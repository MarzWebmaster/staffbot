"""Containers router — 1 user = 1 container, multiple Staff AI profiles.

Endpoints:
- GET / - List Staff AI profiles for current client
- POST / - Create a new Staff AI (deploy container if first one)
- GET /{id} - Get Staff AI details
- PUT /{id} - Update Staff AI settings
- DELETE /{id} - Delete a Staff AI profile
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List

from app.database import get_db
from app.models.client import Client
from app.models.container import Container
from app.models.package import Package
from app.models.subscription import Subscription
from app.schemas.container import (
    ContainerCreate, ContainerUpdate, ContainerResponse,
)
from app.middleware.auth import get_current_client
from app.services.docker_service import DockerService

router = APIRouter()


@router.get("", response_model=list[ContainerResponse])
async def list_containers(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """List all Staff AI profiles for the authenticated client."""
    result = await db.execute(
        select(Container).where(Container.client_id == current_user.id)
        .order_by(Container.created_at.desc())
    )
    profiles = result.scalars().all()

    # Enrich with Docker status if container exists
    docker = DockerService()
    containers = docker.get_client_containers(current_user.id)

    enriched = []
    for p in profiles:
        data = {
            "id": p.id,
            "client_id": p.client_id,
            "name": p.name,
            "container_name": p.container_name,
            "image": p.image,
            "port": p.port,
            "status": p.status,
            "skills": p.skills,
            "tools": p.tools,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        # If this profile is the user's main container, get Docker status
        if p.container_name and p.container_name in containers:
            data["docker_status"] = containers[p.container_name]["status"]
            if data["docker_status"] == "running":
                data["status"] = "running"
        enriched.append(data)

    return enriched


@router.post("", response_model=ContainerResponse, status_code=status.HTTP_201_CREATED)
async def create_container(
    data: ContainerCreate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Create a new Staff AI profile.
    
    First profile → deploys Docker container for the user.
    Subsequent profiles → just create records (same Docker container).
    """
    # Check subscription
    sub_result = await db.execute(
        select(Subscription).where(Subscription.client_id == current_user.id)
    )
    sub = sub_result.scalar_one_or_none()
    if not sub or sub.status != "active":
        raise HTTPException(status_code=403, detail="No active subscription")

    # Get package limits
    pkg_result = await db.execute(
        select(Package).where(Package.name == current_user.package, Package.is_active == True)
    )
    pkg = pkg_result.scalar_one_or_none()
    bot_limit = pkg.bot_limit if pkg else 1

    # Count existing Staff AI profiles
    count_result = await db.execute(
        select(Container).where(Container.client_id == current_user.id)
    )
    existing_profiles = count_result.scalars().all()
    existing_count = len(existing_profiles)

    if existing_count >= bot_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Staff AI limit reached ({bot_limit}). Upgrade your package to add more.",
        )

    # Validate skill/tool categories against package limits
    if data.skills and pkg and pkg.skill_category_ids:
        from app.config import get_settings
        settings = get_settings()
        # Fetch category names to validate
        import json
        try:
            import asyncpg
            conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
            try:
                rows = await conn.fetch(
                    "SELECT id, name FROM skill_categories WHERE id = ANY($1::int[])",
                    pkg.skill_category_ids
                )
                allowed_skills = {r["name"] for r in rows}
                invalid = [s for s in data.skills if s not in allowed_skills]
                if invalid:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Skills {invalid} not in your package. Upgrade to access them."
                    )
            finally:
                await conn.close()
        except Exception as e:
            if "asyncpg" in str(type(e)):
                pass  # asyncpg specific, skip validation silently

    # Generate Staff AI name
    bot_number = existing_count + 1
    name = data.name or f"StaffBot {bot_number}"

    # Check if user already has a Docker container
    docker = DockerService()
    existing_container = docker.get_client_container(current_user.id)

    container = Container(
        client_id=current_user.id,
        name=name,
        skills=data.skills or ["communication", "operations", "memory"],
        tools=data.tools or ["whatsapp", "telegram", "email"],
        status="pending",
    )

    if existing_container:
        # User already has a container — just create Staff AI profile
        container.container_name = existing_container.get("name")
        container.port = existing_container.get("port")
        container.image = existing_container.get("image", "staffbot-core:latest")
        container.status = existing_container.get("status", "running")
    else:
        # First Staff AI — deploy a Docker container
        try:
            deploy_result = docker.deploy_client_container(
                client_id=current_user.id,
                client_name=current_user.name,
                subdomain=current_user.subdomain,
                package=current_user.package,
                cpu_limit=pkg.cpu_limit if pkg else 1.0,
                memory_limit_mb=pkg.memory_limit_mb if pkg else 512,
                storage_limit_gb=pkg.storage_limit_gb if pkg else 10,
                skill_categories=pkg.skill_category_ids if pkg else [],
                tool_categories=pkg.tool_category_ids if pkg else [],
            )
            container.container_name = deploy_result.get("container_name", f"staffbot-{current_user.id}")
            container.port = deploy_result.get("port")
            container.image = deploy_result.get("image", "staffbot-core:latest")
            container.status = deploy_result.get("status", "running")
        except Exception as e:
            container.status = "error"

    db.add(container)
    await db.commit()
    await db.refresh(container)
    return container


@router.get("/{container_id}", response_model=ContainerResponse)
async def get_container(
    container_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get Staff AI profile details."""
    result = await db.execute(
        select(Container).where(
            Container.id == container_id,
            Container.client_id == current_user.id,
        )
    )
    container = result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff AI not found")
    return container


@router.put("/{container_id}", response_model=ContainerResponse)
async def update_container(
    container_id: int,
    data: ContainerUpdate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Update Staff AI profile settings."""
    result = await db.execute(
        select(Container).where(
            Container.id == container_id,
            Container.client_id == current_user.id,
        )
    )
    container = result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff AI not found")

    update_data = data.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(container, key, value)

    await db.commit()
    await db.refresh(container)
    return container


@router.delete("/{container_id}")
async def delete_container(
    container_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Delete a Staff AI profile.
    
    If this is the last profile, also remove the Docker container.
    """
    result = await db.execute(
        select(Container).where(
            Container.id == container_id,
            Container.client_id == current_user.id,
        )
    )
    container = result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff AI not found")

    # Check if this is the last profile
    remaining = await db.execute(
        select(Container).where(
            Container.client_id == current_user.id,
            Container.id != container_id,
        )
    )
    remaining_profiles = remaining.scalars().all()

    if not remaining_profiles and container.container_name:
        # Last profile — remove Docker container too
        try:
            docker = DockerService()
            docker.remove_container(container.container_name)
        except Exception:
            pass  # Docker container might already be gone

    await db.delete(container)
    await db.commit()
    return {"message": f"Staff AI '{container.name}' deleted successfully"}
