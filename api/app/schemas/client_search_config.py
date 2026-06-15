"""Client search config schemas for request/response validation."""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional

VALID_PROVIDERS = {"brave", "google", "serpapi", "duckduckgo"}


class ClientSearchConfigCreate(BaseModel):
    """Create a new search provider config."""
    provider: str = Field(..., description="brave, google, serpapi, or duckduckgo")
    api_key: Optional[str] = Field(default=None, description="Raw API key — encrypted before save")
    base_url: Optional[str] = Field(default=None, max_length=500)
    is_active: bool = Field(default=True)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in VALID_PROVIDERS:
            raise ValueError(f"provider must be one of: {', '.join(sorted(VALID_PROVIDERS))}")
        return v


class ClientSearchConfigUpdate(BaseModel):
    """Update an existing search config."""
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.lower().strip()
        if v not in VALID_PROVIDERS:
            raise ValueError(f"provider must be one of: {', '.join(sorted(VALID_PROVIDERS))}")
        return v


class ClientSearchConfigResponse(BaseModel):
    """Public response — api_key is MASKED."""
    id: int
    client_id: int
    provider: str
    api_key: Optional[str]  # masked: "BSA-12**...**3f" or None
    base_url: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
