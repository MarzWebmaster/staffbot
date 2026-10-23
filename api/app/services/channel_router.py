"""Route customer conversations to their own Hermes container (docs/TARGET_ARCHITECTURE.md D15).

Web chat, WhatsApp and Telegram all end up here. Each conversation gets a
stable Hermes session (X-Hermes-Session-Id), so Hermes keeps the history and
we only send the new message. Sleeping containers are woken first.
"""
import asyncio
import hashlib
import logging
from collections import defaultdict
from typing import AsyncIterator, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.client import Client
from app.models.hermes_instance import HermesInstance
from app.models.package import Package
from app.services import hermes_orchestrator as orch
from app.services.audit import log_audit
from app.utils.encryption import decrypt_value

logger = logging.getLogger(__name__)
settings = get_settings()

TELEGRAM_CHUNK = 4000
_chat_locks: dict[tuple, asyncio.Lock] = defaultdict(asyncio.Lock)


class ChannelError(Exception):
    pass


def session_headers(platform: str, chat: str) -> dict:
    digest = hashlib.sha256(f"{platform}:{chat}".encode()).hexdigest()[:24]
    return {"X-Hermes-Session-Id": f"sb-{platform}-{digest}",
            "X-Hermes-Session-Key": f"agent:main:{platform}:{digest}"}


def channel_allowed(pkg: Package, platform: str) -> bool:
    if platform == "web":
        return True
    limits = pkg.channel_limits or {}
    return bool(limits.get(platform))


async def _instance(db: AsyncSession, client_id: int) -> tuple[Client, Package, HermesInstance]:
    client, pkg, inst = await orch._load(db, client_id)
    if client.status != "active":
        raise ChannelError(f"account is {client.status}")
    if not inst or inst.status != "running":
        inst = await orch.wake(db, client_id)
    else:
        await orch.touch(db, client_id)
    return client, pkg, inst


def _url(inst: HermesInstance) -> str:
    return f"http://{settings.CUSTOMER_GATEWAY_IP}:{inst.api_port}/v1/chat/completions"


def _headers(inst: HermesInstance, platform: str, chat: str) -> dict:
    return {"Authorization": f"Bearer {decrypt_value(inst.api_server_key_encrypted)}",
            **session_headers(platform, chat)}


def _body(text: str, stream: bool) -> dict:
    return {"model": "hermes-agent", "messages": [{"role": "user", "content": text}], "stream": stream}


async def ask(db: AsyncSession, client_id: int, platform: str, chat: str, text: str) -> str:
    """Send one user message and return the agent's reply text."""
    async with _chat_locks[(client_id, platform, chat)]:  # keep turns in order per chat
        _, _, inst = await _instance(db, client_id)
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=settings.HERMES_REQUEST_TIMEOUT) as http:
                    r = await http.post(_url(inst), headers=_headers(inst, platform, chat), json=_body(text, False))
                break
            except httpx.ConnectError:
                if attempt == 2:
                    raise ChannelError("agent unreachable")
                inst = await orch.wake(db, client_id)  # container died or was stopped
        if r.status_code != 200:
            raise ChannelError(f"agent returned HTTP {r.status_code}")
        data = r.json()
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


async def stream(client_id: int, chat: str, text: str, keepalive: float = 15.0) -> AsyncIterator[bytes]:
    """SSE passthrough for web chat, with keepalive comments while the agent works
    (keeps Cloudflare's ~100 s idle limit from cutting long tool runs).
    Uses its own DB sessions: it outlives the request's dependencies."""
    from app.database import async_session_factory
    try:
        async with async_session_factory() as db:
            _, _, inst = await _instance(db, client_id)
    except (ChannelError, orch.OrchestratorError) as e:
        yield f'data: {{"error": "{type(e).__name__}"}}\n\n'.encode()
        return
    queue: asyncio.Queue = asyncio.Queue()

    async def pump():
        try:
            async with httpx.AsyncClient(timeout=settings.HERMES_REQUEST_TIMEOUT) as http:
                async with http.stream("POST", _url(inst), headers=_headers(inst, "web", chat),
                                       json=_body(text, True)) as r:
                    if r.status_code != 200:
                        await queue.put(f'data: {{"error": "agent returned HTTP {r.status_code}"}}\n\n'.encode())
                    else:
                        async for line in r.aiter_lines():
                            await queue.put((line + "\n").encode())
        except httpx.HTTPError:
            await queue.put(b'data: {"error": "agent unreachable"}\n\n')
        finally:
            await queue.put(None)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=keepalive)
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
                continue
            if item is None:
                break
            yield item
    finally:
        task.cancel()
        async with async_session_factory() as db:
            await orch.touch(db, client_id)


# ── reply delivery ──────────────────────────────────────────

async def reply_whatsapp(client_id: int, jid: str, text: str) -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        await http.post(f"{settings.BAILEYS_MANAGER_URL}/api/session/{client_id}/send", json={"to": jid, "text": text})


async def reply_telegram(client_id: int, chat_id, text: str) -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        for i in range(0, len(text), TELEGRAM_CHUNK):
            await http.post(f"{settings.TELEGRAM_MANAGER_URL}/api/send/{client_id}",
                            json={"chat_id": chat_id, "text": text[i:i + TELEGRAM_CHUNK]})


async def handle_incoming(client_id: int, platform: str, data: dict) -> Optional[str]:
    """Background task for a WhatsApp/Telegram message. Returns the reply (for tests)."""
    from app.database import async_session_factory
    if platform == "whatsapp":
        if data.get("isGroup"):
            return None  # private chats only for now
        chat, reply_to = data.get("jid") or data.get("from"), data.get("jid") or data.get("from")
    else:
        if data.get("chat_type") not in (None, "private"):
            return None
        chat, reply_to = str(data.get("chat_id")), data.get("chat_id")
    text = (data.get("text") or "").strip()
    if not text or not chat:
        return None
    async with async_session_factory() as db:
        try:
            _, pkg, _ = await orch._load(db, client_id)
            if not channel_allowed(pkg, platform):
                await log_audit(client_id=client_id, action="channel_message", resource=platform,
                                detail={"reason": "channel not in package"}, status="blocked")
                return None
            answer = await ask(db, client_id, platform, chat, text)
        except (ChannelError, orch.OrchestratorError) as e:
            logger.warning("channel %s for client %s failed: %s", platform, client_id, e)
            answer = "Maaf, StaffBot sedang sibuk. Sila cuba sebentar lagi. / Sorry, please try again shortly."
    if not answer:
        return None
    if platform == "whatsapp":
        await reply_whatsapp(client_id, reply_to, answer)
    else:
        await reply_telegram(client_id, reply_to, answer)
    return answer
