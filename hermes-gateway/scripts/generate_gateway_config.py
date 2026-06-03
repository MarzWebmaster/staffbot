#!/usr/bin/env python3
"""
StaffBot.my — Hermes Gateway Config Generator v2.4
===================================================
Generates the base Hermes config.yaml for the Gateway.
v2.4: DB-driven providers — reads llm_providers table, falls back to env vars.

Three-tier config:
  1. Base (this file) — default for all clients
  2. Package tier — limits by package (trial/basic/pro/enterprise)
  3. Client override — governance policy from admin panel
"""

import argparse
import os
import sys
import yaml
import json
import hashlib
import base64

PACKAGE_LIMITS = {
    "trial": {
        "max_turns": 15,
        "max_tool_rounds": 25,
        "bot_limit": 1,
        "token_quota": 1000,
        "rate_limit_rps": 3,
        "rate_limit_burst": 5,
        "max_concurrent_llm": 1,
        "disabled_toolsets": [
            "browser", "delegation", "cronjob", "kanban",
            "discord", "discord_admin", "homeassistant",
            "video_gen", "tts", "image_gen",
        ],
        "disabled_skills": [],
        "enabled_toolsets": ["web", "file", "terminal", "memory", "search", "staffbot"],
    },
    "basic": {
        "max_turns": 20,
        "max_tool_rounds": 30,
        "bot_limit": 1,
        "token_quota": 10000,
        "rate_limit_rps": 5,
        "rate_limit_burst": 10,
        "max_concurrent_llm": 2,
        "disabled_toolsets": [
            "browser", "delegation", "cronjob", "kanban",
            "homeassistant", "discord_admin",
        ],
        "disabled_skills": [],
        "enabled_toolsets": ["web", "file", "terminal", "memory", "search", "skills",
                             "session_search", "messaging", "clarify", "staffbot"],
    },
    "pro": {
        "max_turns": 30,
        "max_tool_rounds": 50,
        "bot_limit": 3,
        "token_quota": 50000,
        "rate_limit_rps": 10,
        "rate_limit_burst": 20,
        "max_concurrent_llm": 5,
        "disabled_toolsets": [],
        "disabled_skills": [],
        "enabled_toolsets": [],
    },
    "enterprise": {
        "max_turns": 60,
        "max_tool_rounds": 100,
        "bot_limit": 10,
        "token_quota": 500000,
        "rate_limit_rps": 20,
        "rate_limit_burst": 50,
        "max_concurrent_llm": 10,
        "disabled_toolsets": [],
        "disabled_skills": [],
        "enabled_toolsets": [],
    },
}


# ── Encryption (mirrors API's app/utils/encryption.py) ──────────────

def _derive_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def decrypt_value(encrypted: str, secret: str) -> str:
    """Decrypt a value encrypted with the API's Fernet cipher."""
    if not encrypted or not secret:
        return ""
    try:
        from cryptography.fernet import Fernet
        key = _derive_fernet_key(secret)
        cipher = Fernet(key)
        return cipher.decrypt(encrypted.encode()).decode()
    except Exception:
        return ""


# ── DB Provider Reader ──────────────────────────────────────────────

def _get_db_providers(db_url: str, secret: str) -> list[dict]:
    """Fetch active LLM providers from the database. Returns empty list on failure."""
    if not db_url:
        return []
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT name, display_name, base_url, api_key_encrypted,
                   models, default_model, is_active, sort_order
            FROM llm_providers
            WHERE is_active = TRUE
            ORDER BY sort_order, id
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        providers = []
        for row in rows:
            name, display_name, base_url, key_enc, models_json, default_model, is_active, sort_order = row
            api_key = decrypt_value(key_enc or "", secret)
            models = json.loads(models_json) if isinstance(models_json, str) else (models_json or [])

            providers.append({
                "name": name,
                "display_name": display_name,
                "base_url": base_url,
                "api_key": api_key,
                "models": models,
                "default_model": default_model,
                "sort_order": sort_order,
            })

        return providers
    except Exception as e:
        print(f"[ConfigGen] DB read failed: {e}", file=sys.stderr)
        return []


def _build_custom_providers(db_providers: list[dict]) -> list[dict]:
    """Build Hermes custom_providers section from DB providers."""
    custom_providers = []
    for p in db_providers:
        entry = {
            "name": p["name"],
            "base_url": p["base_url"],
        }
        if p["api_key"]:
            entry["api_key"] = p["api_key"]
        custom_providers.append(entry)
    return custom_providers


