"""Server-side execution of StaffBot core tools for customer Hermes agents.

The Hermes plugin in each customer container is a thin client: it calls
/api/v1/agent-tools with the customer's token, and the work happens here, so
webhook credentials and SMTP passwords never enter the container.

Rate limits are counted from audit_trail rows (shared by all API workers):
webhook 10/min, email 50/day per customer.
"""
import asyncio
import base64
import ipaddress
import json
import smtplib
import socket
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_trail import AuditTrail
from app.models.client_email_config import ClientEmailConfig
from app.models.client_webhook import ClientWebhook
from app.services.audit import log_audit
from app.utils.encryption import decrypt_value

WEBHOOK_PER_MINUTE = 10
EMAIL_PER_DAY = 50
MAX_RESPONSE_BYTES = 100_000


class ToolError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _recent_count(db: AsyncSession, client_id: int, action: str, since: datetime) -> int:
    return (await db.execute(
        select(func.count()).select_from(AuditTrail).where(
            AuditTrail.client_id == client_id,
            AuditTrail.action == action,
            AuditTrail.status == "success",
            AuditTrail.created_at >= since,
        )
    )).scalar_one()


def check_public_host(hostname: str) -> None:
    """Refuse hosts that resolve to any non-public address (fail closed).

    Covers private, loopback, link-local, CGNAT/Tailscale (100.64/10) and
    reserved ranges. A DNS answer that changes between this check and the
    request (rebinding) is not covered.
    """
    if not hostname:
        raise ToolError(400, "URL has no host")
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ToolError(400, f"Cannot resolve host {hostname}")
    for info in infos:
        addr = ipaddress.ip_address(info[4][0].split("%")[0])
        if not addr.is_global:
            raise ToolError(403, "Internal or non-public addresses are blocked")


def build_webhook_url(base_url: str, path: str) -> str:
    """Join base_url and path, refusing anything that escapes base_url."""
    if "://" in path or path.startswith("//") or "\\" in path:
        raise ToolError(400, "path must be relative to the webhook base_url")
    if any(seg == ".." for seg in path.split("?")[0].split("/")):
        raise ToolError(400, "path may not contain '..'")
    base = base_url.rstrip("/") + "/"
    url = urljoin(base, path.lstrip("/"))
    b, u = urlparse(base), urlparse(url)
    if (u.scheme, u.netloc) != (b.scheme, b.netloc) or not u.path.startswith(b.path):
        raise ToolError(400, "URL must stay under the configured base_url")
    if u.scheme not in ("http", "https"):
        raise ToolError(400, "Only http(s) webhooks are allowed")
    return url


async def list_webhooks(db: AsyncSession, client_id: int) -> list[dict]:
    rows = (await db.execute(
        select(ClientWebhook).where(ClientWebhook.client_id == client_id, ClientWebhook.is_active == True)  # noqa: E712
    )).scalars().all()
    return [{"name": w.name, "base_url": w.base_url, "auth_type": w.auth_type} for w in rows]


async def call_webhook(db: AsyncSession, client_id: int, endpoint_name: str, path: str, method: str,
                       body: Optional[dict] = None, query_params: Optional[dict] = None) -> dict:
    method = (method or "GET").upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise ToolError(400, f"Unsupported method {method}")
    if await _recent_count(db, client_id, "webhook_call", _utcnow() - timedelta(minutes=1)) >= WEBHOOK_PER_MINUTE:
        raise ToolError(429, f"Rate limit: max {WEBHOOK_PER_MINUTE} webhook calls per minute")

    hook = (await db.execute(
        select(ClientWebhook).where(
            ClientWebhook.client_id == client_id, ClientWebhook.name == endpoint_name,
            ClientWebhook.is_active == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not hook:
        raise ToolError(404, f"Webhook '{endpoint_name}' is not configured. Ask the user to add it in the portal.")

    url = build_webhook_url(hook.base_url, path or "")
    await asyncio.to_thread(check_public_host, urlparse(url).hostname or "")

    headers = dict(hook.default_headers or {})
    secret = decrypt_value(hook.auth_value) if hook.auth_value else None
    if secret and hook.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif secret and hook.auth_type == "api_key":
        headers[hook.auth_header or "X-API-Key"] = secret
    elif secret and hook.auth_type == "basic":
        headers["Authorization"] = "Basic " + base64.b64encode(secret.encode()).decode()

    try:
        async with httpx.AsyncClient(timeout=float(hook.max_timeout or 30), follow_redirects=False) as http:
            resp = await http.request(method, url, headers=headers, params=query_params or None,
                                      json=body if method in ("POST", "PUT", "PATCH") else None)
    except httpx.TimeoutException:
        raise ToolError(504, "Webhook timed out")
    except httpx.HTTPError as e:
        raise ToolError(502, f"Webhook request failed: {type(e).__name__}")

    raw = resp.content[:MAX_RESPONSE_BYTES]
    text = raw.decode(errors="replace")
    if secret:
        text = text.replace(secret, "[REDACTED]")
    try:
        data = json.loads(text)
    except ValueError:
        data = text
    await log_audit(client_id=client_id, action="webhook_call", resource=f"webhook:{endpoint_name}",
                    detail={"method": method, "url": url, "status_code": resp.status_code})
    return {"status_code": resp.status_code, "data": data, "truncated": len(resp.content) > MAX_RESPONSE_BYTES}


async def send_email(db: AsyncSession, client_id: int, to: str, subject: str, body: str,
                     cc: Optional[str] = None) -> dict:
    if not to or not subject or not body:
        raise ToolError(400, "to, subject and body are required")
    if await _recent_count(db, client_id, "email_send", _utcnow() - timedelta(days=1)) >= EMAIL_PER_DAY:
        raise ToolError(429, f"Rate limit: max {EMAIL_PER_DAY} emails per day")
    cfg = (await db.execute(
        select(ClientEmailConfig).where(ClientEmailConfig.client_id == client_id, ClientEmailConfig.is_active == True)  # noqa: E712
    )).scalars().first()
    if not cfg:
        raise ToolError(404, "No email (SMTP) settings. Ask the user to add them in the portal.")
    password = decrypt_value(cfg.smtp_pass)

    def _send() -> None:
        msg = MIMEMultipart()
        sender = cfg.from_email or cfg.smtp_user
        msg["From"] = f"{cfg.from_name} <{sender}>" if cfg.from_name else sender
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg.attach(MIMEText(body, "html" if "<" in body and ">" in body else "plain", "utf-8"))
        recipients = [to] + ([cc] if cc else [])
        if cfg.smtp_port == 465:
            with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=20) as s:
                s.login(cfg.smtp_user, password)
                s.sendmail(sender, recipients, msg.as_string())
        else:
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20) as s:
                if cfg.use_tls:
                    s.starttls()
                s.login(cfg.smtp_user, password)
                s.sendmail(sender, recipients, msg.as_string())

    try:
        await asyncio.to_thread(_send)
    except smtplib.SMTPAuthenticationError:
        raise ToolError(502, "SMTP login failed. Ask the user to check their email settings.")
    except (smtplib.SMTPException, OSError) as e:
        raise ToolError(502, f"Email could not be sent: {type(e).__name__}")
    await log_audit(client_id=client_id, action="email_send", resource="email",
                    detail={"to": to, "cc": cc, "subject": subject[:200]})
    return {"sent": True, "to": to, "subject": subject}
