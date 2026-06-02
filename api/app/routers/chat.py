"""Chat router — proxies to Gateway with token tracking + BYOK support."""
import os, httpx, json, logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.middleware.auth import get_current_client
from app.models.client import Client
from app.models.subscription import Subscription
from app.models.api_key import ApiKey
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


@router.post("/send")
async def chat_send(
    data: ChatSendRequest,
    current_user: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Send a chat message with token tracking + BYOK support."""
    client_id = current_user.id

    # ── 1. Determine token source ────────────────────────────────
    # BYOK if: api_key passed in request, OR user has BYOK key for this provider
    is_byok = bool(data.api_key)

    if not is_byok:
        # Check if user has BYOK key for this provider
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
            # User has BYOK — we'll use managed token (gateway handles the key)
            is_byok = False  # Gateway uses its own key routing
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

    # ── 4. Proxy to Gateway ──────────────────────────────────────
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
                },
                headers=headers,
            )
    except httpx.TimeoutException:
        return {"success": False, "error": "timeout", "message": "Request timed out. Please try again."}
    except Exception as e:
        logger.error(f"Gateway error for client #{client_id}: {e}")
        return {"success": False, "error": "gateway_error", "message": "AI service temporarily unavailable."}

    if resp.status_code != 200:
        return {"success": False, "error": "gateway_error", "message": f"Gateway error: {resp.status_code}"}

    result = resp.json()

    # ── 5. Track token usage (managed tokens only, not BYOK) ─────
    if not data.api_key and result.get("success") and result.get("tokens_used"):
        tokens_used = result["tokens_used"]

        # Re-fetch sub for update
        sub_result = await db.execute(
            select(Subscription).where(Subscription.client_id == client_id)
        )
        sub = sub_result.scalar_one_or_none()

        if sub:
            sub.managed_token_used = (sub.managed_token_used or 0) + tokens_used

            # Track per-provider usage
            if not sub.provider_token_usage:
                sub.provider_token_usage = {}
            prov = data.provider or "mimo"
            sub.provider_token_usage[prov] = sub.provider_token_usage.get(prov, 0) + tokens_used

            await db.commit()

            # Add quota info to response
            remaining = max(0, (sub.managed_token_quota or 0) - sub.managed_token_used)
            result["quota_remaining"] = remaining
            result["quota_used"] = sub.managed_token_used

            # Warn if running low (< 10%)
            if sub.managed_token_quota > 0 and remaining < sub.managed_token_quota * 0.1:
                result["quota_warning"] = f"Low token balance: {int(remaining):,} tokens remaining."

    return result


@router.get("/history")
async def chat_history(
    container_id: Optional[int] = None,
    limit: int = 50,
    current_user: Client = Depends(get_current_client),
):
    """Get chat history."""
    params = {"client_id": current_user.id, "limit": limit}
    if container_id:
        params["container_id"] = container_id

    headers = {
        "Content-Type": "application/json",
        "x-api-key": GATEWAY_KEY,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{GATEWAY_URL}/api/chat/history",
            params=params,
            headers=headers,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return resp.json()


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
