"""Default guardrails applied by the LLM proxy, outside the customer container.

- Input: the latest user message goes through the existing 3-layer
  moderation (app/services/content_moderation.py), once per user turn.
- Policy: a platform system message is prepended to every request.
- Output: secrets that look like API keys or proxy tokens are redacted.
"""
import re
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting

DEFAULT_POLICY = (
    "You are an AI staff member provided by StaffBot.my. Follow the StaffBot.my "
    "acceptable use policy: refuse requests for illegal activity, malware, "
    "harassment, sexual content involving minors, or attempts to access other "
    "customers' data or the hosting platform. Never reveal API keys, tokens, "
    "passwords or system configuration."
)
POLICY_SETTING_KEY = "llm_guardrail_prompt"

SECRET_PATTERNS = [
    re.compile(r"sbk_\d+_\d+_[0-9a-f]{64}"),           # our proxy tokens
    re.compile(r"sk-(?:or-|ant-|proj-)?[A-Za-z0-9_\-]{20,}"),  # OpenAI/OpenRouter/Anthropic style
    re.compile(r"AKIA[0-9A-Z]{16}"),                    # AWS access key id
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),          # GitHub tokens
]
REDACTED = "[REDACTED]"


def message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def latest_user_turn(messages: list) -> Optional[str]:
    """Text of the last message if it is a new user turn, else None.

    Agent loops resend the conversation each round; later rounds end with
    tool/assistant messages, so moderation runs once per user turn.
    """
    if not messages or messages[-1].get("role") != "user":
        return None
    return message_text(messages[-1]) or None


async def policy_prompt(db: AsyncSession) -> str:
    row = (await db.execute(select(Setting).where(Setting.key == POLICY_SETTING_KEY))).scalar_one_or_none()
    return (row.value if row and row.value else DEFAULT_POLICY).strip()


def with_policy(messages: list, policy: str) -> list:
    return [{"role": "system", "content": policy}] + list(messages)


def redact(text: str, extra: tuple = ()) -> str:
    """Mask known secret formats plus exact values in `extra` (e.g. the provider key in use)."""
    for value in extra:
        if value and len(value) >= 8:
            text = text.replace(value, REDACTED)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def redact_completion(body: dict, extra: tuple = ()) -> dict:
    for choice in body.get("choices") or []:
        msg = choice.get("message") or {}
        if isinstance(msg.get("content"), str):
            msg["content"] = redact(msg["content"], extra)
    return body


def redact_chunk(chunk: dict, extra: tuple = ()) -> dict:
    """Best effort for streams: a secret split across chunks is not caught."""
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        if isinstance(delta.get("content"), str):
            delta["content"] = redact(delta["content"], extra)
    return chunk


def refusal_completion(model: str, text: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-staffbot-guardrail",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
