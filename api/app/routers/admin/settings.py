"""
Admin settings router — system configuration.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client import Client
from app.models.setting import Setting
from app.schemas.admin import SettingUpdate
from app.middleware.auth import get_current_admin
from app.utils.encryption import encrypt_value, decrypt_value

router = APIRouter()


@router.get("/")
@router.get("")
async def get_all_settings(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get all system settings."""
    result = await db.execute(select(Setting))
    settings = result.scalars().all()
    return [
        {
            "key": s.key,
            "value": decrypt_value(s.value) if s.encrypted else s.value,
            "encrypted": s.encrypted,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in settings
    ]


@router.put("/")
@router.put("")
async def update_setting(
    data: SettingUpdate,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a system setting."""
    result = await db.execute(
        select(Setting).where(Setting.key == data.key)
    )
    setting = result.scalar_one_or_none()

    value = encrypt_value(data.value) if data.encrypted else data.value

    if setting:
        setting.value = value
        setting.encrypted = data.encrypted
    else:
        setting = Setting(
            key=data.key,
            value=value,
            encrypted=data.encrypted,
        )
        db.add(setting)

    await db.commit()
    return {"message": f"Setting '{data.key}' updated"}
