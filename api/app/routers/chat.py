"""Chat router — proxies to Gateway with token tracking + BYOK + message history."""
import os, httpx, json, logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header, UploadFile, File
from pydantic import BaseModel
import io, os as _os, base64, tempfile

try:
    import pymupdf
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.database import get_db
from app.middleware.auth import get_current_client, get_current_client_or_internal
from app.models.client import Client
from app.models.subscription import Subscription
from app.models.api_key import ApiKey
from app.models.chat_message import ChatMessage
from app.services.enforcement_service import EnforcementService
from app.services.content_moderation import moderate_message



class LinkExtractRequest(BaseModel):
    url: str


class AttachmentData(BaseModel):
    filename: str = ""
    text: str = ""
    mime_type: str = ""
    image_base64: str = None
    pdf_base64: str = None

router = APIRouter()
logger = logging.getLogger(__name__)

GATEWAY_URL = os.environ.get("STAFFBOT_SERVER_B_API_URL", "http://staffbot-gateway:8080")
GATEWAY_KEY = os.environ.get("STAFFBOT_SERVER_B_API_KEY", "")
MIMO_URL = os.environ.get("MIMO_BASE_URL", "https://jemaahapi.tail5cfbb9.ts.net/v1")
MIMO_KEY = os.environ.get("MIMO_API_KEY", "")
HERMES_URL = os.environ.get("HERMES_GATEWAY_URL", "http://staffbot-gateway:8642")
HERMES_KEY = os.environ.get("HERMES_API_KEY", "")


class ChatSendRequest(BaseModel):
    content: str
    container_id: Optional[int] = None
    provider: str = "mimo"
    model: Optional[str] = None
    api_key: Optional[str] = None
    image_base64: Optional[str] = None


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

    # ── 4b. Content moderation — scan before AI forward ────────────
    violation = await moderate_message(
        message=data.content,
        client_id=client_id,
        db=db,
    )
    if violation:
        await _save_message(
            db=db, client_id=client_id, role="assistant",
            content=violation["message"], provider=data.provider,
        )
        await db.commit()
        return {
            "success": False,
            "error": "policy_violation",
            "message": violation["message"],
            "categories": violation["categories"],
            "action": violation["action"],
        }

    # ── 5. Route ALL traffic to Hermes Native :8642 (text + vision) ─
    has_image = bool(data.image_base64)

    if has_image:
        # Vision — use Mimo Omni via Hermes custom_providers
        user_content = [
            {"type": "text", "text": data.content},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data.image_base64}"}},
        ]
        model_name = "mimo/mimo-v2-omni"
    else:
        # Text — use default model with tools
        user_content = data.content
        model_name = data.model or "deepseek-v4-flash"

    target_url = f"{HERMES_URL}/v1/chat/completions"
    req_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {HERMES_KEY}",
    }
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"You are an AI Staff agent for {current_user.name or 'Client'} "
                    f"({current_user.company or 'StaffBot'}). "
                    f"Client ID: {client_id}. "
                    "Be helpful, professional, and concise."
                ),
            },
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 2000,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(target_url, json=payload, headers=req_headers)
    except httpx.TimeoutException:
        # Save error as assistant message
        await _save_message(db=db, client_id=client_id, role="assistant",
                           content="[Error: Request timed out]", provider=data.provider)
        await db.commit()
        return {"success": False, "error": "timeout", "message": "Request timed out. Please try again."}
    except Exception as e:
        logger.error(f"Hermes error for client #{client_id}: {e}")
        await _save_message(db=db, client_id=client_id, role="assistant",
                           content=f"[Error: AI service unavailable]", provider=data.provider)
        await db.commit()
        return {"success": False, "error": "gateway_error", "message": "AI service temporarily unavailable."}

    if resp.status_code != 200:
        await _save_message(db=db, client_id=client_id, role="assistant",
                           content=f"[Error: Gateway {resp.status_code}]", provider=data.provider)
        await db.commit()
        return {"success": False, "error": "gateway_error", "message": f"Gateway error: {resp.status_code}"}

    hermes_data = resp.json()
    choices = hermes_data.get("choices", [])
    assistant_content = choices[0].get("message", {}).get("content", "") if choices else ""
    
    result = {
        "success": True,
        "content": assistant_content,
        "model": hermes_data.get("model", data.model or "deepseek-v4-flash"),
        "provider": data.provider or "deepseek",
        "tokens_used": hermes_data.get("usage", {}).get("total_tokens", 0),
    }

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

