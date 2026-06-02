"""Internal router — for Gateway communication (same server).

Endpoints here are authenticated via x-api-key (STAFFBOT_GATEWAY_API_KEY),
NOT via user JWT tokens.
"""
import os
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.models.llm_provider import LlmProvider
from app.models.subscription import Subscription
from app.utils.encryption import decrypt_value

router = APIRouter()

GATEWAY_API_KEY = os.environ.get("STAFFBOT_SERVER_B_API_KEY", "")

async def verify_internal(x_api_key: str = Header(None)):
    """Verify internal API key for Gateway communication."""
    if not GATEWAY_API_KEY:
        raise HTTPException(status_code=500, detail="Internal auth not configured")
    if not x_api_key or x_api_key != GATEWAY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid internal API key")
    return True


class ProviderResolveRequest(BaseModel):
    provider_name: str
    client_id: int


class ProviderResolveResponse(BaseModel):
    name: str
    display_name: str
    base_url: str
    api_key: str
    default_model: str
    models: list = []


@router.post("/provider/resolve")
async def resolve_provider(
    data: ProviderResolveRequest,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(verify_internal),
):
    """Resolve a provider config with decrypted API key.
    
    Called by Gateway to get managed API keys
    for making LLM calls on behalf of clients.
    """
    result = await db.execute(
        select(LlmProvider).where(
            LlmProvider.name == data.provider_name,
            LlmProvider.is_active == True,
        )
    )
    provider = result.scalar_one_or_none()
    
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{data.provider_name}' not found or inactive")
    
    if not provider.api_key_encrypted:
        raise HTTPException(status_code=400, detail=f"Provider '{data.provider_name}' has no API key configured")
    
    # Decrypt the API key
    try:
        api_key = decrypt_value(provider.api_key_encrypted)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt API key: {str(e)}")
    
    return {
        "name": provider.name,
        "display_name": provider.display_name,
        "base_url": provider.base_url,
        "api_key": api_key,
        "default_model": provider.default_model or "deepseek-v4-flash",
        "models": provider.models or [],
    }


@router.get("/provider/list")
async def list_providers(
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(verify_internal),
):
    """List all active providers (without API keys)."""
    result = await db.execute(
        select(LlmProvider).where(LlmProvider.is_active == True)
    )
    providers = result.scalars().all()
    
    return [
        {
            "name": p.name,
            "display_name": p.display_name,
            "base_url": p.base_url,
            "default_model": p.default_model,
            "models": p.models or [],
            "api_key_configured": bool(p.api_key_encrypted),
        }
        for p in providers
    ]
