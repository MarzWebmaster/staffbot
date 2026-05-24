"""
Clients router.

Endpoints:
- GET / - List all clients (admin only)
- GET /{id} - Get client details
- PUT /{id} - Update client profile
- POST /setup - Complete onboarding wizard (API key + Telegram token)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.models.client import Client
from app.models.api_key import ApiKey
from app.schemas.client import (
    ClientResponse, ClientUpdate, ClientListResponse, SetupComplete,
)
from app.schemas.api_key import ApiKeyResponse
from app.middleware.auth import get_current_client, get_current_admin
from app.utils.encryption import encrypt_value, mask_key

router = APIRouter()


@router.get("/", response_model=ClientListResponse)
async def list_clients(
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    package: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all clients (admin only)."""
    query = select(Client)

    if search:
        query = query.where(
            Client.name.ilike(f"%{search}%")
            | Client.email.ilike(f"%{search}%")
            | Client.company.ilike(f"%{search}%")
        )
    if status_filter:
        query = query.where(Client.status == status_filter)
    if package:
        query = query.where(Client.package == package)

    query = query.order_by(Client.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    clients = result.scalars().all()

    # Get total count
    count_query = select(Client)
    if search:
        count_query = count_query.where(
            Client.name.ilike(f"%{search}%")
            | Client.email.ilike(f"%{search}%")
        )
    if status_filter:
        count_query = count_query.where(Client.status == status_filter)
    count_result = await db.execute(count_query)
    total = len(count_result.scalars().all())

    return ClientListResponse(items=clients, total=total)


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get client details."""
    # Customers can only access their own profile
    if current_user.id != client_id and current_user.email != "admin@staffbot.my":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return client


@router.put("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: int,
    data: ClientUpdate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Update client profile."""
    if current_user.id != client_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    update_data = data.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(client, key, value)

    await db.commit()
    await db.refresh(client)
    return client


@router.post("/setup")
async def complete_setup(
    data: SetupComplete,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Complete onboarding setup — save API key and/or Telegram token."""
    results = {}

    # Save API key if provided
    if data.api_key:
        encrypted = encrypt_value(data.api_key)
        api_key = ApiKey(
            client_id=current_user.id,
            provider="openrouter",
            key_encrypted=encrypted,
            key_prefix=mask_key(data.api_key),
            is_active=True,
            is_managed=False,
        )
        db.add(api_key)
        results["api_key"] = "saved"

    # Save encrypted Telegram token if provided
    if data.telegram_token:
        current_user.telegram_token_encrypted = encrypt_value(data.telegram_token)
        results["telegram_token"] = "saved"

    # Update client status to active if pending
    if current_user.status == "pending":
        current_user.status = "active"
        results["status"] = "activated"

    await db.commit()
    return {
        "message": "Setup completed successfully",
        "data": results,
    }


@router.get("/{client_id}/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    client_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """List API keys for a client."""
    if current_user.id != client_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(
        select(ApiKey).where(ApiKey.client_id == client_id)
    )
    keys = result.scalars().all()
    return keys
