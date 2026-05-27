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
    cpu_limit: float = 1.0
    memory_limit_mb: int = 512
    storage_limit_gb: int = 10
    sort_order: int = 0


class PackageUpdate(BaseModel):
    display_name: Optional[str] = None
    price_monthly: Optional[float] = None
    price_yearly: Optional[float] = None
    description: Optional[str] = None
    features: Optional[list] = None
    bot_limit: Optional[int] = None
    managed_tokens: Optional[float] = None
    cpu_limit: Optional[float] = None
    memory_limit_mb: Optional[int] = None
    storage_limit_gb: Optional[int] = None
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

class TokenUsageData(BaseModel):
    labels: list[str]
    values: list[int]
    active_clients: int = 0
    avg_per_call: int = 0

class UsageByClient(BaseModel):
    items: list[dict]

class ActivityItem(BaseModel):
    items: list[dict]

class StaffItem(BaseModel):
    items: list[dict]