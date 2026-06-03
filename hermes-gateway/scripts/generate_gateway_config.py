#!/usr/bin/env python3
"""
StaffBot.my — Hermes Gateway Config Generator
==============================================
Generates the base Hermes config.yaml for the Gateway.
Client-specific overrides are in per-profile configs.

Three-tier config:
  1. Base (this file) — default for all clients
  2. Package tier — limits by package (trial/basic/pro/enterprise)
  3. Client override — governance policy from admin panel
"""

import argparse
import os
import yaml


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


def generate_base_config() -> dict:
    """Generate the base Hermes Gateway config."""
    return {
        "model": {
            "default": os.environ.get("LLM_MODEL", "deepseek/deepseek-chat"),
            "provider": os.environ.get("LLM_PROVIDER", "openrouter"),
            "base_url": os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
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
        "staffbot": {
            "version": "2.0.0",
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
    args = parser.parse_args()

    if args.client_id:
        config = generate_profile_config(args.client_id, args.package)
    else:
        config = generate_base_config()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    print(f"[StaffBot] ✅ Config written to {args.output}")


if __name__ == "__main__":
    main()