# ── Document Upload & Link Extraction Endpoints ──────────────────

import io
import tempfile
import os as _os

try:
    import pymupdf
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


@router.post("/upload")
async def chat_upload(
    file: UploadFile = File(...),
    current_user: Client = Depends(get_current_client_or_internal),
):
    """Upload a document and extract its text content for AI chat."""
    client_id = current_user.id

    # Validate file size (max 10MB)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Max 10MB.")

    filename = file.filename or "document"
    ext = _os.path.splitext(filename)[1].lower()
    text = ""

    try:
        if ext == ".pdf" and HAS_PYMUPDF:
            doc = pymupdf.open(stream=content, filetype="pdf")
            for page in doc:
                text += page.get_text() + "\n"
            doc.close()

        elif ext in (".docx", ".doc") and HAS_DOCX:
            doc = DocxDocument(io.BytesIO(content))
            for para in doc.paragraphs:
                text += para.text + "\n"

        elif ext in (".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".py", ".js", ".html", ".css"):
            text = content.decode("utf-8", errors="replace")

        elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            # Images — return as base64 for vision models
            import base64
            b64 = base64.b64encode(content).decode()
            mime = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp"
            }.get(ext, "image/png")
            return {
                "success": True,
                "filename": filename,
                "mime_type": mime,
                "image_base64": b64,
                "text": f"[Image: {filename}]",
                "hint": "Include in message as vision context",
            }

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to extract text: {str(e)[:200]}")

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from this file.")

    # Truncate to reasonable size (50KB)
    if len(text) > 50000:
        text = text[:50000] + "\n\n[Content truncated at 50KB]"

    return {
        "success": True,
        "filename": filename,
        "ext": ext,
        "text_length": len(text),
        "text": text,
    }


@router.post("/extract-link")
async def chat_extract_link(
    data: LinkExtractRequest,
    current_user: Client = Depends(get_current_client_or_internal),
):
    """Extract content from a URL for AI chat context."""
    url = data.url.strip()

    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL. Must start with http:// or https://")

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "StaffBot/1.0"},
            )

        if resp.status_code != 200:
            raise HTTPException(status_code=422, detail=f"Failed to fetch URL: HTTP {resp.status_code}")

        content_type = resp.headers.get("content-type", "").lower()
        text = ""

        if "application/pdf" in content_type:
            if HAS_PYMUPDF:
                doc = pymupdf.open(stream=resp.content, filetype="pdf")
                for page in doc:
                    text += page.get_text() + "\n"
                doc.close()
            else:
                # Return PDF as base64
                import base64
                return {
                    "success": True,
                    "url": url,
                    "mime_type": "application/pdf",
                    "pdf_base64": base64.b64encode(resp.content).decode(),
                    "text": f"[PDF: {url}]",
                    "hint": "Include PDF content for AI analysis",
                }

        elif "text/html" in content_type and HAS_BS4:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove scripts and styles
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)

        elif "text/" in content_type or "application/json" in content_type:
            text = resp.text

        else:
            return {
                "success": True,
                "url": url,
                "content_type": content_type,
                "text": f"[Binary content: {content_type}]",
                "hint": f"URL returns {content_type}. AI cannot process this directly.",
            }

    except httpx.TimeoutException:
        raise HTTPException(status_code=422, detail="Request timed out while fetching URL")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to extract content: {str(e)[:200]}")

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text content found at this URL.")

    # Truncate
    if len(text) > 50000:
        text = text[:50000] + "\n\n[Content truncated at 50KB]"

    return {
        "success": True,
        "url": url,
        "content_type": content_type,
        "text_length": len(text),
        "text": text,
    }

