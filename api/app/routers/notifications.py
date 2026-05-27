"""
Notifications router.

Endpoints:
- GET /channels - List notification channels
- POST /channels - Add notification channel
- PUT /channels/{id} - Update channel
- DELETE /channels/{id} - Remove channel
- GET /log - View notification history
- POST /test - Send test notification
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client import Client
from app.models.notification import NotificationChannel, NotificationLog
from app.schemas.notification import (
    NotificationChannelCreate, NotificationChannelResponse,
    NotificationLogResponse, NotificationTest, NotificationTestResponse,
)
from app.middleware.auth import get_current_client
from app.services.notification_service import NotificationService

router = APIRouter()


@router.get("/channels", response_model=list[NotificationChannelResponse])
async def list_channels(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """List notification channels for the client."""
    result = await db.execute(
        select(NotificationChannel).where(NotificationChannel.client_id == current_user.id)
    )
    return result.scalars().all()


@router.post("/channels", response_model=NotificationChannelResponse, status_code=status.HTTP_201_CREATED)
async def add_channel(
    data: NotificationChannelCreate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Add a new notification channel."""
    # Check channel type
    if data.channel not in ("whatsapp", "email", "sms", "in-app"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid channel. Must be: whatsapp, email, sms, or in-app",
        )

    channel = NotificationChannel(
        client_id=current_user.id,
        channel=data.channel,
        value=data.value,
        is_active=True,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.put("/channels/{channel_id}", response_model=NotificationChannelResponse)
async def update_channel(
    channel_id: int,
    data: NotificationChannelCreate,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Update a notification channel."""
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.client_id == current_user.id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    channel.channel = data.channel
    channel.value = data.value
    await db.commit()
    await db.refresh(channel)
    return channel


@router.delete("/channels/{channel_id}")
async def delete_channel(
    channel_id: int,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Remove a notification channel."""
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.client_id == current_user.id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    await db.delete(channel)
    await db.commit()
    return {"message": "Channel removed successfully"}


@router.get("/log", response_model=list[NotificationLogResponse])
async def get_notification_log(
    limit: int = 50,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """View recent notification history."""
    result = await db.execute(
        select(NotificationLog)
        .where(NotificationLog.client_id == current_user.id)
        .order_by(NotificationLog.sent_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.post("/test", response_model=NotificationTestResponse)
async def send_test_notification(
    data: NotificationTest,
    current_user: Client = Depends(get_current_client),
):
    """Send a test notification."""
    channel = data.channel
    service = NotificationService()

    if channel == "whatsapp":
        result = await service.send_whatsapp(data.value, data.message)
    elif channel == "email":
        result = await service.send_email(data.value, "Test Notification — StaffBot.my", data.message)
    elif channel == "sms":
        result = await service.send_sms(data.value, data.message[:160])
    else:
        return NotificationTestResponse(success=False, message=f"Unsupported channel: {channel}")

    if result.get("success"):
        return NotificationTestResponse(success=True, message="Test notification sent successfully")
    else:
        return NotificationTestResponse(
            success=False,
            message=f"Failed: {result.get('error', 'Unknown error')}",
        )
