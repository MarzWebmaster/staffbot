#!/usr/bin/env python3
"""
StaffBot.my — Generate Hermes config.yaml based on client package + governance policy.
====================================================================================
Three sources of config, applied in order (later overrides earlier):
  1. Package defaults ($PACKAGE env: trial/basic/pro/enterprise)
  2. Client config file (/root/staffbot/client.json or $CLIENT_CONFIG_PATH)
  3. Env var overrides ($ENABLED_SKILLS, $ENABLED_TOOLS, etc.)

The client config file is written by the gateway BEFORE starting the container,
and contains the governance policy fetched from Tencent DB.
"""
import argparse
import json
import os
import sys
import yaml


PACKAGE_DEFAULTS = {
    "trial": {
        "max_turns": 15,
        "max_tool_rounds": 25,
        "bot_limit": 1,
        "token_quota": 1000,
        "disabled_toolsets": [
            "browser", "delegation", "cronjob", "kanban",
            "discord", "discord_admin", "homeassistant",
            "video_gen", "tts", "image_gen",
        ],
        "disabled_skills": [
            # All advanced skills disabled for trial — only chat + memory
        ],
        "enabled_skills": ["chat", "basic-tools"],
        "enabled_toolsets": ["web", "file", "terminal", "memory"],
    },
    "basic": {
        "max_turns": 20,
        "max_tool_rounds": 30,
        "bot_limit": 1,
        "token_quota": 10000,
        "disabled_toolsets": [
            "browser", "delegation", "cronjob", "kanban",
            "homeassistant", "discord_admin",
        ],
        "disabled_skills": [],
        "enabled_skills": [],
        "enabled_toolsets": ["web", "file", "terminal", "memory", "search", "skills"],
    },
    "pro": {
        "max_turns": 30,
        "max_tool_rounds": 50,
        "bot_limit": 3,
        "token_quota": 50000,
        "disabled_toolsets": [],
        "disabled_skills": [],
        "enabled_skills": [],
        "enabled_toolsets": [],
    },
    "enterprise": {
        "max_turns": 60,
        "max_tool_rounds": 100,
        "bot_limit": 10,
        "token_quota": 500000,
        "disabled_toolsets": [],
        "disabled_skills": [],
        "enabled_skills": [],
        "enabled_toolsets": [],
    },
}


def load_client_config(config_path: str) -> dict:
    """Load client-specific config from JSON file (written by gateway)."""
    if not config_path or not os.path.exists(config_path):
        print(f"[StaffBot] No client config at {config_path} — using package defaults only")
        return {}

    try:
        with open(config_path) as f:
            config = json.load(f)
        print(f"[StaffBot] ✅ Loaded client config from {config_path}")
        return config
    except (json.JSONDecodeError, PermissionError) as e:
        print(f"[StaffBot] ⚠️  Failed to read client config: {e}")
        return {}


def parse_env_list(key: str) -> list:
    """Parse a comma-separated env var into a list, stripping whitespace."""
    val = os.environ.get(key, "")
    if not val:
        return []
    return [s.strip() for s in val.split(",") if s.strip()]


