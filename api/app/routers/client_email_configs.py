"""
Client email configs CRUD router.

Endpoints:
- GET    / — List all email configs for client
- POST   / — Create new email config
- DELETE /{id} — Delete email config
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client import Client
from app.models.client_email_config import ClientEmailConfig
from app.schemas.client_email_config import (
    ClientEmailConfigCreate, ClientEmailConfigUpdate, ClientEmailConfigResponse,
)
from app.middleware.auth import get_current_client
from app.utils.encryption import encrypt_value, decrypt_value, mask_key

router = APIRouter()


def _mask_config(cfg: ClientEmailConfig) -> ClientEmailConfigResponse:
    """Mask smtp_pass before returning to client."""
    masked = None
    if cfg.smtp_pass:
        try:
            masked = mask_key(decrypt_value(cfg.smtp_pass))
        except Exception:
            masked = "***"
    return ClientEmailConfigResponse(
        id=cfg.id,
        client_id=cfg.client_id,
        smtp_host=cfg.smtp_host,
        smtp_port=cfg.smtp_port,
        smtp_user=cfg.smtp_user,
        smtp_pass=masked,
        use_tls=cfg.use_tls,
        from_email=cfg.from_email,
        from_name=cfg.from_name,
        is_active=cfg.is_active,
        created_at=cfg.created_at,
    )


@router.get("/", response_model=list[ClientEmailConfigResponse])
async def list_email_configs(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """List all email/SMTP configs for the current client."""
    result = await db.execute(
        select(ClientEmailConfig)
        .where(ClientEmailConfig.client_id == current_user.id)
        .order_by(ClientEmailConfig.created_at.desc())
    )
    configs = result.scalars().all()
    return [_mask_config(cfg) for cfg in configs]


@router.post("/", response_model=ClientEmailConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_email_config(
    data: ClientEmailConfigCreate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Create a new SMTP email config.

    Example:
    {
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "you@gmail.com",
        "smtp_pass": "your-app-password"
    }
    """
    encrypted_pass = encrypt_value(data.smtp_pass)

    cfg = ClientEmailConfig(
        client_id=current_user.id,
        smtp_host=data.smtp_host,
        smtp_port=data.smtp_port,
        smtp_user=data.smtp_user,
        smtp_pass=encrypted_pass,
        use_tls=data.use_tls,
        from_email=data.from_email or data.smtp_user,
        from_name=data.from_name,
        is_active=data.is_active,
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return _mask_config(cfg)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email_config(
    config_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Delete an email config."""
    result = await db.execute(
        select(ClientEmailConfig).where(
            ClientEmailConfig.id == config_id,
            ClientEmailConfig.client_id == current_user.id,
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="Email config not found")

    await db.delete(cfg)
    await db.commit()
    return None
