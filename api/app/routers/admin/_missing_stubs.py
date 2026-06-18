"""Stub admin endpoints — fill in real data later.

These are the endpoints called by admin/*.html pages but not yet implemented.
Return empty/placeholder data so the admin dashboard doesn't show "Not Found" toasts.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.middleware.auth import get_current_admin
from app.models.client import Client
from app.models.subscription import Subscription

router = APIRouter()


@router.get("/billing/overview")
async def billing_overview(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin billing overview — total revenue, MRR, active subscriptions."""
    # Count active subscriptions
    result = await db.execute(
        select(func.count(Subscription.id)).where(Subscription.status == "active")
    )
    active_count = result.scalar() or 0

    # Sum revenue from active subscriptions (sum of price)
    result = await db.execute(
        select(func.coalesce(func.sum(Subscription.price), 0))
        .where(Subscription.status == "active")
    )
    mrr = float(result.scalar() or 0)

    return {
        "active_subscriptions": active_count,
        "mrr": mrr,
        "arr": mrr * 12,
        "total_revenue": mrr * 12,  # TODO: compute from payments table
        "churn_rate": 0.0,
        "currency": "MYR",
    }


@router.get("/revenue")
async def revenue(
    period: str = Query("30d", description="7d, 30d, 90d, 1y"),
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Revenue chart data."""
    return {
        "labels": [],
        "values": [],
        "period": period,
        "currency": "MYR",
    }


@router.get("/usage/by-client")
async def usage_by_client(
    period: str = Query("30d"),
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Token usage breakdown by client."""
    return {
        "clients": [],
        "period": period,
    }


@router.get("/affiliates/referrals")
async def all_affiliate_referrals(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """All affiliate referrals (admin view, no affiliate_id filter)."""
    return {"items": [], "total": 0}


@router.get("/affiliates/payouts")
async def affiliate_payouts(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """All affiliate payouts (paginated list)."""
    return {"items": [], "total": 0, "page": 1, "page_size": 20}
