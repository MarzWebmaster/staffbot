"""Admin router for token top-up package CRUD."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List

from app.database import get_db
from app.models.client import Client
from app.models.token_topup import TokenTopupPackage, TokenTopup
from app.middleware.auth import get_current_admin

router = APIRouter()


@router.get("/", response_model=list[dict])
async def list_topup_packages(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all top-up packages (admin only)."""
    result = await db.execute(
        select(TokenTopupPackage).order_by(TokenTopupPackage.sort_order)
    )
    pkgs = result.scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "tokens": p.tokens,
            "price_myr": p.price_myr,
            "is_active": p.is_active,
            "sort_order": p.sort_order,
        }
        for p in pkgs
    ]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_topup_package(
    data: dict,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new top-up package."""
    pkg = TokenTopupPackage(
        name=data.get("name"),
        description=data.get("description", ""),
        tokens=data.get("tokens", 0),
        price_myr=data.get("price_myr", 0),
        sort_order=data.get("sort_order", 0),
        is_active=True,
    )
    db.add(pkg)
    await db.commit()
    await db.refresh(pkg)
    return {"message": "Top-up package created", "id": pkg.id}


@router.put("/{pkg_id}")
async def update_topup_package(
    pkg_id: int,
    data: dict,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a top-up package."""
    result = await db.execute(select(TokenTopupPackage).where(TokenTopupPackage.id == pkg_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")

    for key in ("name", "description", "tokens", "price_myr", "sort_order", "is_active"):
        if key in data:
            setattr(pkg, key, data[key])

    await db.commit()
    return {"message": "Top-up package updated"}


@router.delete("/{pkg_id}")
async def delete_topup_package(
    pkg_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a top-up package."""
    result = await db.execute(select(TokenTopupPackage).where(TokenTopupPackage.id == pkg_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    pkg.is_active = False
    await db.commit()
    return {"message": "Top-up package deactivated"}


@router.get("/history", response_model=list[dict])
async def list_all_topups(
    limit: int = 50,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all token top-up transactions (admin only)."""
    result = await db.execute(
        select(TokenTopup).order_by(TokenTopup.created_at.desc()).limit(limit)
    )
    topups = result.scalars().all()
    return [
        {
            "id": t.id,
            "client_id": t.client_id,
            "tokens": t.tokens,
            "amount_paid": t.amount_paid,
            "status": t.status,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in topups
    ]
