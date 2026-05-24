"""
Subscriptions router.

Endpoints:
- POST /create-checkout - Create a Stripe checkout session
- GET /{client_id} - Get subscription details
- PUT /{client_id}/tokens - Update token usage
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database import get_db
from app.models.client import Client
from app.models.subscription import Subscription
from app.schemas.subscription import SubscriptionResponse, TokenUsageUpdate
from app.middleware.auth import get_current_client, get_current_admin
from app.services.stripe_service import StripeService
from app.config import get_settings

router = APIRouter()
settings = get_settings()


@router.post("/create-checkout")
async def create_checkout(
    package: str,
    success_url: str = "",
    cancel_url: str = "",
    current_user: Client = Depends(get_current_client),
):
    """Create a Stripe Checkout Session for subscription upgrade."""
    # Get package price
    from sqlalchemy import select as se
    from app.database import async_session_factory
    from app.models.package import Package

    async with async_session_factory() as db:
        result = await db.execute(se(Package).where(Package.name == package, Package.is_active == True))
        pkg = result.scalar_one_or_none()

    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Package '{package}' not found")

    success = success_url or f"{settings.LANDING_PAGE_URL}/payment/success"
    cancel = cancel_url or f"{settings.LANDING_PAGE_URL}/pricing"

    session = await StripeService.create_checkout_session(
        name=current_user.name,
        email=current_user.email,
        package=package,
        amount=pkg.price_monthly,
        success_url=success,
        cancel_url=cancel,
    )

    return {
        "checkout_url": session.get("url"),
        "session_id": session.get("id"),
        "test_mode": session.get("test_mode", False),
    }


@router.get("/{client_id}", response_model=SubscriptionResponse)
async def get_subscription(
    client_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get subscription details for a client."""
    if current_user.id != client_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(
        select(Subscription).where(Subscription.client_id == client_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No subscription found")

    return sub


@router.put("/{client_id}/tokens")
async def update_token_usage(
    client_id: int,
    data: TokenUsageUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update token usage (called by Server B container)."""
    result = await db.execute(
        select(Subscription).where(Subscription.client_id == client_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No subscription found")

    sub.managed_token_used = data.managed_token_used

    # Check if quota exceeded
    if sub.managed_token_quota > 0 and sub.managed_token_used >= sub.managed_token_quota:
        # Notify client that quota is exhausted
        from app.services.notification_service import NotificationService
        await NotificationService.notify_client(
            client_id=client_id,
            channels=["whatsapp", "email", "in-app"],
            subject="⚠️ Token Quota Exhausted",
            body=(
                "Your StaffBot managed token quota has been used up. "
                "Please add your own API key via the dashboard to continue using StaffBot, "
                "or upgrade your plan for more tokens."
            ),
        )

    await db.commit()
    return {"message": "Token usage updated", "quota_remaining": max(0, sub.managed_token_quota - sub.managed_token_used)}
