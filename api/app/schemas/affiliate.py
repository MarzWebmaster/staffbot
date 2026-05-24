from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List


# ── Affiliate Profile ──────────────────────────────────────────────

class AffiliateProfileResponse(BaseModel):
    id: int
    client_id: int
    referral_code: str
    referral_link: Optional[str] = None
    commission_rate: float
    total_earnings: float
    pending_earnings: float
    paid_earnings: float
    total_referrals: int
    total_clicks: int
    status: str
    is_auto_approve: bool
    min_payout: float
    created_at: datetime

    model_config = {"from_attributes": True}


class AffiliateUpdate(BaseModel):
    commission_rate: Optional[float] = None
    is_auto_approve: Optional[bool] = None
    min_payout: Optional[float] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class AffiliateAdminUpdate(AffiliateUpdate):
    total_earnings: Optional[float] = None
    pending_earnings: Optional[float] = None
    paid_earnings: Optional[float] = None


# ── Referrals ──────────────────────────────────────────────────────

class AffiliateReferralResponse(BaseModel):
    id: int
    referred_email: Optional[str] = None
    referred_name: Optional[str] = None
    status: str
    commission_earned: float
    package_signed: Optional[str] = None
    created_at: datetime
    converted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Commissions ────────────────────────────────────────────────────

class AffiliateCommissionResponse(BaseModel):
    id: int
    amount: float
    description: Optional[str] = None
    status: str
    created_at: datetime
    paid_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Payouts ────────────────────────────────────────────────────────

class AffiliatePayoutRequest(BaseModel):
    amount: float
    method: str = "bank_transfer"
    account_details: Optional[str] = None


class AffiliatePayoutResponse(BaseModel):
    id: int
    amount: float
    method: str
    account_details: Optional[str] = None
    status: str
    admin_notes: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AffiliatePayoutProcess(BaseModel):
    status: str  # processing / completed / rejected
    admin_notes: Optional[str] = None


# ── Leaderboard ────────────────────────────────────────────────────

class AffiliateLeaderboardEntry(BaseModel):
    rank: int
    name_masked: str          # "R***y" or "M*** Technology"
    total_earnings: float
    total_referrals: int
    commission_rate: float


class AffiliateLeaderboard(BaseModel):
    entries: List[AffiliateLeaderboardEntry]
    total_affiliates: int


# ── Click Tracking ─────────────────────────────────────────────────

class AffiliateClickResponse(BaseModel):
    id: int
    ip_address: Optional[str] = None
    referrer_url: Optional[str] = None
    converted: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Copywriting ────────────────────────────────────────────────────

class AffiliateCopyRequest(BaseModel):
    platform: str = "whatsapp"           # whatsapp / telegram / email / social
    target_audience: str = "SME"         # SME / enterprise / freelancer
    tone: str = "professional"           # professional / friendly / urgent
    extra_notes: Optional[str] = None


class AffiliateCopyResponse(BaseModel):
    subject: Optional[str] = None
    body: str
    platform: str


# ── Dashboard Summary ──────────────────────────────────────────────

class AffiliateDashboardResponse(BaseModel):
    profile: Optional[AffiliateProfileResponse] = None
    recent_referrals: List[AffiliateReferralResponse] = []
    recent_commissions: List[AffiliateCommissionResponse] = []
    recent_clicks: int = 0
    conversion_rate: float = 0.0
    leaderboard_rank: Optional[int] = None
    referrals_this_month: int = 0
    earnings_this_month: float = 0.0
