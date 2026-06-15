"""
Client search configs CRUD router.

Endpoints:
- GET    / — List all search configs for client
- POST   / — Create new search config
- DELETE /{id} — Delete search config
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client import Client
from app.models.client_search_config import ClientSearchConfig
from app.schemas.client_search_config import (
    ClientSearchConfigCreate, ClientSearchConfigUpdate, ClientSearchConfigResponse,
)
from app.middleware.auth import get_current_client
from app.utils.encryption import encrypt_value, decrypt_value, mask_key

router = APIRouter()


def _mask_config(cfg: ClientSearchConfig) -> ClientSearchConfigResponse:
    """Mask api_key before returning to client."""
    masked = None
    if cfg.api_key:
        try:
            masked = mask_key(decrypt_value(cfg.api_key))
        except Exception:
            masked = "***"
    return ClientSearchConfigResponse(
        id=cfg.id,
        client_id=cfg.client_id,
        provider=cfg.provider,
        api_key=masked,
        base_url=cfg.base_url,
        is_active=cfg.is_active,
        created_at=cfg.created_at,
    )


@router.get("/", response_model=list[ClientSearchConfigResponse])
async def list_search_configs(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """List all search provider configs for the current client."""
    result = await db.execute(
        select(ClientSearchConfig)
        .where(ClientSearchConfig.client_id == current_user.id)
        .order_by(ClientSearchConfig.created_at.desc())
    )
    configs = result.scalars().all()
    return [_mask_config(cfg) for cfg in configs]


@router.post("/", response_model=ClientSearchConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_search_config(
    data: ClientSearchConfigCreate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Create a new search provider config.

    - provider: brave, google, serpapi, or duckduckgo
    - api_key: your API key (not needed for duckduckgo)
    """
    # Validate duckduckgo doesn't need api_key
    if data.provider != "duckduckgo" and not data.api_key:
        raise HTTPException(status_code=400, detail="api_key is required for this provider")

    # Encrypt api_key if provided
    encrypted_key = encrypt_value(data.api_key) if data.api_key else None

    cfg = ClientSearchConfig(
        client_id=current_user.id,
        provider=data.provider,
        api_key=encrypted_key,
        base_url=data.base_url,
        is_active=data.is_active,
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return _mask_config(cfg)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search_config(
    config_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Delete a search config."""
    result = await db.execute(
        select(ClientSearchConfig).where(
            ClientSearchConfig.id == config_id,
            ClientSearchConfig.client_id == current_user.id,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="Search config not found")

    await db.delete(cfg)
    await db.commit()
    return None
