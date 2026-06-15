"""Client email config schemas for request/response validation."""
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Optional


class ClientEmailConfigCreate(BaseModel):
    """Create a new SMTP email config."""
    smtp_host: str = Field(..., min_length=1, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = Field(..., min_length=1, max_length=255)
    smtp_pass: str = Field(..., min_length=1, description="SMTP password — encrypted before save")
    use_tls: bool = Field(default=True)
    from_email: Optional[EmailStr] = None
    from_name: Optional[str] = Field(default=None, max_length=100)
    is_active: bool = Field(default=True)

    @field_validator("smtp_host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or " " in v:
            raise ValueError("Invalid SMTP host")
        return v


class ClientEmailConfigUpdate(BaseModel):
    """Update an existing SMTP config."""
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    use_tls: Optional[bool] = None
    from_email: Optional[EmailStr] = None
    from_name: Optional[str] = None
    is_active: Optional[bool] = None


class ClientEmailConfigResponse(BaseModel):
    """Public response — smtp_pass is MASKED."""
    id: int
    client_id: int
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: Optional[str]  # masked: "abc***xyz" or None
    use_tls: bool
    from_email: Optional[str]
    from_name: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
