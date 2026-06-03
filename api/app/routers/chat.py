"""Chat router — proxies to Gateway with token tracking + BYOK + message history."""
import os, httpx, json, logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.database import get_db
from app.middleware.auth import get_current_client
from app.models.client import Client
from app.models.subscription import Subscription
from app.models.api_key import ApiKey
from app.models.chat_message import ChatMessage
from app.services.enforcement_service import EnforcementService

router = APIRouter()
logger = logging.getLogger(__name__)

GATEWAY_URL = os.environ.get("STAFFBOT_SERVER_B_API_URL", "http://staffbot-gateway:8080")
GATEWAY_KEY = os.environ.get("STAFFBOT_SERVER_B_API_KEY", "")


class ChatSendRequest(BaseModel):
    content: str
    container_id: Optional[int] = None
    provider: str = "mimo"
    model: Optional[str] = None
    api_key: Optional[str] = None


async def _save_message(db: AsyncSession, client_id: int, role: str, content: str,
                        container_id: int = None, model: str = None,
                        provider: str = None, tokens_used: int = 0):
    """Save a chat message to the database."""
    msg = ChatMessage(
        client_id=client_id,
        container_id=container_id,
        role=role,
        content=content,
        model=model,
        provider=provider,
        tokens_used=tokens_used,
    )
    db.add(msg)
    await db.flush()
    return msg


