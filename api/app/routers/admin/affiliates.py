"""
Admin Affiliates router — manage affiliates, view reports, process payouts.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional

from app.database import get_db
from app.models.client import Client
from app.models.affiliate import (
    Affiliate, AffiliateReferral, AffiliateCommission,
    AffiliatePayout, AffiliateClick,
)
from app.schemas.affiliate import (
    AffiliateProfileResponse, AffiliateAdminUpdate,
    AffiliateReferralResponse, AffiliateCommissionResponse,
    AffiliatePayoutResponse, AffiliatePayoutProcess,
    AffiliateLeaderboardEntry,
)
from app.middleware.auth import get_current_admin
from app.utils.encryption import mask_key

router = APIRouter()


# ── Affiliate Profiles ─────────────────────────────────────────────

@router.get("/", response_model=list[AffiliateProfileResponse])
async def list_affiliates(
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all affiliate profiles (admin)."""
    query = select(Affiliate)

    if status_filter:
        query = query.where(Affiliate.status == status_filter)

    query = query.order_by(Affiliate.total_earnings.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    affiliates = result.scalars().all()

    response = []
    for aff in affiliates:
        client_data = None
        if aff.client_id:
            c_result = await db.execute(select(Client).where(Client.id == aff.client_id))
            client_data = c_result.scalar_one_or_none()

        response.append({
            "id": aff.id,
            "client_id": aff.client_id,
            "referral_code": aff.referral_code,
            "referral_link": f"https://staffbot.my/ref/{aff.referral_code}",
            "commission_rate": aff.commission_rate,
            "total_earnings": aff.total_earnings,
            "pending_earnings": aff.pending_earnings,
            "paid_earnings": aff.paid_earnings,
            "total_referrals": aff.total_referrals,
            "total_clicks": aff.total_clicks,
            "status": aff.status,
            "is_auto_approve": aff.is_auto_approve,
            "min_payout": aff.min_payout,
            "notes": aff.notes,
            "created_at": aff.created_at,
            "client_name": client_data.name if client_data else "Unknown",
            "client_email": client_data.email if client_data else "",
        })

    return response


@router.get("/{affiliate_id}", response_model=AffiliateProfileResponse)
async def get_affiliate(
    affiliate_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get affiliate profile details."""
    result = await db.execute(select(Affiliate).where(Affiliate.id == affiliate_id))
    aff = result.scalar_one_or_none()
    if not aff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Affiliate not found")

    return {
        "id": aff.id,
        "client_id": aff.client_id,
        "referral_code": aff.referral_code,
        "referral_link": f"https://staffbot.my/ref/{aff.referral_code}",
        "commission_rate": aff.commission_rate,
        "total_earnings": aff.total_earnings,
        "pending_earnings": aff.pending_earnings,
        "paid_earnings": aff.paid_earnings,
        "total_referrals": aff.total_referrals,
        "total_clicks": aff.total_clicks,
        "status": aff.status,
        "is_auto_approve": aff.is_auto_approve,
        "min_payout": aff.min_payout,
        "notes": aff.notes,
        "created_at": aff.created_at,
    }


@router.put("/{affiliate_id}")
async def update_affiliate(
    affiliate_id: int,
    data: AffiliateAdminUpdate,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update affiliate profile (admin)."""
    result = await db.execute(select(Affiliate).where(Affiliate.id == affiliate_id))
    aff = result.scalar_one_or_none()
    if not aff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Affiliate not found")

    update_data = data.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(aff, key, value)

    await db.commit()
    return {"message": "Affiliate updated"}


# ── Referrals ──────────────────────────────────────────────────────

@router.get("/{affiliate_id}/referrals", response_model=list[AffiliateReferralResponse])
async def list_affiliate_referrals(
    affiliate_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List referrals for an affiliate."""
    result = await db.execute(
        select(AffiliateReferral)
        .where(AffiliateReferral.affiliate_id == affiliate_id)
        .order_by(AffiliateReferral.created_at.desc())
    )
    refs = result.scalars().all()
    return [
        {
            "id": r.id,
            "referred_email": r.referred_email,
            "referred_name": r.referred_name,
            "status": r.status,
            "commission_earned": r.commission_earned,
            "package_signed": r.package_signed,
            "created_at": r.created_at,
            "converted_at": r.converted_at,
        }
        for r in refs
    ]


@router.get("/{affiliate_id}/commissions", response_model=list[AffiliateCommissionResponse])
async def list_affiliate_commissions(
    affiliate_id: int,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List commissions for an affiliate."""
    result = await db.execute(
        select(AffiliateCommission)
        .where(AffiliateCommission.affiliate_id == affiliate_id)
        .order_by(AffiliateCommission.created_at.desc())
    )
    comms = result.scalars().all()
    return [
        {
            "id": c.id,
            "amount": c.amount,
            "description": c.description,
            "status": c.status,
            "created_at": c.created_at,
            "paid_at": c.paid_at,
        }
        for c in comms
    ]


# ── Payouts ────────────────────────────────────────────────────────

@router.get("/payouts/all", response_model=list[AffiliatePayoutResponse])
async def list_all_payouts(
    status_filter: Optional[str] = None,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all payout requests."""
    query = select(AffiliatePayout)
    if status_filter:
        query = query.where(AffiliatePayout.status == status_filter)
    query = query.order_by(AffiliatePayout.created_at.desc())

    result = await db.execute(query)
    payouts = result.scalars().all()
    return [
        {
            "id": p.id,
            "amount": p.amount,
            "method": p.method,
            "account_details": p.account_details,
            "status": p.status,
            "admin_notes": p.admin_notes,
            "created_at": p.created_at,
            "processed_at": p.processed_at,
        }
        for p in payouts
    ]


@router.put("/payouts/{payout_id}")
async def process_payout(
    payout_id: int,
    data: AffiliatePayoutProcess,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Process a payout request (approve/reject)."""
    result = await db.execute(select(AffiliatePayout).where(AffiliatePayout.id == payout_id))
    payout = result.scalar_one_or_none()
    if not payout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payout not found")

    payout.status = data.status
    payout.admin_notes = data.admin_notes
    payout.processed_by = admin.id

    if data.status in ("completed", "rejected"):
        payout.processed_at = datetime.now(timezone.utc)

    # If completed, move from pending to paid
    if data.status == "completed":
        aff_result = await db.execute(select(Affiliate).where(Affiliate.id == payout.affiliate_id))
        aff = aff_result.scalar_one_or_none()
        if aff:
            aff.pending_earnings = max(0, aff.pending_earnings - payout.amount)
            aff.paid_earnings = (aff.paid_earnings or 0) + payout.amount

            # Mark related commissions as paid
            comm_result = await db.execute(
                select(AffiliateCommission).where(AffiliateCommission.payout_id == payout.id)
            )
            for c in comm_result.scalars().all():
                c.status = "paid"
                c.paid_at = payout.processed_at

    await db.commit()
    return {"message": f"Payout {data.status}"}


# ── Statistics ─────────────────────────────────────────────────────

@router.get("/stats/summary")
async def get_affiliate_stats(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get overall affiliate program statistics."""
    total_aff = (await db.execute(select(func.count(Affiliate.id)))).scalar() or 0
    active_aff = (await db.execute(
        select(func.count(Affiliate.id)).where(Affiliate.status == "active")
    )).scalar() or 0
    total_paid = (await db.execute(
        select(func.coalesce(func.sum(Affiliate.paid_earnings), 0))
    )).scalar() or 0.0
    total_pending = (await db.execute(
        select(func.coalesce(func.sum(Affiliate.pending_earnings), 0))
    )).scalar() or 0.0
    total_referrals = (await db.execute(
        select(func.coalesce(func.sum(Affiliate.total_referrals), 0))
    )).scalar() or 0
    pending_payouts = (await db.execute(
        select(func.count(AffiliatePayout.id))
        .where(AffiliatePayout.status == "pending")
    )).scalar() or 0

    # This month stats
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    referrals_this_month = (await db.execute(
        select(func.count(AffiliateReferral.id))
        .where(AffiliateReferral.created_at >= first_of_month)
    )).scalar() or 0

    return {
        "total_affiliates": total_aff,
        "active_affiliates": active_aff,
        "total_paid": total_paid,
        "total_pending_earnings": total_pending,
        "total_referrals": total_referrals,
        "pending_payout_requests": pending_payouts,
        "referrals_this_month": referrals_this_month,
    }


# ── Leaderboard ────────────────────────────────────────────────────

@router.get("/leaderboard")
async def get_leaderboard(
    limit: int = 20,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get full affiliate leaderboard (admin sees everything)."""
    result = await db.execute(
        select(Affiliate)
        .where(Affiliate.total_earnings > 0)
        .order_by(Affiliate.total_earnings.desc())
        .limit(limit)
    )
    affiliates = result.scalars().all()

    entries = []
    for rank, aff in enumerate(affiliates, 1):
        client_data = None
        if aff.client_id:
            c_result = await db.execute(select(Client).where(Client.id == aff.client_id))
            client_data = c_result.scalar_one_or_none()

        name = client_data.name if client_data else "Unknown"
        # Mask name: show first letter + *** + last letter if long enough
        if len(name) > 3:
            masked = f"{name[0]}***{name[-1]}"
        elif len(name) > 1:
            masked = f"{name[0]}***"
        else:
            masked = "***"

        entries.append({
            "rank": rank,
            "name_masked": masked,
            "total_earnings": aff.total_earnings,
            "total_referrals": aff.total_referrals,
            "commission_rate": aff.commission_rate,
        })

    return {"entries": entries, "total_affiliates": len(entries)}
