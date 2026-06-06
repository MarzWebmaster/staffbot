"""Bridge to Agent Office visualization server — fire-and-forget events with tenant isolation."""
import httpx
import logging
import os

logger = logging.getLogger(__name__)

OFFICE_URL = os.getenv("OFFICE_URL", "http://127.0.0.1:3334")
try:
    with open(os.path.expanduser("~/.agent-office/auth-token"), "r") as f:
        OFFICE_TOKEN=f.read().strip()
except Exception:
    OFFICE_TOKEN = os.getenv("OFFICE_TOKEN", "")


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
