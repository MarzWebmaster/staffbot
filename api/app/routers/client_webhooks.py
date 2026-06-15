"""
Client webhooks CRUD router.

Endpoints:
- GET    / — List all webhooks for client
- POST   / — Create new webhook
- GET    /{id} — Get single webhook
- PUT    /{id} — Update webhook
- DELETE /{id} — Delete webhook
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client import Client
from app.models.client_webhook import ClientWebhook
from app.schemas.client_webhook import (
    ClientWebhookCreate, ClientWebhookUpdate, ClientWebhookResponse,
)
from app.middleware.auth import get_current_client
from app.utils.encryption import encrypt_value, decrypt_value, mask_key

router = APIRouter()


def _mask_webhook(wh: ClientWebhook) -> ClientWebhookResponse:
    """Mask auth_value before returning to client."""
    return ClientWebhookResponse(
        id=wh.id,
        client_id=wh.client_id,
        name=wh.name,
        base_url=wh.base_url,
        auth_type=wh.auth_type,
        auth_header=wh.auth_header,
        auth_value=mask_key(decrypt_value(wh.auth_value)) if wh.auth_value else None,
        default_headers=wh.default_headers or {},
        is_active=wh.is_active,
        rate_limit=wh.rate_limit,
        max_timeout=wh.max_timeout,
        created_at=wh.created_at,
    )


@router.get("/", response_model=list[ClientWebhookResponse])
async def list_webhooks(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """List all webhook configurations for the current client."""
    result = await db.execute(
        select(ClientWebhook)
        .where(ClientWebhook.client_id == current_user.id)
        .order_by(ClientWebhook.created_at.desc())
    )
    webhooks = result.scalars().all()
    return [_mask_webhook(wh) for wh in webhooks]


@router.post("/", response_model=ClientWebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    data: ClientWebhookCreate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Create a new webhook configuration."""
    # Encrypt auth_value if provided
    encrypted_auth = encrypt_value(data.auth_value) if data.auth_value else None

    webhook = ClientWebhook(
        client_id=current_user.id,
        name=data.name,
        base_url=data.base_url,
        auth_type=data.auth_type,
        auth_header=data.auth_header,
        auth_value=encrypted_auth,
        default_headers=data.default_headers or {},
        is_active=data.is_active,
        rate_limit=data.rate_limit,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    return _mask_webhook(webhook)


@router.get("/{webhook_id}", response_model=ClientWebhookResponse)
async def get_webhook(
    webhook_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get a single webhook configuration."""
    result = await db.execute(
        select(ClientWebhook).where(
            ClientWebhook.id == webhook_id,
            ClientWebhook.client_id == current_user.id,
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return _mask_webhook(webhook)


@router.put("/{webhook_id}", response_model=ClientWebhookResponse)
async def update_webhook(
    webhook_id: int,
    data: ClientWebhookUpdate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Update a webhook configuration."""
    result = await db.execute(
        select(ClientWebhook).where(
            ClientWebhook.id == webhook_id,
            ClientWebhook.client_id == current_user.id,
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Update fields if provided
    update_data = data.model_dump(exclude_unset=True)
    if "auth_value" in update_data:
        update_data["auth_value"] = encrypt_value(update_data["auth_value"]) if update_data["auth_value"] else None

    for field, value in update_data.items():
        setattr(webhook, field, value)

    await db.commit()
    await db.refresh(webhook)
    return _mask_webhook(webhook)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook configuration."""
    result = await db.execute(
        select(ClientWebhook).where(
            ClientWebhook.id == webhook_id,
            ClientWebhook.client_id == current_user.id,
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    await db.delete(webhook)
    await db.commit()
    return None
