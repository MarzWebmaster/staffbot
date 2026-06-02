from pydantic import BaseModel
from typing import Optional


class SubdomainCreate(BaseModel):
    subdomain: str
    client_id: Optional[int] = None
    status: str = "available"
    notes: Optional[str] = None


class SubdomainUpdate(BaseModel):
    subdomain: Optional[str] = None
    client_id: Optional[int] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class SubdomainResponse(BaseModel):
    id: int
    subdomain: str
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    status: str
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
