from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional


class ApiKeyCreate(BaseModel):
    provider: str = "openrouter"
    key: str = Field(..., min_length=5)


class ApiKeyTest(BaseModel):
    key: str
    provider: str = "openrouter"


class ApiKeyTestResponse(BaseModel):
    valid: bool
    message: str
    model_name: Optional[str] = None


class ApiKeyResponse(BaseModel):
    id: int
    client_id: int
    provider: str
    key_prefix: Optional[str] = None
    is_active: bool
    is_managed: bool
    created_at: datetime

    model_config = {"from_attributes": True}