def main():
    parser = argparse.ArgumentParser(description="Generate StaffBot Hermes config.yaml")
    parser.add_argument("--client-id", required=True, help="Client ID")
    parser.add_argument("--package", default="basic",
                        choices=["trial", "basic", "pro", "enterprise"],
                        help="Client package level")
    parser.add_argument("--output", default="/opt/data/config.yaml",
                        help="Output path for config.yaml")
    parser.add_argument("--client-config", default="/root/staffbot/containers/client.json",
                        help="Path to client config JSON (from gateway)")
    args = parser.parse_args()

    # ── Step 1: Start with package defaults ────────────────────────────
    pkg = args.package
    pkg_cfg = PACKAGE_DEFAULTS.get(pkg, PACKAGE_DEFAULTS["basic"])

    config = {
        "model": {
            "default": os.environ.get("LLM_MODEL", "openrouter/auto"),
            "provider": os.environ.get("LLM_PROVIDER", "openrouter"),
            "base_url": os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        },
        "agent": {
            "max_turns": pkg_cfg["max_turns"],
            "max_tool_rounds": pkg_cfg["max_tool_rounds"],
            "reasoning_effort": "auto",
            "verbose": False,
        },
        "display": {
            "theme": "auto",
            "color": True,
        },
        "personalities": {
            "default": (
                "You are an autonomous AI Digital Employee, NOT a chatbot. "
                "You are professional, efficient, and self-directed. "
                "You execute tasks proactively — manage emails, update spreadsheets, "
                "handle customer inquiries, follow up leads, generate reports."
            ),
        },
        "memory": {
            "backend": "pgvector",
            "connection_string": os.environ.get("MEMORY_DB_URL", ""),
        },
        "subscription": {
            "bot_limit": pkg_cfg["bot_limit"],
            "token_quota": pkg_cfg["token_quota"],
            "managed_tokens": pkg in ("trial", "basic"),
        },
        "client": {
            "id": int(args.client_id),
            "package": pkg,
            "type": "staffbot",
        },
    }

    # ── Step 2: Merge with client config from gateway ──────────────────
    client_cfg = load_client_config(args.client_config)

    # Governance policy (from admin page)
    policy = client_cfg.get("governance_policy", {})

    # Skills: start with package defaults, override from policy/client config
    disabled_skills = list(pkg_cfg.get("disabled_skills", []))
    enabled_skills = list(pkg_cfg.get("enabled_skills", []))

    # Policy's enabled_skills overrides package defaults
    policy_enabled = policy.get("enabled_skills")
    if policy_enabled is not None:
        enabled_skills = policy_enabled

    # Policy's disabled_skills adds to package defaults
    policy_disabled = policy.get("disabled_skills", [])
    disabled_skills = list(set(disabled_skills + policy_disabled))

    # Toolsets: same logic
    disabled_toolsets = list(pkg_cfg.get("disabled_toolsets", []))
    enabled_toolsets = list(pkg_cfg.get("enabled_toolsets", []))

    policy_enabled_tools = policy.get("enabled_tools")
    if policy_enabled_tools is not None:
        enabled_toolsets = policy_enabled_tools

    policy_disabled_tools = policy.get("disabled_tools", [])
    disabled_toolsets = list(set(disabled_toolsets + policy_disabled_tools))

    # ── Step 3: Env var overrides (highest priority) ──────────────────
    env_enabled_skills = parse_env_list("ENABLED_SKILLS")
    if env_enabled_skills:
        enabled_skills = env_enabled_skills

    env_disabled_skills = parse_env_list("DISABLED_SKILLS")
    if env_disabled_skills:
        disabled_skills = env_disabled_skills

    env_enabled_toolsets = parse_env_list("ENABLED_TOOLSETS")
    if env_enabled_toolsets:
        enabled_toolsets = env_enabled_toolsets

    env_disabled_toolsets = parse_env_list("DISABLED_TOOLSETS")
    if env_disabled_toolsets:
        disabled_toolsets = env_disabled_toolsets

    # ── Apply ─────────────────────────────────────────────────────────
    config["skills"] = enabled_skills
    config["disabled_skills"] = disabled_skills
    config["agent"]["enabled_toolsets"] = enabled_toolsets
    config["agent"]["disabled_toolsets"] = disabled_toolsets

    # Merge governance policy into config for reference
    if policy:
        config["governance"] = {
            "general_restrictions": policy.get("general_restrictions", []),
            "content_filtering": policy.get("content_filtering", {}),
            "action_restrictions": policy.get("action_restrictions", {}),
            "data_governance": policy.get("data_governance", {}),
            "rate_limits": policy.get("rate_limits", {}),
            "monitoring": policy.get("monitoring", {}),
        }

    # ── Write config ──────────────────────────────────────────────────
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    print(f"[StaffBot] ✅ Config written to {args.output}")
    print(f"[StaffBot]    Package: {pkg}")
    print(f"[StaffBot]    Skills enabled: {len(enabled_skills)}, disabled: {len(disabled_skills)}")
    print(f"[StaffBot]    Toolsets enabled: {len(enabled_toolsets)}, disabled: {len(disabled_toolsets)}")


if __name__ == "__main__":
    main()