@router.post("/send")
async def chat_send(
    data: ChatSendRequest,
    request: Request,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Send a chat message with token tracking + BYOK + message persistence."""
    client_id = current_user.id
    auth_token = request.headers.get("authorization", "").replace("Bearer ", "")


    # ── 1. Determine token source ────────────────────────────────
    is_byok = bool(data.api_key)

    if not is_byok:
        byok_result = await db.execute(
            select(ApiKey).where(
                ApiKey.client_id == client_id,
                ApiKey.provider == data.provider,
                ApiKey.is_active == True,
                ApiKey.is_managed == False,
            )
        )
        byok_key = byok_result.scalar_one_or_none()
        if byok_key and byok_key.key_encrypted:
            is_byok = False
        else:
            is_byok = False

    # ── 2. Check managed token quota (skip if BYOK) ──────────────
    if not data.api_key:
        sub_result = await db.execute(
            select(Subscription).where(Subscription.client_id == client_id)
        )
        sub = sub_result.scalar_one_or_none()

        if not sub:
            return {
                "success": False,
                "error": "no_subscription",
                "message": "No active subscription found. Please subscribe to a package first.",
            }

        if sub.status != "active":
            return {
                "success": False,
                "error": "subscription_inactive",
                "message": "Your subscription is not active. Please renew your subscription.",
            }

        quota = sub.managed_token_quota or 0
        used = sub.managed_token_used or 0

        if quota > 0 and used >= quota:
            return {
                "success": False,
                "error": "token_quota_exceeded",
                "message": "Token limit reached. Please top up your tokens or upgrade your package.",
                "quota": quota,
                "used": used,
                "remaining": 0,
            }

    # ── 3. Get enforcement rules ──────────────────────────────────
    enforcement = await EnforcementService.get_enforcement(
        client_id=client_id,
        db=db,
    )

    system_context = {
        "client_id": client_id,
        "client_name": current_user.name or "",
        "client_company": current_user.company or "",
        "client_package": current_user.package or "basic",
        "enforcement": {
            "allowed_skills": enforcement.get("allowed_skill_ids", []),
            "allowed_tools": enforcement.get("allowed_tool_ids", []),
            "governance": enforcement.get("governance", {}),
        },
    }

    # ── 4. Save user message BEFORE sending ───────────────────────
    await _save_message(
        db=db,
        client_id=client_id,
        role="user",
        content=data.content,
        container_id=data.container_id,
        provider=data.provider,
    )
    await db.commit()

    # ── 5. Proxy to Gateway ──────────────────────────────────────
    headers = {
        "Content-Type": "application/json",
        "x-api-key": GATEWAY_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{GATEWAY_URL}/api/chat/send",
                json={
                    "client_id": client_id,
                    "container_id": data.container_id,
                    "content": data.content,
                    "provider": data.provider,
                    "model": data.model,
                    "api_key": data.api_key,
                    "system_context": json.dumps(system_context),
                    "auth_token": auth_token,
                },
                headers=headers,
            )
    except httpx.TimeoutException:
        # Save error as assistant message
        await _save_message(db=db, client_id=client_id, role="assistant",
                           content="[Error: Request timed out]", provider=data.provider)
        await db.commit()
        return {"success": False, "error": "timeout", "message": "Request timed out. Please try again."}
    except Exception as e:
        logger.error(f"Gateway error for client #{client_id}: {e}")
        await _save_message(db=db, client_id=client_id, role="assistant",
                           content=f"[Error: AI service unavailable]", provider=data.provider)
        await db.commit()
        return {"success": False, "error": "gateway_error", "message": "AI service temporarily unavailable."}

    if resp.status_code != 200:
        await _save_message(db=db, client_id=client_id, role="assistant",
                           content=f"[Error: Gateway {resp.status_code}]", provider=data.provider)
        await db.commit()
        return {"success": False, "error": "gateway_error", "message": f"Gateway error: {resp.status_code}"}

    result = resp.json()

    # ── 6. Save assistant response ────────────────────────────────
    if result.get("success") and result.get("content"):
        await _save_message(
            db=db,
            client_id=client_id,
            role="assistant",
            content=result["content"],
            container_id=data.container_id,
            model=result.get("model"),
            provider=result.get("provider", data.provider),
            tokens_used=result.get("tokens_used", 0),
        )

    # ── 7. Track token usage (managed tokens only, not BYOK) ─────
    if not data.api_key and result.get("success") and result.get("tokens_used"):
        tokens_used = result["tokens_used"]

        sub_result = await db.execute(
            select(Subscription).where(Subscription.client_id == client_id)
        )
        sub = sub_result.scalar_one_or_none()

        if sub:
            sub.managed_token_used = (sub.managed_token_used or 0) + tokens_used

            if not sub.provider_token_usage:
                sub.provider_token_usage = {}
            prov = data.provider or "mimo"
            sub.provider_token_usage[prov] = sub.provider_token_usage.get(prov, 0) + tokens_used

            remaining = max(0, (sub.managed_token_quota or 0) - sub.managed_token_used)
            result["quota_remaining"] = remaining
            result["quota_used"] = sub.managed_token_used

            if sub.managed_token_quota > 0 and remaining < sub.managed_token_quota * 0.1:
                result["quota_warning"] = f"Low token balance: {int(remaining):,} tokens remaining."

    await db.commit()
    return result


@router.get("/history")
async def chat_history(
    container_id: Optional[int] = None,
    limit: int = Query(default=50, le=200),
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get chat history from local DB."""
    query = (
        select(ChatMessage)
        .where(ChatMessage.client_id == current_user.id)
    )

    if container_id:
        from sqlalchemy import or_
        query = query.where(or_(ChatMessage.container_id == container_id, ChatMessage.container_id.is_(None)))

    query = query.order_by(ChatMessage.created_at.asc()).limit(limit)

    result = await db.execute(query)
    messages = result.scalars().all()

    return {
        "client_id": current_user.id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "model": m.model,
                "provider": m.provider,
                "tokens_used": m.tokens_used,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.get("/token-status")
async def token_status(
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Get current token quota status for the logged-in user."""
    sub_result = await db.execute(
        select(Subscription).where(Subscription.client_id == current_user.id)
    )
    sub = sub_result.scalar_one_or_none()

    if not sub:
        return {"has_subscription": False, "quota": 0, "used": 0, "remaining": 0}

    quota = sub.managed_token_quota or 0
    used = sub.managed_token_used or 0

    return {
        "has_subscription": True,
        "status": sub.status,
        "package": sub.package,
        "quota": quota,
        "used": used,
        "remaining": max(0, quota - used),
        "percent_used": round((used / quota * 100), 1) if quota > 0 else 0,
        "provider_usage": sub.provider_token_usage or {},
    }
