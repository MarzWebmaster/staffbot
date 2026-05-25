from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List


class AdminLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class DashboardStats(BaseModel):
    total_users: int
    active_users: int
    total_revenue: float
    active_containers: int
    pending_deployments: int
    monthly_revenue: List[dict]


class SystemHealth(BaseModel):
    api_status: str
    db_status: str
    server_b_status: str
    uptime: float


class PackageCreate(BaseModel):
    name: str
    display_name: str
    price_monthly: float = 0
    price_yearly: Optional[float] = None
    description: str = ""
    features: list = []
    bot_limit: int = 1
    managed_tokens: float = 0
    sort_order: int = 0


class PackageUpdate(BaseModel):
    display_name: Optional[str] = None
    price_monthly: Optional[float] = None
    price_yearly: Optional[float] = None
    description: Optional[str] = None
    features: Optional[list] = None
    bot_limit: Optional[int] = None
    managed_tokens: Optional[float] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class SettingUpdate(BaseModel):
    key: str
    value: str
    encrypted: bool = False


class UserUpdateAdmin(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    package: Optional[str] = None
    status: Optional[str] = None


# ── Token Usage Analytics ──────────────────────────────────────────


class TokenUsagePoint(BaseModel):
    """Single data point on a token usage chart."""
    date: str
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    request_count: int = 0


class TokenUsageSummary(BaseModel):
    """Aggregated token usage stats."""
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    total_requests: int = 0
    avg_tokens_per_request: float = 0.0
    unique_models: int = 0
    unique_users: int = 0


class TokenUsageResponse(BaseModel):
    """Token usage analytics response."""
    summary: TokenUsageSummary
    timeseries: List[TokenUsagePoint]
    top_models: List[dict] = []
    top_users: List[dict] = []
