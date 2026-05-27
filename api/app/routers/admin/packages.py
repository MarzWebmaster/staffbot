"""
Admin packages router — CRUD for pricing packages + apply resources to existing containers.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client import Client as ClientModel
from app.models.package import Package
from app.schemas.admin import PackageCreate, PackageUpdate
from app.middleware.auth import get_current_admin
from app.services.server_b_service import ServerBService

router = APIRouter()


@router.get("/", response_model=list[dict])
async def list_packages(
    db: AsyncSession = Depends(get_db),
):
    """List all active packages (public)."""
    result = await db.execute(
        select(Package).where(Package.is_active == True).order_by(Package.sort_order)
    )
    packages = result.scalars().all()
    return [
        {
            "id": pkg.id,
            "name": pkg.name,
            "display_name": pkg.display_name,
            "price_monthly": pkg.price_monthly,
            "price_yearly": pkg.price_yearly,
            "description": pkg.description,
            "features": pkg.features or [],
            "bot_limit": pkg.bot_limit,
            "managed_tokens": pkg.managed_tokens,
            "cpu_limit": pkg.cpu_limit,
            "memory_limit_mb": pkg.memory_limit_mb,
            "storage_limit_gb": pkg.storage_limit_gb,
        }
        for pkg in packages
    ]


@router.get("/all", response_model=list[dict])
async def list_all_packages(
    admin: ClientModel = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all packages including inactive (admin only)."""
    result = await db.execute(
        select(Package).order_by(Package.sort_order)
    )
    packages = result.scalars().all()
    return [
        {
            "id": pkg.id,
            "name": pkg.name,
            "display_name": pkg.display_name,
            "price_monthly": pkg.price_monthly,
            "price_yearly": pkg.price_yearly,
            "description": pkg.description,
            "features": pkg.features or [],
            "bot_limit": pkg.bot_limit,
            "managed_tokens": pkg.managed_tokens,
            "cpu_limit": pkg.cpu_limit,
            "memory_limit_mb": pkg.memory_limit_mb,
            "storage_limit_gb": pkg.storage_limit_gb,
            "sort_order": pkg.sort_order,
            "is_active": pkg.is_active,
        }
        for pkg in packages
    ]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_package(
    data: PackageCreate,
    admin: ClientModel = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new package."""
    pkg = Package(
        name=data.name,
        display_name=data.display_name,
        price_monthly=data.price_monthly,
        price_yearly=data.price_yearly,
        description=data.description,
        features=data.features,
        bot_limit=data.bot_limit,
        managed_tokens=data.managed_tokens,
        cpu_limit=data.cpu_limit,
        memory_limit_mb=data.memory_limit_mb,
        storage_limit_gb=data.storage_limit_gb,
        sort_order=data.sort_order,
        is_active=True,
    )
    db.add(pkg)
    await db.commit()
    await db.refresh(pkg)
    return {"message": f"Package '{pkg.name}' created", "id": pkg.id}


@router.put("/{package_id}")
async def update_package(
    package_id: int,
    data: PackageUpdate,
    admin: ClientModel = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a package."""
    result = await db.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    update_data = data.model_dump(exclude_none=True)
    for key, value in update_data.items():
        if key != "id":
            setattr(pkg, key, value)

    await db.commit()
    return {"message": f"Package '{pkg.name}' updated"}


@router.delete("/{package_id}")
async def delete_package(
    package_id: int,
    admin: ClientModel = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a package (set inactive)."""
    result = await db.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    pkg.is_active = False
    await db.commit()
    return {"message": f"Package '{pkg.name}' deactivated"}


@router.post("/{package_id}/apply")
async def apply_package_resources(
    package_id: int,
    admin: ClientModel = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Apply current resource limits from a package to all running containers with that package.

    - CPU & RAM: Updated live via docker update (no restart).
    - Storage: Requires container recreation — logged as warning.
    """
    # 1. Get package
    result = await db.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")

    cpu = pkg.cpu_limit or 1.0
    ram = pkg.memory_limit_mb or 512
    storage = pkg.storage_limit_gb or 10

    # 2. Find clients with active containers using this package
    # Clients have a `package` column (string) that matches pkg.name
    client_result = await db.execute(
        select(ClientModel).where(
            ClientModel.package == pkg.name,
            ClientModel.container_id.isnot(None)
        )
    )
    clients = client_result.scalars().all()

    if not clients:
        return {
            "message": f"No running containers found for package '{pkg.name}'",
            "package_id": package_id,
            "package_name": pkg.name,
            "updated_cpu_ram": [],
            "storage_warnings": [],
            "total_containers": 0,
        }

    # 3. Apply resource limits to each container
    updated = []
    warnings = []

    for client in clients:
        container_name = None
        # Try to derive container name from client info
        if hasattr(client, 'containers') and client.containers:
            for c in client.containers:
                if c.name:
                    container_name = c.name
                    break

        if not container_name and client.subdomain:
            container_name = f"staffbot-{client.subdomain}"

        if not container_name:
            warnings.append({
                "client_id": client.id,
                "client_name": client.name,
                "reason": "No container name found"
            })
            continue

        # Apply CPU & RAM via docker update
        try:
            result = await ServerBService.update_resource_limits(
                container_name=container_name,
                cpu_limit=cpu,
                memory_limit_mb=ram,
                storage_limit_gb=storage,
            )
            updated.append({
                "client_id": client.id,
                "client_name": client.name,
                "container_name": container_name,
                "result": result,
            })
            # Storage warning is always present since docker update can't change it
            if "warning" in result:
                warnings.append({
                    "client_id": client.id,
                    "client_name": client.name,
                    "container_name": container_name,
                    "warning": result["warning"]
                })
        except HTTPException as e:
            warnings.append({
                "client_id": client.id,
                "client_name": client.name,
                "container_name": container_name,
                "error": e.detail,
            })
        except Exception as e:
            warnings.append({
                "client_id": client.id,
                "client_name": client.name,
                "container_name": container_name,
                "error": str(e),
            })

    return {
        "message": f"Applied resources for {len(updated)} container(s)",
        "package_id": package_id,
        "package_name": pkg.name,
        "new_limits": {"cpu": cpu, "ram_mb": ram, "storage_gb": storage},
        "updated_cpu_ram": updated,
        "storage_warnings": warnings,
        "total_containers": len(clients),
    }