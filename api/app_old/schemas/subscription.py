from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, Any


class SubscriptionBase(BaseModel):
    package: str = "basic"
    managed_token_quota: float = 0.0


class SubscriptionCreate(SubscriptionBase):
    client_id: int
    stripe_session_id: str


class SubscriptionResponse(BaseModel):
    id: int
    client_id: int
    package: str
    status: str
    managed_token_quota: float
    managed_token_used: float
    provider_token_usage: Optional[dict] = None
    start_date: datetime
    end_date: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenUsageUpdate(BaseModel):
    managed_token_used: float = Field(..., ge=0)
