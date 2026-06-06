"""Bridge to Agent Office visualization server — fire-and-forget events with tenant isolation.

Events:
  - agent_spawned / agent_working / agent_completed  (chat activity)
  - bot_created / bot_updated / bot_deleted          (CRUD activity)
"""
import httpx
import logging
import os

logger = logging.getLogger(__name__)

OFFICE_URL = os.getenv("OFFICE_URL", "http://127.0.0.1:3334")
try:
    with open(os.path.expanduser("~/.agent-office/auth-token"), "r") as f:
        OFFICE_TOKEN = f.read().strip()
except Exception:
    OFFICE_TOKEN = os.environ.get("OFFICE_AUTH_TOKEN", "")


def _send_event(event: dict):
    """Fire-and-forget POST to office server."""
    if not OFFICE_TOKEN:
        return
    try:
        httpx.post(
            f"{OFFICE_URL}/event",
            json=event,
            headers={"Authorization": f"Bearer {OFFICE_TOKEN}"},
            timeout=3.0,
        )
    except Exception:
        pass  # Office server is optional — never block main flow


# ─── Chat activity events ───────────────────────────────────────────


def agent_spawned(client_id: int, name: str, role: str, task: str):
    _send_event({
        "type": "agent_spawned",
        "client_id": client_id,
        "agent": {"name": name, "role": role, "task": task},
    })


def agent_working(client_id: int, agent_id: str):
    _send_event({
        "type": "agent_working",
        "client_id": client_id,
        "agentId": agent_id,
        "status": "processing",
    })


def agent_completed(client_id: int, agent_id: str, result: str = ""):
    _send_event({
        "type": "agent_completed",
        "client_id": client_id,
        "agentId": agent_id,
        "result": result,
    })


# ─── Bot CRUD events (persistent staff presence) ────────────────────


def bot_created(client_id: int, bot_id: int, name: str, agent_name: str = "", skills: list | None = None):
    """Fire when customer creates a new bot — agent joins the office permanently."""
    _send_event({
        "type": "bot_created",
        "client_id": client_id,
        "bot": {
            "id": f"bot-{bot_id}",
            "name": agent_name or name,
            "botName": name,
            "role": "general-purpose",
            "skills": skills or [],
        },
    })


def bot_updated(client_id: int, bot_id: int, name: str, agent_name: str = "", skills: list | None = None):
    """Fire when customer updates bot config — agent appearance changes."""
    _send_event({
        "type": "bot_updated",
        "client_id": client_id,
        "bot": {
            "id": f"bot-{bot_id}",
            "name": agent_name or name,
            "botName": name,
            "role": "general-purpose",
            "skills": skills or [],
        },
    })


def bot_deleted(client_id: int, bot_id: int):
    """Fire when customer deletes a bot — agent leaves the office permanently."""
    _send_event({
        "type": "bot_deleted",
        "client_id": client_id,
        "botId": f"bot-{bot_id}",
    })


def bot_activated(client_id: int, bot_id: int):
    """Fire when customer activates a bot — agent comes alive."""
    _send_event({
        "type": "bot_activated",
        "client_id": client_id,
        "botId": f"bot-{bot_id}",
    })


def bot_deactivated(client_id: int, bot_id: int):
    """Fire when customer deactivates a bot — agent goes grey/sleeping."""
    _send_event({
        "type": "bot_deactivated",
        "client_id": client_id,
        "botId": f"bot-{bot_id}",
    })
