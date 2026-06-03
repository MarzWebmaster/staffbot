"""
StaffBot — Gateway Config Generator (API-side)
Generates Hermes config.yaml from DB providers with decrypted API keys,
then pushes to gateway via internal API.
"""
import os, json, yaml, httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.llm_provider import LlmProvider
from app.utils.encryption import decrypt_value


PACKAGE_LIMITS = {
    "trial": {"max_turns": 15, "max_tool_rounds": 25, "bot_limit": 1, "token_quota": 1000,
              "rate_limit_rps": 3, "rate_limit_burst": 5, "max_concurrent_llm": 1},
    "basic": {"max_turns": 20, "max_tool_rounds": 30, "bot_limit": 1, "token_quota": 10000,
              "rate_limit_rps": 5, "rate_limit_burst": 10, "max_concurrent_llm": 2},
    "pro": {"max_turns": 30, "max_tool_rounds": 50, "bot_limit": 3, "token_quota": 50000,
            "rate_limit_rps": 10, "rate_limit_burst": 20, "max_concurrent_llm": 5},
    "enterprise": {"max_turns": 60, "max_tool_rounds": 100, "bot_limit": 10, "token_quota": 500000,
                   "rate_limit_rps": 20, "rate_limit_burst": 50, "max_concurrent_llm": 10},
}


async def build_gateway_config(db: AsyncSession) -> dict:
    """Build complete Hermes config from DB providers."""
    # Get active providers
    result = await db.execute(
        select(LlmProvider)
        .where(LlmProvider.is_active == True)
        .order_by(LlmProvider.sort_order)
    )
    providers = result.scalars().all()

    custom_providers = []
    primary_model = "deepseek-v4-flash"
    primary_provider = "deepseek"
    primary_base_url = "https://api.deepseek.com/v1"

    for p in providers:
        api_key = ""
        if p.api_key_encrypted:
            try:
                api_key = decrypt_value(p.api_key_encrypted)
            except Exception:
                pass  # Skip corrupted keys
        entry = {
            "name": p.name,
            "base_url": p.base_url,
        }
        if api_key:
            entry["api_key"] = api_key
        custom_providers.append(entry)

        # First provider is primary
        if providers.index(p) == 0:
            primary_provider = f"custom:{p.name}"
            primary_base_url = p.base_url
            if p.default_model:
                primary_model = p.default_model

    config = {
        "model": {
            "default": primary_model,
            "provider": primary_provider,
            "base_url": primary_base_url,
            "context_length": 128000,
        },
        "agent": {
            "max_turns": 90,
            "tool_use_enforcement": True,
            "reasoning_effort": "auto",
        },
        "terminal": {
            "backend": "local",
            "cwd": "/app/data/workspace",
            "timeout": 180,
        },
        "compression": {"enabled": True, "threshold": 0.50, "target_ratio": 0.20},
        "display": {"skin": "auto", "tool_progress": True, "show_reasoning": False, "show_cost": False},
        "gateway": {
            "enabled": True,
            "profiles_dir": os.environ.get("STAFFBOT_PROFILES_DIR", "/app/data/profiles"),
        },
        "platform_toolsets": {"api_server": ["hermes-api-server", "staffbot"]},
        "staffbot": {
            "version": "2.5.0",
            "mode": "multi-tenant-gateway",
            "db_url": os.environ.get("STAFFBOT_DATABASE_URL", ""),
            "package_limits": PACKAGE_LIMITS,
        },
        "security": {"redact_secrets": True, "tirith_enabled": False},
        "privacy": {"redact_pii": True},
    }

    if custom_providers:
        config["custom_providers"] = custom_providers

    return config


async def push_config_to_gateway(config: dict) -> bool:
    """Push config to gateway's /admin/regenerate-config endpoint."""
    gw_url = os.environ.get("STAFFBOT_SERVER_B_API_URL", "http://staffbot-gateway:8080")
    gw_key = os.environ.get("STAFFBOT_SERVER_B_API_KEY", "")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{gw_url}/admin/regenerate-config",
                json=config,
                headers={"x-api-key": gw_key},
            )
            return resp.status_code == 200
    except Exception:
        return False
