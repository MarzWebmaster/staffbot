"""
Containers router.

Endpoints:
- GET / - List containers for current client
- POST / - Create a new container (bot)
- GET /{id} - Get container details
- PUT /{id} - Update container
- DELETE /{id} - Delete container
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.models.client import Client
from app.models.container import Container
from app.schemas.container import (
    ContainerCreate, ContainerUpdate, ContainerResponse,
)
from app.middleware.auth import get_current_client

router = APIRouter()


@router.get("", response_model=list[ContainerResponse])
async def list_containers(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """List all containers for the authenticated client."""
    result = await db.execute(
        select(Container).where(Container.client_id == current_user.id)
        .order_by(Container.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ContainerResponse, status_code=status.HTTP_201_CREATED)
async def create_container(
    data: ContainerCreate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Create a new bot container (if within package limits)."""
    # Count existing containers
    count_result = await db.execute(
        select(Container).where(Container.client_id == current_user.id)
    )
    existing_count = len(count_result.scalars().all())

    # Get package bot limit
    from app.models.package import Package
    pkg_result = await db.execute(
        select(Package).where(Package.name == current_user.package, Package.is_active == True)
    )
    pkg = pkg_result.scalar_one_or_none()
    bot_limit = pkg.bot_limit if pkg else 1

    if existing_count >= bot_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Bot limit reached ({bot_limit}). Upgrade your package to add more bots.",
        )

    # Generate bot name
    bot_number = existing_count + 1
    name = data.name or f"StaffBot {bot_number}"

    container = Container(
        client_id=current_user.id,
        name=name,
        status="pending",
        skills=data.skills or ["chat", "memory"],
    )
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
    """Get container details."""
    result = await db.execute(
        select(Container).where(
            Container.id == container_id,
            Container.client_id == current_user.id,
        )
    )
    container = result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Container not found")
    return container


@router.put("/{container_id}", response_model=ContainerResponse)
async def update_container(
    container_id: int,
    data: ContainerUpdate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Update container settings."""
    result = await db.execute(
        select(Container).where(
            Container.id == container_id,
            Container.client_id == current_user.id,
        )
    )
    container = result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Container not found")

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
    """Delete a bot container."""
    result = await db.execute(
        select(Container).where(
            Container.id == container_id,
            Container.client_id == current_user.id,
        )
    )
    container = result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Container not found")

    await db.delete(container)
    await db.commit()
    return {"message": f"Container '{container.name}' deleted successfully"}
