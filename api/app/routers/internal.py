"""Internal router — for Gateway communication (same server).

Endpoints here are authenticated via x-api-key (STAFFBOT_GATEWAY_API_KEY),
NOT via user JWT tokens.
"""
import os
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.models.llm_provider import LlmProvider
from app.models.subscription import Subscription
from app.models.client_webhook import ClientWebhook
from app.models.client_search_config import ClientSearchConfig
from app.models.client_email_config import ClientEmailConfig
from app.utils.encryption import decrypt_value, encrypt_value

router = APIRouter()

GATEWAY_API_KEY = os.environ.get("STAFFBOT_SERVER_B_API_KEY", "")

async def verify_internal(x_api_key: str = Header(None)):
    """Verify internal API key for Gateway communication."""
    if not GATEWAY_API_KEY:
        raise HTTPException(status_code=500, detail="Internal auth not configured")
    if not x_api_key or x_api_key != GATEWAY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid internal API key")
    return True


class ProviderResolveRequest(BaseModel):
    provider_name: str
    client_id: int


class ProviderResolveResponse(BaseModel):
    name: str
    display_name: str
    base_url: str
    api_key: str
    default_model: str
    models: list = []


@router.post("/provider/resolve")
async def resolve_provider(
    data: ProviderResolveRequest,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(verify_internal),
):
    """Resolve a provider config with decrypted API key.
    
    Called by Gateway to get managed API keys
    for making LLM calls on behalf of clients.
    """
    result = await db.execute(
        select(LlmProvider).where(
            LlmProvider.name == data.provider_name,
            LlmProvider.is_active == True,
        )
    )
    provider = result.scalar_one_or_none()
    
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{data.provider_name}' not found or inactive")
    
    if not provider.api_key_encrypted:
        raise HTTPException(status_code=400, detail=f"Provider '{data.provider_name}' has no API key configured")
    
    # Decrypt the API key
    try:
        api_key = decrypt_value(provider.api_key_encrypted)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt API key: {str(e)}")
    
    return {
        "name": provider.name,
        "display_name": provider.display_name,
        "base_url": provider.base_url,
        "api_key": api_key,
        "default_model": provider.default_model or "deepseek-v4-flash",
        "models": provider.models or [],
    }


@router.get("/provider/list")
async def list_providers(
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(verify_internal),
):
    """List all active providers (without API keys)."""
    result = await db.execute(
        select(LlmProvider).where(LlmProvider.is_active == True)
    )
    providers = result.scalars().all()
    
    return [
        {
            "name": p.name,
            "display_name": p.display_name,
            "base_url": p.base_url,
            "default_model": p.default_model,
            "models": p.models or [],
            "api_key_configured": bool(p.api_key_encrypted),
        }
        for p in providers
    ]


class TelegramSetupInternalRequest(BaseModel):
    bot_token: str


@router.post("/client/{client_id}/telegram/setup")
async def setup_telegram_internal(
    client_id: int,
    data: TelegramSetupInternalRequest,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(verify_internal),
):
    """Internal endpoint — called by Gateway when user sends /connect <token> in Telegram chat.
    
    Same logic as clients.py setup_telegram: saves encrypted token to clients table,
    then registers webhook via telegram-manager.
    """
    from app.models.client import Client
    from app.utils.encryption import encrypt_value
    from app.services.server_b_service import GatewayService

    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Save encrypted Telegram token — SAME DB column as settings.html
    client.telegram_token_encrypted = encrypt_value(data.bot_token)
    await db.commit()
    await db.refresh(client)

    # Register webhook with telegram-manager
    try:
        webhook_result = await GatewayService.telegram_register_webhook(
            client_id=client_id,
            bot_token=data.bot_token,
        )
        return {
            "success": True,
            "message": "Telegram bot registered successfully",
            "webhook_url": webhook_result.get("webhook_url"),
        }
    except Exception as e:
        return {
            "success": True,
            "message": "Token saved. Webhook registration pending.",
            "error": str(e),
        }


