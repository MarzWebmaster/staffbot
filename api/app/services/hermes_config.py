"""Managed-scope config for a customer's Hermes container.

Renders /etc/hermes/config.yaml and /etc/hermes/.env, which the orchestrator
bind-mounts read-only (root-owned) into the customer container. Hermes gives
these values priority over the customer's own config and .env for the keys
they pin. See docs/TARGET_ARCHITECTURE.md §5 and §7.

Real enforcement stays outside the container (LLM proxy, firewall, resource
limits). A customer with a shell can run their own processes, so toolset
pins here shape the agent's default behaviour; they are not a security fence.
"""
import secrets
from typing import Optional

import yaml

from app.config import get_settings
from app.llm_proxy.tokens import make_token
from app.models.client import Client
from app.models.package import Package

API_SERVER_PORT = 8642
CORE_SKILLS_DIR = "/opt/staffbot/skills"

# Auxiliary model slots (hermes_cli/config_defaults.py, v0.22.4). Pinned to the
# main model so every call goes through the LLM proxy.
AUXILIARY_TASKS = [
    "vision", "compression", "skills_hub", "approval", "review", "mcp", "title_generation",
    "memory_query_rewrite", "tts_audio_tags", "voice_chat", "triage_specifier", "kanban_decomposer",
    "profile_describer", "goal_judge", "curator", "monitor", "background_review",
    "moa_reference", "moa_aggregator", "compact", "personality", "resume_display",
]

ALWAYS_DISABLED = ["computer_use"]              # desktop control; no desktop in a container
NO_AGENT_TERMINAL = ["terminal", "code_execution"]
BASIC_CATALOG_DISABLED = ["browser", "image_gen", "video_gen", "tts"]  # heavy RAM / external cost


def disabled_toolsets(pkg: Package) -> list[str]:
    disabled = list(ALWAYS_DISABLED)
    if not pkg.agent_terminal:
        disabled += NO_AGENT_TERMINAL
    if (pkg.catalog_tier or "basic") != "all":
        disabled += BASIC_CATALOG_DISABLED
    return disabled


def render_config(pkg: Package, default_model: str) -> str:
    settings = get_settings()
    config = {
        "model": {
            "provider": "custom",
            "base_url": settings.LLM_PROXY_PUBLIC_URL.rstrip("/") + "/v1",
            "default": default_model,
            "key_env": "STAFFBOT_LLM_TOKEN",
        },
        "fallback_providers": [],
        "auxiliary": {task: {"provider": "main"} for task in AUXILIARY_TASKS},
        "agent": {"disabled_toolsets": disabled_toolsets(pkg)},
        "plugins": {"enabled": ["staffbot"]},
        "skills": {"external_dirs": [CORE_SKILLS_DIR]},
        "terminal": {"backend": "local"},
        "updates": {"check": False},
        "security": {"redact_secrets": True},
    }
    # Post-turn self-review costs tokens on every turn; only for always-on plans.
    config["auxiliary"]["background_review"]["enabled"] = (pkg.idle_sleep_minutes == 0)
    return yaml.safe_dump(config, sort_keys=False)


def render_env(client: Client, api_server_key: str) -> str:
    settings = get_settings()
    lines = {
        "STAFFBOT_LLM_TOKEN": make_token(client.id, client.llm_token_version or 1),
        "STAFFBOT_API_URL": settings.LLM_PROXY_PUBLIC_URL.rstrip("/"),
        "STAFFBOT_CLIENT_ID": str(client.id),
        "API_SERVER_ENABLED": "true",
        "API_SERVER_HOST": "0.0.0.0",
        "API_SERVER_PORT": str(API_SERVER_PORT),
        "API_SERVER_KEY": api_server_key,
    }
    return "".join(f"{k}={v}\n" for k, v in lines.items())


def new_api_server_key() -> str:
    """Key the channel router uses to call this customer's Hermes API server."""
    return secrets.token_hex(32)


def render_managed_scope(client: Client, pkg: Package, default_model: str,
                         api_server_key: Optional[str] = None) -> tuple[str, str, str]:
    """Return (config.yaml, .env, api_server_key)."""
    key = api_server_key or new_api_server_key()
    return render_config(pkg, default_model), render_env(client, key), key
