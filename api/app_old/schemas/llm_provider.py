from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List


class LlmProviderBase(BaseModel):
    name: str
    display_name: str
    base_url: str
    models: list = []
    default_model: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class LlmProviderCreate(LlmProviderBase):
    api_key: Optional[str] = None  # Will be encrypted


class LlmProviderUpdate(BaseModel):
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    models: Optional[list] = None
    default_model: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class LlmProviderResponse(LlmProviderBase):
    id: int
    api_key_configured: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PackageProviderAssign(BaseModel):
    provider_id: int
    token_quota: float = 0.0
    is_available: bool = True


class PackageProviderResponse(BaseModel):
    id: int
    package_id: int
    provider_id: int
    token_quota: float
    is_available: bool
    provider: Optional[LlmProviderResponse] = None

    model_config = {"from_attributes": True}


class ProviderUsageUpdate(BaseModel):
    provider_name: str
    tokens_used: float
