"""Per-customer LLM proxy tokens.

Format: sbk_<client_id>_<version>_<hmac>. The client id is readable so the
proxy can look the customer up; the HMAC (keyed by LLM_PROXY_SECRET) makes it
unforgeable, and bumping clients.llm_token_version revokes old tokens.
"""
import hashlib
import hmac
from typing import Optional, Tuple

from app.config import get_settings

PREFIX = "sbk"


def _sig(secret: str, client_id: int, version: int) -> str:
    msg = f"llm:{client_id}:{version}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def make_token(client_id: int, version: int, secret: Optional[str] = None) -> str:
    secret = secret or get_settings().LLM_PROXY_SECRET
    if not secret:
        raise RuntimeError("STAFFBOT_LLM_PROXY_SECRET is not set")
    return f"{PREFIX}_{client_id}_{version}_{_sig(secret, client_id, version)}"


def parse_token(token: str, secret: Optional[str] = None) -> Optional[Tuple[int, int]]:
    """Return (client_id, version) for a valid token, else None."""
    secret = secret or get_settings().LLM_PROXY_SECRET
    if not secret or not token:
        return None
    parts = token.split("_")
    if len(parts) != 4 or parts[0] != PREFIX:
        return None
    try:
        client_id, version = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if not hmac.compare_digest(parts[3], _sig(secret, client_id, version)):
        return None
    return client_id, version
