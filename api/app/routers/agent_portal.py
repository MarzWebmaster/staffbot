"""Customer portal: my Hermes Agent status, wake, and the Web Console.

The Web Console (docs/TARGET_ARCHITECTURE.md §7A, D17) is a terminal in the
browser: a WebSocket bridged to `docker exec` inside the customer's own
container, running `hermes` or a shell depending on packages.console_mode.
Sessions are audited and time out when idle.

Open with ?ticket= from POST /api/v1/agent/console-ticket (60 s, single use).
WebSocket protocol (browser -> server, JSON text frames):
  {"type": "input", "data": "<keystrokes>"}
  {"type": "resize", "cols": 120, "rows": 32}
Server -> browser: binary frames with terminal output.
"""
import asyncio
import json
import logging
import secrets
import time
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory, get_db
from app.middleware.auth import get_current_client
from app.models.client import Client
from app.services import hermes_orchestrator as orch
from app.services.audit import log_audit
from app.utils.security import create_access_token, decode_access_token

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

CONSOLE_IDLE_SECONDS = 15 * 60
CONSOLE_MAX_SECONDS = 2 * 60 * 60
CONSOLE_COMMANDS = {"hermes": ["hermes"], "shell": ["/bin/bash", "-l"]}
CONSOLE_TICKET_SECONDS = 60
_used_tickets: dict[str, float] = {}  # jti -> expiry (per worker)


@router.get("/me")
async def my_agent(client: Client = Depends(get_current_client), db: AsyncSession = Depends(get_db)):
    _, pkg, inst = await orch._load(db, client.id)
    return {
        "managed_hermes": settings.MANAGED_HERMES_ENABLED,
        "instance": None if not inst else {
            "status": inst.status, "image": inst.image,
            "last_active_at": inst.last_active_at.isoformat() if inst.last_active_at else None,
            "last_backup_at": inst.last_backup_at.isoformat() if inst.last_backup_at else None,
        },
        "package": {
            "name": pkg.name, "display_name": pkg.display_name,
            "console_mode": pkg.console_mode or "none", "agent_terminal": bool(pkg.agent_terminal),
            "catalog_tier": pkg.catalog_tier or "basic", "channel_limits": pkg.channel_limits or {},
            "idle_sleep_minutes": pkg.idle_sleep_minutes, "byok_allowed": pkg.byok_allowed is not False,
        },
    }


@router.post("/wake")
async def wake_agent(client: Client = Depends(get_current_client), db: AsyncSession = Depends(get_db)):
    if not settings.MANAGED_HERMES_ENABLED:
        raise HTTPException(status_code=409, detail="Managed Hermes is not enabled")
    try:
        inst = await orch.wake(db, client.id)
    except orch.OrchestratorError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"status": inst.status}


@router.post("/console-ticket")
async def console_ticket(client: Client = Depends(get_current_client)):
    """Short-lived, single-use ticket for opening the console WebSocket, so the
    login token never appears in a URL (proxy/CDN access logs)."""
    ticket = create_access_token(
        {"sub": client.email, "purpose": "console", "jti": secrets.token_hex(16)},
        expires_delta=timedelta(seconds=CONSOLE_TICKET_SECONDS),
    )
    return {"ticket": ticket, "expires_in": CONSOLE_TICKET_SECONDS}


def _claim_ticket(payload: dict) -> bool:
    now = time.time()
    for jti, exp in list(_used_tickets.items()):
        if exp < now:
            _used_tickets.pop(jti, None)
    jti = payload.get("jti")
    if not jti or jti in _used_tickets:
        return False
    _used_tickets[jti] = float(payload.get("exp", now + CONSOLE_TICKET_SECONDS))
    return True


async def _console_client(ticket: str) -> Optional[tuple[Client, str]]:
    payload = decode_access_token(ticket or "")
    if not payload or not payload.get("sub") or payload.get("purpose") != "console" or not _claim_ticket(payload):
        return None
    from sqlalchemy import select
    async with async_session_factory() as db:
        client = (await db.execute(select(Client).where(Client.email == payload["sub"]))).scalar_one_or_none()
        if not client or client.status != "active":
            return None
        _, pkg, _ = await orch._load(db, client.id)
        mode = pkg.console_mode or "none"
    return (client, mode) if mode in CONSOLE_COMMANDS else None


def open_exec(container: str, mode: str, dk=None):
    """Start an interactive exec in the customer's container; returns (exec_id, raw socket)."""
    dk = dk or orch._docker()
    exec_id = dk.api.exec_create(
        container, CONSOLE_COMMANDS[mode], stdin=True, tty=True, user="hermes", workdir="/opt/data",
        environment={"TERM": "xterm-256color"},
    )["Id"]
    sock = dk.api.exec_start(exec_id, tty=True, socket=True)
    raw = getattr(sock, "_sock", sock)
    raw.setblocking(False)
    return dk, exec_id, raw


@router.websocket("/console")
async def console(ws: WebSocket, ticket: str = Query("")):
    """Browsers cannot set headers on WebSockets, so a single-use ticket from
    POST /console-ticket comes as ?ticket=."""
    found = await _console_client(ticket)
    await ws.accept()  # accept first: a close code is only delivered after the handshake
    if not settings.MANAGED_HERMES_ENABLED or not found:
        await ws.close(code=4403, reason="console not allowed")
        return
    client, mode = found
    try:
        async with async_session_factory() as db:
            inst = await orch.wake(db, client.id)
        dk, exec_id, raw = await asyncio.to_thread(open_exec, inst.container_name, mode)
    except Exception as e:
        logger.warning("console open failed for client %s: %s", client.id, e)
        await ws.send_bytes(b"\r\n[StaffBot] Agent is not available right now. Please try again.\r\n")
        await ws.close(code=1011)
        return

    await log_audit(client_id=client.id, action="console_session", resource=mode, detail={"event": "start"})
    loop = asyncio.get_running_loop()
    started = last_input = time.monotonic()

    async def pump_output():
        while True:
            data = await loop.sock_recv(raw, 65536)
            if not data:
                break
            await ws.send_bytes(data)

    async def pump_input():
        nonlocal last_input
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "input":
                last_input = time.monotonic()
                await loop.sock_sendall(raw, msg.get("data", "").encode())
            elif msg.get("type") == "resize":
                await asyncio.to_thread(dk.api.exec_resize, exec_id,
                                        height=int(msg.get("rows", 24)), width=int(msg.get("cols", 80)))

    async def watchdog():
        while True:
            await asyncio.sleep(5)
            now = time.monotonic()
            if now - last_input > CONSOLE_IDLE_SECONDS or now - started > CONSOLE_MAX_SECONDS:
                await ws.send_bytes(b"\r\n[StaffBot] Console session timed out.\r\n")
                break

    tasks = [asyncio.create_task(t()) for t in (pump_output, pump_input, watchdog)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        try:
            raw.close()
        except OSError:
            pass
        try:
            await ws.close()
        except Exception:
            pass
        async with async_session_factory() as db:
            await orch.touch(db, client.id)
        await log_audit(client_id=client.id, action="console_session", resource=mode,
                        detail={"event": "end", "seconds": int(time.monotonic() - started)})
