from pydantic import BaseModel, EmailStr, Field
from typing import Literal, Optional, List


class AdminLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class DashboardStats(BaseModel):
    total_users: int
    active_users: int
    total_revenue: float
    active_containers: int
    active_clients: int = 0
    pending_deployments: int
    pending_payments: int = 0
    monthly_revenue: List[dict]


class SystemHealth(BaseModel):
    api_status: str
    db_status: str
    gateway_status: str
    uptime: float


class PackageCreate(BaseModel):
    name: str
    display_name: str
    price_monthly: float = 0
    price_yearly: Optional[float] = None
    description: str = ""
    features: list = []
    bot_limit: int = 1
    sub_ejen_limit: int = 0
    managed_tokens: float = 0
    cpu_limit: float = 1.0
    memory_limit_mb: int = 512
    storage_limit_gb: int = 10
    skill_category_ids: list = []
    tool_category_ids: list = []
    allowed_skill_categories: list = []
    allowed_tool_categories: list = []
    enabled_skills: list = []
    enabled_tools: list = []
    sort_order: int = 0
    trial_days: int = 0
    is_public: bool = True
    badge: Optional[str] = None
    memory_retention_days: int = 7
    memory_item_limit: int = 50
    knowledge_item_limit: int = 50
    allowed_models: list[str] = []
    channel_limits: dict = {}
    byok_allowed: bool = True
    console_mode: Literal["none", "hermes", "shell"] = "none"
    agent_terminal: bool = False
    catalog_tier: Literal["basic", "all"] = "basic"
    custom_code_allowed: bool = False
    idle_sleep_minutes: int = Field(30, ge=0)  # 0 = always on
    backup_retention_days: int = Field(7, ge=0)
    upgrade_window: bool = False
    support_level: Literal["none", "email", "email_whatsapp", "priority"] = "email"


class PackageUpdate(BaseModel):
    display_name: Optional[str] = None
    price_monthly: Optional[float] = None
    price_yearly: Optional[float] = None
    description: Optional[str] = None
    features: Optional[list] = None
    bot_limit: Optional[int] = None
    sub_ejen_limit: Optional[int] = None
    managed_tokens: Optional[float] = None
    cpu_limit: Optional[float] = None
    memory_limit_mb: Optional[int] = None
    storage_limit_gb: Optional[int] = None
    skill_category_ids: Optional[list] = None
    tool_category_ids: Optional[list] = None
    allowed_skill_categories: Optional[list] = None
    allowed_tool_categories: Optional[list] = None
    enabled_skills: Optional[list] = None
    enabled_tools: Optional[list] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    trial_days: Optional[int] = None
    is_public: Optional[bool] = None
    badge: Optional[str] = None
    memory_retention_days: Optional[int] = None
    memory_item_limit: Optional[int] = None
    knowledge_item_limit: Optional[int] = None
    allowed_models: Optional[list[str]] = None
    channel_limits: Optional[dict] = None
    byok_allowed: Optional[bool] = None
    console_mode: Optional[Literal["none", "hermes", "shell"]] = None
    agent_terminal: Optional[bool] = None
    catalog_tier: Optional[Literal["basic", "all"]] = None
    custom_code_allowed: Optional[bool] = None
    idle_sleep_minutes: Optional[int] = Field(None, ge=0)  # 0 = always on
    backup_retention_days: Optional[int] = Field(None, ge=0)
    upgrade_window: Optional[bool] = None
    support_level: Optional[Literal["none", "email", "email_whatsapp", "priority"]] = None


class SettingUpdate(BaseModel):
    key: str
    value: str
    encrypted: bool = False


class UserCreateAdmin(BaseModel):
    """Admin-created user — no password complexity requirement."""
    name: str
    email: EmailStr
    password: str = Field(..., min_length=6)
    company: Optional[str] = None
    phone: Optional[str] = None
    package: str = "basic"
    status: str = "active"


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
