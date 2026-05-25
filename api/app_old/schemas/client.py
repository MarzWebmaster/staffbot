from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
import re


class ClientBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    company: Optional[str] = None
    phone: Optional[str] = None


class ClientCreate(ClientBase):
    password: str = Field(..., min_length=8)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=~`\[\];']", v):
            raise ValueError("Password must contain at least one special character")
        return v


class ClientLogin(BaseModel):
    email: EmailStr
    password: str


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    package: Optional[str] = None
    status: Optional[str] = None


class ClientResponse(ClientBase):
    id: int
    package: str
    status: str
    subdomain: Optional[str] = None
    container_port: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClientListResponse(BaseModel):
    items: list[ClientResponse]
    total: int


class SetupComplete(BaseModel):
    telegram_token: Optional[str] = None
    api_key: Optional[str] = None
