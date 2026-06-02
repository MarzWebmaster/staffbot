"""
Containers router.

Manages AI Staff (bot containers) lifecycle:
- CREATE: Register → Check package → Deploy Docker → Update status
- READ: List/get containers for current client
- UPDATE: Name, skills, config
- DELETE: Remove container + Docker cleanup

Deployment flow:
  1. Create DB record → status="provisioning"
  2. Fetch Package for resource limits (CPU, RAM)
  3. Generate subdomain/container_name
  4. Call DockerService.deploy_container() — tries Gateway → local → simulated
  5. Update record with results
     - Success → status="running", save container_name/port/image
     - Failure → status="error", save error message
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.models.client import Client
from app.models.container import Container
from app.models.package import Package
from app.schemas.container import (
    ContainerCreate, ContainerUpdate, ContainerResponse,
)
from app.middleware.auth import get_current_client
from app.services.docker_service import DockerService

import logging
logger = logging.getLogger(__name__)

router = APIRouter()

# ─── HELPERS ────────────────────────────────────────────────────────────────

def _generate_container_name(client_id: int, name: str, existing_count: int) -> str:
    """
    Generate a unique container name from the user-provided name.
    Falls back to a numeric pattern if name is generic.
    """
    base = name.strip().lower().replace(" ", "-")
    # Only alphanumeric and hyphens
    import re
    base = re.sub(r"[^a-z0-9-]", "", base)
    if not base or len(base) < 3:
        base = f"staffbot-{client_id}"
    return f"{base}"


async def _get_package_limits(
    package_name: str,
    db: AsyncSession,
) -> dict:
    """
    Fetch resource limits from the Package config.
    Returns defaults if package not found.
    """
    if not package_name:
        return {"bot_limit": 1, "cpu_limit": 1.0, "memory_limit_mb": 512, "storage_limit_gb": 10}

    result = await db.execute(
        select(Package).where(Package.name == package_name, Package.is_active == True)
    )
    pkg = result.scalar_one_or_none()
    if pkg:
        return {
            "bot_limit": pkg.bot_limit or 1,
            "cpu_limit": pkg.cpu_limit or 1.0,
            "memory_limit_mb": pkg.memory_limit_mb or 512,
            "storage_limit_gb": pkg.storage_limit_gb or 10,
        }
    return {"bot_limit": 1, "cpu_limit": 1.0, "memory_limit_mb": 512, "storage_limit_gb": 10}


# ─── ENDPOINTS ──────────────────────────────────────────────────────────────


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


@router.get("/", response_model=list[ContainerResponse], include_in_schema=False)
async def list_containers_slash(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """List all containers (with trailing slash)."""
    return await list_containers(current_user=current_user, db=db)


@router.post("", response_model=ContainerResponse, status_code=status.HTTP_201_CREATED)
async def create_container(
    data: ContainerCreate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Create and deploy a new AI Staff (Docker container).

    Flow:
    1. Check package bot limit
    2. Create DB record → status = "provisioning"
    3. Look up package resource limits
    4. Deploy actual Docker container (local Docker → local → simulated)
    5. Update DB record with results
    """
    # ── Step 1: Check package bot limit ──────────────────────────
    package_limits = await _get_package_limits(current_user.package, db)
    bot_limit = package_limits["bot_limit"]

    count_result = await db.execute(
        select(Container).where(Container.client_id == current_user.id)
    )
    existing_count = len(count_result.scalars().all())

    if existing_count >= bot_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Bot limit reached ({bot_limit}). Upgrade your package to add more bots.",
        )

    # ── Step 2: Create DB record ─────────────────────────────────
    bot_number = existing_count + 1
    name = data.name or f"StaffBot {bot_number}"
    skills = data.skills or ["chat", "memory"]

    container = Container(
        client_id=current_user.id,
        name=name,
        container_name="",
        status="provisioning",
        skills=skills,
    )
    db.add(container)
    await db.commit()
    await db.refresh(container)

    # ── Step 3: Prepare deployment ───────────────────────────────
    container_name = _generate_container_name(
        client_id=current_user.id,
        name=name,
        existing_count=existing_count,
    )

    cpu_limit = package_limits["cpu_limit"]
    memory_limit_mb = package_limits["memory_limit_mb"]
    storage_limit_gb = package_limits["storage_limit_gb"]

    env_vars = {
        "CLIENT_ID": str(current_user.id),
        "CLIENT_NAME": current_user.name or "",
        "CLIENT_EMAIL": current_user.email or "",
        "CONTAINER_NAME": container_name,
        "SKILLS": ",".join(skills),
        "CPU_LIMIT": str(cpu_limit),
        "MEMORY_LIMIT_MB": str(memory_limit_mb),
        "STORAGE_LIMIT_GB": str(storage_limit_gb),
    }

    # ── Step 4: Deploy container ─────────────────────────────────
    try:
        deploy_result = await DockerService.deploy_container(
            client_id=current_user.id,
            name=container_name,
            subdomain=container_name,
            skills=skills,
            env_vars=env_vars,
            cpu_limit=cpu_limit,
            memory_limit_mb=memory_limit_mb,
            storage_limit_gb=storage_limit_gb,
        )

        # ── Step 5: Update record with results ───────────────────
        if deploy_result.get("success"):
            container.status = "running"
            container.container_name = deploy_result.get("container_name", container_name)
            container.image = STAFFBOT_CORE_IMAGE if (STAFFBOT_CORE_IMAGE := __import__('os').environ.get("STAFFBOT_CORE_IMAGE", "staffbot-core:latest")) else "staffbot-core:latest"
            container.port = deploy_result.get("port")
            container.env_vars = env_vars
            logger.info(
                f"Container {container.id} ({container_name}) deployed successfully "
                f"via {deploy_result.get('deploy_method', 'unknown')}"
            )
        else:
            container.status = "error"
            container.env_vars = {"error": deploy_result.get("message", "Deployment failed")}
            logger.error(
                f"Container {container.id} ({container_name}) deployment failed: "
                f"{deploy_result.get('message', 'Unknown error')}. "
                f"Method: {deploy_result.get('deploy_method', 'unknown')}"
            )

    except Exception as e:
        container.status = "error"
        container.env_vars = {"error": str(e)}
        logger.exception(f"Container {container.id} deployment exception: {e}")

    await db.commit()
    await db.refresh(container)
    return container


import os as _os
# Get image from env for use in endpoint
STAFFBOT_CORE_IMAGE = _os.environ.get("STAFFBOT_CORE_IMAGE", "staffbot-core:latest")


@router.post("/", response_model=ContainerResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_container_slash(
    data: ContainerCreate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Create a new bot container (with trailing slash)."""
    return await create_container(data=data, current_user=current_user, db=db)


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
    """Update container settings (name, skills, etc.)."""
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
    """
    Delete a bot container.
    Removes both the DB record and the actual Docker container.
    """
    result = await db.execute(
        select(Container).where(
            Container.id == container_id,
            Container.client_id == current_user.id,
        )
    )
    container = result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Container not found")

    # Remove Docker container if it was deployed
    if container.container_name:
        try:
            await DockerService.remove_container(container.container_name)
        except Exception as e:
            logger.warning(f"Failed to remove Docker container {container.container_name}: {e}")

    await db.delete(container)
    await db.commit()
    return {"message": f"Container '{container.name}' deleted successfully"}
