"""
Affiliates user router — dashboard, referral links, copywriting, leaderboard.
"""
import secrets
import string
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
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
    AffiliateProfileResponse, AffiliateReferralResponse,
    AffiliateCommissionResponse, AffiliatePayoutRequest,
    AffiliatePayoutResponse, AffiliateCopyRequest,
    AffiliateCopyResponse, AffiliateDashboardResponse,
    AffiliateLeaderboardEntry, AffiliateClickResponse,
)
from app.middleware.auth import get_current_client
from app.config import get_settings

router = APIRouter()
settings = get_settings()


def generate_referral_code(length=8) -> str:
    """Generate a random referral code."""
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def mask_name(name: str) -> str:
    """Mask name for leaderboard."""
    if not name:
        return "***"
    if len(name) > 3:
        return f"{name[0]}***{name[-1]}"
    elif len(name) > 1:
        return f"{name[0]}***"
    return "***"


# ── Dashboard ──────────────────────────────────────────────────────

@router.get("/dashboard", response_model=AffiliateDashboardResponse)
async def get_dashboard(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get affiliate dashboard with summary data."""
    # Get or create affiliate profile
    result = await db.execute(
        select(Affiliate).where(Affiliate.client_id == current_user.id)
    )
    aff = result.scalar_one_or_none()

    if not aff:
        return AffiliateDashboardResponse(
            profile=None,
            recent_referrals=[],
            recent_commissions=[],
            recent_clicks=0,
            conversion_rate=0.0,
            leaderboard_rank=None,
            referrals_this_month=0,
            earnings_this_month=0.0,
        )

    # Recent referrals
    ref_result = await db.execute(
        select(AffiliateReferral)
        .where(AffiliateReferral.affiliate_id == aff.id)
        .order_by(AffiliateReferral.created_at.desc())
        .limit(10)
    )
    referrals = ref_result.scalars().all()

    # Recent commissions
    comm_result = await db.execute(
        select(AffiliateCommission)
        .where(AffiliateCommission.affiliate_id == aff.id)
        .order_by(AffiliateCommission.created_at.desc())
        .limit(10)
    )
    commissions = comm_result.scalars().all()

    # Monthly stats
    now = datetime.now(timezone.utc)
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    refs_this_month = (await db.execute(
        select(func.count(AffiliateReferral.id))
        .where(
            AffiliateReferral.affiliate_id == aff.id,
            AffiliateReferral.created_at >= first_of_month,
        )
    )).scalar() or 0

    earnings_this_month = (await db.execute(
        select(func.coalesce(func.sum(AffiliateCommission.amount), 0))
        .where(
            AffiliateCommission.affiliate_id == aff.id,
            AffiliateCommission.status == "paid",
            AffiliateCommission.created_at >= first_of_month,
        )
    )).scalar() or 0.0

    # Conversion rate
    conversion_rate = 0.0
    if aff.total_clicks > 0:
        conversion_rate = round((aff.total_referrals / aff.total_clicks) * 100, 1)

    # Leaderboard rank
    rank_result = await db.execute(
        select(func.count(Affiliate.id))
        .where(
            Affiliate.total_earnings > aff.total_earnings,
            Affiliate.status == "active",
        )
    )
    rank = (rank_result.scalar() or 0) + 1

    profile = {
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
        "created_at": aff.created_at,
    }

    return AffiliateDashboardResponse(
        profile=profile,
        recent_referrals=[
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
            for r in referrals
        ],
        recent_commissions=[
            {
                "id": c.id,
                "amount": c.amount,
                "description": c.description,
                "status": c.status,
                "created_at": c.created_at,
                "paid_at": c.paid_at,
            }
            for c in commissions
        ],
        recent_clicks=aff.total_clicks,
        conversion_rate=conversion_rate,
        leaderboard_rank=rank,
        referrals_this_month=refs_this_month,
        earnings_this_month=earnings_this_month,
    )


# ── Profile Management ─────────────────────────────────────────────

@router.post("/register", response_model=AffiliateProfileResponse)
async def register_affiliate(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Register/create affiliate profile for current user."""
    # Check if already registered
    existing = await db.execute(
        select(Affiliate).where(Affiliate.client_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an affiliate profile",
        )

    # Generate unique code
    code = generate_referral_code()
    while True:
        dup = await db.execute(
            select(Affiliate).where(Affiliate.referral_code == code)
        )
        if not dup.scalar_one_or_none():
            break
        code = generate_referral_code()

    aff = Affiliate(
        client_id=current_user.id,
        referral_code=code,
        commission_rate=10.0,
        is_auto_approve=True,
        min_payout=50.0,
    )
    db.add(aff)
    await db.commit()
    await db.refresh(aff)

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
        "created_at": aff.created_at,
    }


@router.get("/profile", response_model=AffiliateProfileResponse)
async def get_profile(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's affiliate profile."""
    result = await db.execute(
        select(Affiliate).where(Affiliate.client_id == current_user.id)
    )
    aff = result.scalar_one_or_none()
    if not aff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Affiliate profile not found")

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


# ── Referrals ──────────────────────────────────────────────────────

@router.get("/referrals", response_model=list[AffiliateReferralResponse])
async def list_my_referrals(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's referrals."""
    result = await db.execute(
        select(Affiliate).where(Affiliate.client_id == current_user.id)
    )
    aff = result.scalar_one_or_none()
    if not aff:
        return []

    ref_result = await db.execute(
        select(AffiliateReferral)
        .where(AffiliateReferral.affiliate_id == aff.id)
        .order_by(AffiliateReferral.created_at.desc())
    )
    refs = ref_result.scalars().all()

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


# ── Commissions ────────────────────────────────────────────────────

@router.get("/commissions", response_model=list[AffiliateCommissionResponse])
async def list_my_commissions(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's commissions."""
    result = await db.execute(
        select(Affiliate).where(Affiliate.client_id == current_user.id)
    )
    aff = result.scalar_one_or_none()
    if not aff:
        return []

    comm_result = await db.execute(
        select(AffiliateCommission)
        .where(AffiliateCommission.affiliate_id == aff.id)
        .order_by(AffiliateCommission.created_at.desc())
    )
    comms = comm_result.scalars().all()

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

@router.post("/payouts", status_code=status.HTTP_201_CREATED)
async def request_payout(
    data: AffiliatePayoutRequest,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Request a payout."""
    result = await db.execute(
        select(Affiliate).where(Affiliate.client_id == current_user.id)
    )
    aff = result.scalar_one_or_none()
    if not aff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Affiliate profile not found")

    if aff.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Affiliate account is not active")

    if data.amount < aff.min_payout:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Minimum payout is RM{aff.min_payout:.2f}",
        )

    if data.amount > aff.pending_earnings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance. You have RM{aff.pending_earnings:.2f} available",
        )

    payout = AffiliatePayout(
        affiliate_id=aff.id,
        amount=data.amount,
        method=data.method,
        account_details=data.account_details,
        status="pending",
    )
    db.add(payout)
    await db.commit()
    await db.refresh(payout)

    return {
        "message": "Payout request submitted",
        "id": payout.id,
        "amount": payout.amount,
        "status": payout.status,
    }


@router.get("/payouts", response_model=list[AffiliatePayoutResponse])
async def list_my_payouts(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's payout requests."""
    result = await db.execute(
        select(Affiliate).where(Affiliate.client_id == current_user.id)
    )
    aff = result.scalar_one_or_none()
    if not aff:
        return []

    payout_result = await db.execute(
        select(AffiliatePayout)
        .where(AffiliatePayout.affiliate_id == aff.id)
        .order_by(AffiliatePayout.created_at.desc())
    )
    payouts = payout_result.scalars().all()

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


# ── AI Copywriting Generator ───────────────────────────────────────

@router.post("/copywriting", response_model=AffiliateCopyResponse)
async def generate_copy(
    data: AffiliateCopyRequest,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Auto-generate affiliate marketing copy using AI."""
    # Get affiliate profile + user info
    aff_result = await db.execute(
        select(Affiliate).where(Affiliate.client_id == current_user.id)
    )
    aff = aff_result.scalar_one_or_none()
    if not aff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Register as affiliate first")

    referral_link = f"https://staffbot.my/ref/{aff.referral_code}"
    user_name = current_user.name or "StaffBot Affiliate"

    # Templates per platform
    templates = {
        "whatsapp": {
            "professional": {
                "body": (
                    f"*Assalamualaikum tuan/puan,* 👋\n\n"
                    f"Saya nak kongsikan satu perkhidmatan yang saya sendiri guna — *StaffBot.my*.\n\n"
                    f"StaffBot.my adalah *Digital Employee as a Service* untuk SME. Bukan chatbot biasa, "
                    f"tapi AI Agent yang boleh:\n"
                    f"✅ Auto jawab WhatsApp ikut jadual\n"
                    f"✅ Integrasi Google Drive, Email, API\n"
                    f"✅ Execute tasks 24/7 tanpa gaji\n"
                    f"✅ Dashboard web + Telegram\n\n"
                    f"Cuba percuma 7 hari — tak perlu kad kredit.\n"
                    f"👉 {referral_link}\n\n"
                    f"*Jangan lepaskan peluang ni. Staff AI murah dari staff part time, hasil kerja macam staff 10 tahun.* 🚀"
                ),
            },
            "friendly": {
                "body": (
                    f"Hai! 👋\n\n"
                    f"Nak tahu pasal *StaffBot.my*? Best ni!\n\n"
                    f"StaffBot.my ni macam ada staff sendiri yang kerja 24/7 — "
                    f"boleh jawab Whatsapp, urus Google Drive, execute tasks ikut arahan, "
                    f"semua automatik. Gaji dia pulak murah sangat.\n\n"
                    f"Dah ramai SME guna, cuba free 7 hari dulu.\n"
                    f"👉 {referral_link}\n\n"
                    f"Jangan malu tanya apa-apa kat saya ya! 😊"
                ),
            },
            "urgent": {
                "body": (
                    f"🔥 *PROMO TERHAD — StaffBot.my* 🔥\n\n"
                    f"Jangan biar staff manual buang masa dengan tugas berulang.\n\n"
                    f"*StaffBot.my* — AI Agent untuk SME:\n"
                    f"⚡ Auto reply WhatsApp\n"
                    f"⚡ Integrasi GDrive, Email, API\n"
                    f"⚡ 24/7 tanpa henti\n\n"
                    f"✅ *Cuba PERCUMA 7 hari sekarang*\n"
                    f"👉 {referral_link}\n\n"
                    f"*Promosi ni tak lama. Register sekarang sebelum terlambat!* ⏰"
                ),
            },
        },
        "telegram": {
            "professional": {
                "body": (
                    f"📢 *Perkenalan: StaffBot.my*\n\n"
                    f"Saya nak recommend satu service yang saya guna — StaffBot.my.\n\n"
                    f"StaffBot.my adalah *Digital Employee as a Service* untuk SME Malaysia.\n\n"
                    f"✨ *Apa dia boleh buat?*\n"
                    f"• Auto jawab WhatsApp ikut jadual & filter\n"
                    f"• Integrasi Google Drive, Email, API\n"
                    f"• Execute tasks ikut arahan\n"
                    f"• 24/7 operation — tak cuti, tak MC\n\n"
                    f"💰 *Harga*: murah dari staff part time\n"
                    f"🎁 *Cuba percuma 7 hari*\n\n"
                    f"👉 {referral_link}\n\n"
                    f"#StaffBot #AI #DigitalEmployee #SME #Malaysia"
                ),
            },
        },
        "email": {
            "professional": {
                "subject": "Perkenalan StaffBot.my — Digital Employee untuk SME",
                "body": (
                    f"Assalamualaikum tuan/puan,\n\n"
                    f"Saya nak kongsikan StaffBot.my — Digital Employee as a Service yang saya sendiri guna.\n\n"
                    f"StaffBot.my bukan chatbot biasa. Ia adalah AI Agent yang dedicated untuk perniagaan anda:\n\n"
                    f"• Auto jawab WhatsApp — ikut jadual, filter customer/group\n"
                    f"• Integrasi Google Drive, Email, API\n"
                    f"• Execute tasks 24/7 tanpa gaji\n"
                    f"• Web Dashboard + Telegram untuk monitor\n\n"
                    f"Hasil kerja macam staff 10 tahun, harga murah dari staff part time.\n\n"
                    f"Cuba percuma 7 hari — tak perlu kad kredit.\n"
                    f"{referral_link}\n\n"
                    f"Jangan lepaskan peluang ni.\n\n"
                    f"Terima kasih,\n{user_name}"
                ),
            },
        },
        "social": {
            "professional": {
                "body": (
                    f"🚀 *Ada staff yang kerja 24/7 tanpa gaji?* 🚀\n\n"
                    f"Kenalkan — *StaffBot.my* — Digital Employee untuk SME Malaysia.\n\n"
                    f"✅ Auto jawab WhatsApp\n"
                    f"✅ Integrasi GDrive, Email, API\n"
                    f"✅ Execute tasks ikut arahan\n"
                    f"✅ 24/7 operation\n\n"
                    f"Murah dari staff part time, hasil kerja macam staff 10 tahun!\n\n"
                    f"🎁 *Cuba PERCUMA 7 hari*\n"
                    f"👉 {referral_link}\n\n"
                    f"#StaffBot #AI #DigitalEmployee #SME #Malaysia #Automasi"
                ),
            },
        },
    }

    platform_data = templates.get(data.platform, templates["whatsapp"])
    tone_data = platform_data.get(data.tone, platform_data["professional"])

    body = tone_data.get("body", "")
    subject = tone_data.get("subject", None)

    if data.extra_notes:
        body += f"\n\n---\n*Nota tambahan*: {data.extra_notes}"

    return AffiliateCopyResponse(
        subject=subject,
        body=body,
        platform=data.platform,
    )


# ── Leaderboard ────────────────────────────────────────────────────

@router.get("/leaderboard")
async def get_public_leaderboard(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Get affiliate leaderboard (public — names are masked)."""
    result = await db.execute(
        select(Affiliate)
        .where(Affiliate.total_earnings > 0, Affiliate.status == "active")
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

        name = client_data.name if client_data else "***"
        entries.append({
            "rank": rank,
            "name_masked": mask_name(name),
            "total_earnings": aff.total_earnings,
            "total_referrals": aff.total_referrals,
            "commission_rate": aff.commission_rate,
        })

    return {"entries": entries, "total_affiliates": len(affiliates)}


# ── Click Tracking ─────────────────────────────────────────────────

@router.post("/track-click")
async def track_click(
    referral_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Track a referral link click (called by landing page)."""
    result = await db.execute(
        select(Affiliate).where(Affiliate.referral_code == referral_code)
    )
    aff = result.scalar_one_or_none()
    if not aff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid referral code")

    click = AffiliateClick(
        affiliate_id=aff.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        referrer_url=request.headers.get("referer"),
        landing_page=f"/ref/{referral_code}",
    )
    db.add(click)
    aff.total_clicks = (aff.total_clicks or 0) + 1
    await db.commit()

    return {"message": "Click tracked", "referral_code": referral_code}


# ── Referral Conversion (called on user signup with ref code) ──────

@router.post("/convert")
async def convert_referral(
    referral_code: str,
    new_client_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Mark a referral as converted (called after successful signup)."""
    result = await db.execute(
        select(Affiliate).where(Affiliate.referral_code == referral_code)
    )
    aff = result.scalar_one_or_none()
    if not aff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid referral code")

    # Get new client details
    client_result = await db.execute(select(Client).where(Client.id == new_client_id))
    new_client = client_result.scalar_one_or_none()
    if not new_client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    # Create referral record
    referral = AffiliateReferral(
        affiliate_id=aff.id,
        referred_client_id=new_client.id,
        referred_email=new_client.email,
        referred_name=new_client.name,
        status="active",
        ip_address=None,
    )
    db.add(referral)
    aff.total_referrals = (aff.total_referrals or 0) + 1

    # Mark click as converted if exists
    click_result = await db.execute(
        select(AffiliateClick)
        .where(
            AffiliateClick.affiliate_id == aff.id,
            AffiliateClick.converted == False,
        )
        .order_by(AffiliateClick.created_at.desc())
        .limit(1)
    )
    click = click_result.scalar_one_or_none()
    if click:
        click.converted = True

    await db.commit()
    return {"message": "Referral converted", "referral_id": referral.id}
