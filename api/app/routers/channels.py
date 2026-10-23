"""Channel router endpoints (docs/TARGET_ARCHITECTURE.md D15).

- POST /api/v1/channels/incoming/{whatsapp|telegram}/{client_id}
    called by the Baileys / Telegram managers (x-gateway-key). Returns at once;
    the reply is produced in the background and sent back through the manager.
- POST /api/v1/channels/web/chat
    the customer's own web chat (JWT). Streams the agent's answer (SSE).
"""
import hmac
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory
from app.models.hermes_instance import HermesInstance
from app.middleware.auth import get_current_client
from app.models.client import Client
from app.services import channel_router

router = APIRouter()
settings = get_settings()


@router.post("/incoming/{platform}/{client_id}")
async def incoming(platform: str, client_id: int, data: dict, background: BackgroundTasks,
                   x_gateway_key: Optional[str] = Header(None)):
    key = settings.CHANNEL_INCOMING_KEY
    if not key or not x_gateway_key or not hmac.compare_digest(x_gateway_key, key):
        raise HTTPException(status_code=401, detail="Invalid gateway key")
    if platform not in ("whatsapp", "telegram"):
        raise HTTPException(status_code=404, detail="Unknown platform")
    if not await _has_hermes(client_id):
        # Not migrated yet: hand the event to the legacy gateway unchanged, so
        # managers can point at this router before every customer has moved.
        return await _forward_legacy(platform, client_id, data, x_gateway_key)
    if data.get("type", "message") != "message":
        return {"ok": True, "ignored": data.get("type")}
    background.add_task(channel_router.handle_incoming, client_id, platform, data)
    return {"ok": True, "queued": True}


async def _has_hermes(client_id: int) -> bool:
    async with async_session_factory() as db:
        return (await db.execute(
            select(HermesInstance.id).where(HermesInstance.client_id == client_id)
        )).first() is not None


async def _forward_legacy(platform: str, client_id: int, data: dict, key: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(f"{settings.SERVER_B_API_URL}/api/incoming/{platform}/{client_id}",
                                json=data, headers={"x-gateway-key": key})
        return {"ok": True, "legacy": True, "status": r.status_code}
    except httpx.HTTPError:
        return {"ok": False, "legacy": True, "error": "legacy gateway unreachable"}


class WebChat(BaseModel):
    message: str = Field(..., min_length=1, max_length=20000)
    conversation: str = Field("default", max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/web/chat")
async def web_chat(data: WebChat, client: Client = Depends(get_current_client)):
    if not settings.MANAGED_HERMES_ENABLED:
        raise HTTPException(status_code=409, detail="Managed Hermes is not enabled")
    return StreamingResponse(
        channel_router.stream(client.id, f"{client.id}:{data.conversation}", data.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