# ── Config Generation ───────────────────────────────────────────────

def generate_base_config(db_providers: list[dict] = None, secret: str = None) -> dict:
    """Generate the base Hermes Gateway config.

    Priority: DB providers > env vars.
    """
    db_providers = db_providers or []

    # Determine primary provider: first DB provider, or env var fallback
    if db_providers:
        primary = db_providers[0]
        model_provider = f"custom:{primary['name']}"
        model_default = primary.get("default_model") or (primary.get("models", [None])[0] if primary.get("models") else "default")
        model_base_url = primary["base_url"]
    else:
        model_provider = os.environ.get("LLM_PROVIDER", "openrouter")
        model_default = os.environ.get("LLM_MODEL", "deepseek/deepseek-chat")
        model_base_url = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")

    config = {
        "model": {
            "default": model_default,
            "provider": model_provider,
            "base_url": model_base_url,
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
        "compression": {
            "enabled": True,
            "threshold": 0.50,
            "target_ratio": 0.20,
        },
        "display": {
            "skin": "auto",
            "tool_progress": True,
            "show_reasoning": False,
            "show_cost": False,
        },
        "gateway": {
            "enabled": True,
            "profiles_dir": os.environ.get("STAFFBOT_PROFILES_DIR", "/app/data/profiles"),
        },
        "platform_toolsets": {
            "api_server": ["hermes-api-server", "staffbot"],
        },
        "staffbot": {
            "version": "2.4.0",
            "mode": "multi-tenant-gateway",
            "db_url": os.environ.get("DATABASE_URL", ""),
            "package_limits": PACKAGE_LIMITS,
        },
        "security": {
            "redact_secrets": True,
            "tirith_enabled": False,
        },
        "privacy": {
            "redact_pii": True,
        },
    }

    # Add custom_providers from DB
    custom_providers = _build_custom_providers(db_providers)
    if custom_providers:
        config["custom_providers"] = custom_providers

    return config


def generate_profile_config(client_id: int, package: str, governance: dict = None) -> dict:
    """Generate a per-client profile config.yaml."""
    pkg = PACKAGE_LIMITS.get(package, PACKAGE_LIMITS["basic"])
    governance = governance or {}

    config = {
        "model": {
            "default": governance.get("model", "deepseek/deepseek-chat"),
            "provider": governance.get("provider", "openrouter"),
        },
        "agent": {
            "max_turns": governance.get("max_turns", pkg["max_turns"]),
            "max_tool_rounds": governance.get("max_tool_rounds", pkg["max_tool_rounds"]),
        },
        "client": {
            "id": client_id,
            "package": package,
        },
        "rate_limit": {
            "requests_per_second": pkg["rate_limit_rps"],
            "burst": pkg["rate_limit_burst"],
            "max_concurrent_llm": pkg["max_concurrent_llm"],
            "daily_token_quota": pkg["token_quota"],
        },
        "toolsets": {
            "disabled": governance.get("disabled_tools", pkg["disabled_toolsets"]),
            "enabled": governance.get("enabled_tools", pkg["enabled_toolsets"]),
        },
        "skills": {
            "disabled": governance.get("disabled_skills", pkg["disabled_skills"]),
        },
        "governance": governance,
    }

    return config


def main():
    parser = argparse.ArgumentParser(description="Generate StaffBot Hermes config")
    parser.add_argument("--output", default="/app/data/config.yaml")
    parser.add_argument("--client-id", type=int, help="Generate per-client profile config")
    parser.add_argument("--package", default="basic", choices=["trial", "basic", "pro", "enterprise"])
    parser.add_argument("--db", action="store_true", help="Read providers from database")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", "")
    secret = os.environ.get("SECRET_KEY", "")

    # Read providers from DB if requested
    db_providers = []
    if args.db and db_url:
        db_providers = _get_db_providers(db_url, secret)
        print(f"[ConfigGen] Loaded {len(db_providers)} providers from DB")

    if args.client_id:
        config = generate_profile_config(args.client_id, args.package)
    else:
        config = generate_base_config(db_providers, secret)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    print(f"[ConfigGen] ✅ Config written to {args.output}")
    if db_providers:
        print(f"[ConfigGen] Providers: {', '.join(p['name'] for p in db_providers)}")
        print(f"[ConfigGen] Primary: custom:{db_providers[0]['name']} → {db_providers[0].get('default_model', 'auto')}")


if __name__ == "__main__":
    main()
