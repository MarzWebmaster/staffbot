"""
Admin packages router — CRUD for pricing packages.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client import Client
from app.models.package import Package
from app.schemas.admin import PackageCreate, PackageUpdate
from app.middleware.auth import get_current_admin

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
        }
        for pkg in packages
    ]


@router.get("/all", response_model=list[dict])
async def list_all_packages(
    admin: Client = Depends(get_current_admin),
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
            "sort_order": pkg.sort_order,
            "is_active": pkg.is_active,
        }
        for pkg in packages
    ]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_package(
    data: PackageCreate,
    admin: Client = Depends(get_current_admin),
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
    admin: Client = Depends(get_current_admin),
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
    admin: Client = Depends(get_current_admin),
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