class TaskCreateInternalRequest(BaseModel):
    title: str
    description: str = ""
    priority: str = "normal"
    assigned_to: Optional[str] = None
    container_id: Optional[int] = None
    created_by_agent: Optional[str] = None


@router.post("/client/{client_id}/tasks/create")
async def create_task_internal(
    client_id: int,
    data: TaskCreateInternalRequest,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(verify_internal),
):
    """Internal endpoint — called by Gateway when chat classifier detects a task.
    
    Creates a task under the given client_id, authenticated via x-api-key.
    """
    from app.models.task import Task
    from datetime import datetime

    task = Task(
        client_id=client_id,
        container_id=data.container_id,
        title=data.title,
        description=data.description,
        priority=data.priority,
        status="pending",
        assigned_to=data.assigned_to,
        created_by_agent=data.created_by_agent or "chat_classifier",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    return {
        "success": True,
        "task": {
            "id": task.id,
            "client_id": task.client_id,
            "title": task.title,
            "priority": task.priority,
            "status": task.status,
        },
    }


class WebhookResolveRequest(BaseModel):
    client_id: int
    endpoint_name: str


@router.post("/webhook/resolve")
async def resolve_webhook(
    data: WebhookResolveRequest,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(verify_internal),
):
    """Resolve a webhook config with decrypted auth value.

    Called by Gateway when LLM invokes the call_webhook tool.
    Returns full config with decrypted auth_value.
    """
    result = await db.execute(
        select(ClientWebhook).where(
            ClientWebhook.client_id == data.client_id,
            ClientWebhook.name == data.endpoint_name,
            ClientWebhook.is_active == True,
        )
    )
    webhook = result.scalar_one_or_none()

    if not webhook:
        raise HTTPException(status_code=404, detail=f"Webhook '{data.endpoint_name}' not found for client {data.client_id}")

    # Decrypt auth value if present
    auth_value = None
    if webhook.auth_value:
        try:
            auth_value = decrypt_value(webhook.auth_value)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to decrypt auth value: {str(e)}")

    return {
        "id": webhook.id,
        "client_id": webhook.client_id,
        "name": webhook.name,
        "base_url": webhook.base_url,
        "auth_type": webhook.auth_type,
        "auth_header": webhook.auth_header,
        "auth_value": auth_value,
        "default_headers": webhook.default_headers or {},
        "rate_limit": webhook.rate_limit,
        "max_timeout": webhook.max_timeout,
    }


class AuditLogInternalRequest(BaseModel):
    client_id: int
    action: str
    resource: Optional[str] = None
    detail: Optional[dict] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    status: str = "success"


class SearchConfigResolveRequest(BaseModel):
    client_id: int


@router.post("/search-config/resolve")
async def resolve_search_config(
    data: SearchConfigResolveRequest,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(verify_internal),
):
    """Resolve the active search config for a client (with decrypted api_key).

    Called by Gateway when LLM invokes the web_search tool.
    Returns the first active config (or 404 if none).
    Prefers 'brave' over 'duckduckgo' if both exist.
    """
    result = await db.execute(
        select(ClientSearchConfig)
        .where(
            ClientSearchConfig.client_id == data.client_id,
            ClientSearchConfig.is_active == True,
        )
        .order_by(
            # prefer paid providers first (brave > google > serpapi > duckduckgo)
            ClientSearchConfig.provider.desc()
        )
    )
    configs = result.scalars().all()

    if not configs:
        raise HTTPException(
            status_code=404,
            detail="No search config found. Set up via /api/v1/clients/me/search-config",
        )

    cfg = configs[0]  # first active config (preferred order)

    # Decrypt API key if present
    api_key = None
    if cfg.api_key:
        try:
            api_key = decrypt_value(cfg.api_key)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to decrypt api_key: {str(e)}")

    return {
        "id": cfg.id,
        "client_id": cfg.client_id,
        "provider": cfg.provider,
        "api_key": api_key,
        "base_url": cfg.base_url,
    }


@router.post("/audit/log")
async def audit_log_internal(
    data: AuditLogInternalRequest,
    auth: bool = Depends(verify_internal),
):
    """Internal endpoint — called by Gateway to log audit events."""
    from app.services.audit import log_audit

    audit_id = await log_audit(
        client_id=data.client_id,
        action=data.action,
        resource=data.resource,
        detail=data.detail,
        ip_address=data.ip_address,
        user_agent=data.user_agent,
        status=data.status,
    )
    return {"success": True, "audit_id": audit_id}


class EmailConfigResolveRequest(BaseModel):
    client_id: int


class EmailConfigUpsertRequest(BaseModel):
    client_id: int
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str
    smtp_pass: str  # plaintext — will be encrypted
    use_tls: bool = True
    from_email: str | None = None
    from_name: str | None = None


@router.post("/email-config/resolve")
async def resolve_email_config(
    data: EmailConfigResolveRequest,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(verify_internal),
):
    """Resolve the active email/SMTP config for a client (with decrypted password).

    Called by Gateway when LLM invokes the send_email tool.
    """
    result = await db.execute(
        select(ClientEmailConfig).where(
            ClientEmailConfig.client_id == data.client_id,
            ClientEmailConfig.is_active == True,
        )
    )
    configs = result.scalars().all()

    if not configs:
        raise HTTPException(
            status_code=404,
            detail="No email config found. Set up via /api/v1/clients/me/email-config",
        )

    cfg = configs[0]

    smtp_pass = None
    if cfg.smtp_pass:
        try:
            smtp_pass = decrypt_value(cfg.smtp_pass)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to decrypt SMTP password: {str(e)}")

    return {
        "id": cfg.id,
        "client_id": cfg.client_id,
        "smtp_host": cfg.smtp_host,
        "smtp_port": cfg.smtp_port,
        "smtp_user": cfg.smtp_user,
        "smtp_pass": smtp_pass,
        "use_tls": cfg.use_tls,
        "from_email": cfg.from_email or cfg.smtp_user,
        "from_name": cfg.from_name,
    }


@router.post("/email-config/upsert")
async def upsert_email_config(
    data: EmailConfigUpsertRequest,
    db: AsyncSession = Depends(get_db),
    auth: bool = Depends(verify_internal),
):
    """Create or update the SMTP email config for a client.

    Called by Gateway when LLM invokes the set_smtp_config tool.
    Encrypts the password before storing.
    """
    # Find existing active config
    result = await db.execute(
        select(ClientEmailConfig).where(
            ClientEmailConfig.client_id == data.client_id,
            ClientEmailConfig.is_active == True,
        )
    )
    cfg = result.scalar_one_or_none()

    encrypted_pass = encrypt_value(data.smtp_pass)

    if cfg:
        # Update existing
        cfg.smtp_host = data.smtp_host
        cfg.smtp_port = data.smtp_port
        cfg.smtp_user = data.smtp_user
        cfg.smtp_pass = encrypted_pass
        cfg.use_tls = data.use_tls
        cfg.from_email = data.from_email or data.smtp_user
        cfg.from_name = data.from_name
        await db.commit()
        await db.refresh(cfg)
        action = "updated"
        cfg_id = cfg.id
    else:
        # Create new
        cfg = ClientEmailConfig(
            client_id=data.client_id,
            smtp_host=data.smtp_host,
            smtp_port=data.smtp_port,
            smtp_user=data.smtp_user,
            smtp_pass=encrypted_pass,
            use_tls=data.use_tls,
            from_email=data.from_email or data.smtp_user,
            from_name=data.from_name,
            is_active=True,
        )
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
        action = "created"
        cfg_id = cfg.id

    return {
        "success": True,
        "action": action,
        "id": cfg_id,
        "smtp_host": cfg.smtp_host,
        "from_email": cfg.from_email or cfg.smtp_user,
    }
