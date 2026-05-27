"""Admin payments router — Stripe status & transactions."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.client import Client
from app.middleware.auth import get_current_admin
from app.services.stripe_service import StripeService

router = APIRouter()


@router.get("/payments/status")
async def get_payment_status(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get Stripe connection status."""
    await StripeService.configure_from_db(db)
    return await StripeService.get_account_info()


@router.get("/payments/transactions")
async def get_transactions(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get recent Stripe transactions."""
    await StripeService.configure_from_db(db)
    items = await StripeService.get_recent_transactions()
    return {"items": items}
