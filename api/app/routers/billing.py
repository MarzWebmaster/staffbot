"""User billing router — token top-up + payment flow."""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database import get_db
from app.models.client import Client
from app.models.subscription import Subscription
from app.models.token_topup import TokenTopupPackage, TokenTopup
from app.middleware.auth import get_current_client
from app.services.stripe_service import StripeService
from app.config import get_settings

router = APIRouter()
settings = get_settings()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/topup-packages", response_model=list[dict])
async def list_topup_packages(
    db: AsyncSession = Depends(get_db),
):
    """List available token top-up packages."""
    result = await db.execute(
        select(TokenTopupPackage)
        .where(TokenTopupPackage.is_active == True)
        .order_by(TokenTopupPackage.sort_order)
    )
    pkgs = result.scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "tokens": p.tokens,
            "price_myr": p.price_myr,
        }
        for p in pkgs
    ]


@router.post("/topup-checkout")
async def create_topup_checkout(
    package_id: int = Query(...),
    success_url: str = "",
    cancel_url: str = "",
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout session for token top-up."""
    # Get top-up package
    result = await db.execute(
        select(TokenTopupPackage).where(
            TokenTopupPackage.id == package_id,
            TokenTopupPackage.is_active == True,
        )
    )
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=404, detail="Top-up package not found")

    success = success_url or f"{settings.LANDING_PAGE_URL}/billing/topup-success"
    cancel = cancel_url or f"{settings.LANDING_PAGE_URL}/billing"

    # Create Stripe checkout session
    session = await StripeService.create_topup_session(
        client_id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        package_id=pkg.id,
        package_name=pkg.name,
        tokens=pkg.tokens,
        amount=pkg.price_myr,
        success_url=success,
        cancel_url=cancel,
    )

    return {
        "checkout_url": session.get("url"),
        "session_id": session.get("id"),
        "test_mode": session.get("test_mode", False),
    }


@router.get("/topup-history", response_model=list[dict])
async def topup_history(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's token top-up history."""
    result = await db.execute(
        select(TokenTopup)
        .where(TokenTopup.client_id == current_user.id)
        .order_by(TokenTopup.created_at.desc())
        .limit(50)
    )
    topups = result.scalars().all()
    return [
        {
            "id": t.id,
            "tokens": t.tokens,
            "amount_paid": t.amount_paid,
            "status": t.status,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in topups
    ]


@router.get("/usage")
async def get_token_usage(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get current token usage and remaining quota."""
    result = await db.execute(
        select(Subscription).where(Subscription.client_id == current_user.id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return {"quota": 0, "used": 0, "remaining": 0, "percentage": 0}

    quota = sub.managed_token_quota or 0
    used = sub.managed_token_used or 0
    remaining = max(0, quota - used)
    percentage = (used / quota * 100) if quota > 0 else 0

    return {
        "quota": quota,
        "used": used,
        "remaining": remaining,
        "percentage": round(percentage, 1),
    }
