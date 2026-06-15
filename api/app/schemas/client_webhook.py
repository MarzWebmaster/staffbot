"""Client webhook schemas for request/response validation."""
from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl, field_validator
from typing import Optional


class ClientWebhookCreate(BaseModel):
    """Create a new webhook configuration."""
    name: str = Field(..., min_length=1, max_length=100)
    base_url: str = Field(..., min_length=1, max_length=500)
    auth_type: str = Field(default="none", pattern="^(none|bearer|api_key|basic)$")
    auth_header: Optional[str] = Field(default=None, max_length=50)
    auth_value: Optional[str] = Field(default=None)  # raw token — encrypted before save
    default_headers: Optional[dict] = Field(default={})
    is_active: bool = Field(default=True)
    rate_limit: int = Field(default=10, ge=1, le=100)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v


class ClientWebhookUpdate(BaseModel):
    """Update an existing webhook configuration."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    base_url: Optional[str] = Field(default=None, min_length=1, max_length=500)
    auth_type: Optional[str] = Field(default=None, pattern="^(none|bearer|api_key|basic)$")
    auth_header: Optional[str] = Field(default=None, max_length=50)
    auth_value: Optional[str] = Field(default=None)  # raw token — encrypted before save
    default_headers: Optional[dict] = None
    is_active: Optional[bool] = None
    rate_limit: Optional[int] = Field(default=None, ge=1, le=100)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v


class ClientWebhookResponse(BaseModel):
    """Public response — auth_value is MASKED."""
    id: int
    client_id: int
    name: str
    base_url: str
    auth_type: str
    auth_header: Optional[str]
    auth_value: Optional[str]  # masked: "sk-1234..." or None
    default_headers: dict
    is_active: bool
    rate_limit: int
    max_timeout: int
    created_at: datetime

    model_config = {"from_attributes": True}
