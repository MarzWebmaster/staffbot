"""
Admin policy router — skills, toolsets, governance policy.
Stored locally as Setting key-value (JSON blobs).
"""
import json
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.models.client import Client
from app.models.setting import Setting
from app.middleware.auth import get_current_admin

router = APIRouter()


# ── Default/static data ────────────────────────────────────────────

DEFAULT_SKILLS = [
    {"id": "web-search", "name": "Web Search", "desc": "Search the web via DuckDuckGo", "category": "web", "enabled": True},
    {"id": "terminal", "name": "Terminal", "desc": "Execute shell commands", "category": "system", "enabled": True},
    {"id": "file-ops", "name": "File Operations", "desc": "Read, write, search files", "category": "system", "enabled": True},
    {"id": "code-exec", "name": "Code Execution", "desc": "Execute Python scripts", "category": "development", "enabled": True},
    {"id": "image-gen", "name": "Image Generation", "desc": "Generate images via AI", "category": "creative", "enabled": True},
    {"id": "memory", "name": "Memory", "desc": "Persistent cross-session memory", "category": "system", "enabled": True},
    {"id": "vision", "name": "Vision", "desc": "Analyze images", "category": "ai", "enabled": True},
    {"id": "browser", "name": "Browser", "desc": "Navigate and interact with web pages", "category": "web", "enabled": True},
]

DEFAULT_TOOLS = [
    {"id": "terminal", "name": "Terminal", "desc": "Execute shell commands on the system", "risk": "high", "enabled": True},
    {"id": "file_system", "name": "File System", "desc": "Read, write, and manage files", "risk": "medium", "enabled": True},
    {"id": "web_search", "name": "Web Search", "desc": "Search the internet", "risk": "low", "enabled": True},
    {"id": "code_execution", "name": "Code Execution", "desc": "Run isolated code", "risk": "high", "enabled": True},
    {"id": "image_generation", "name": "Image Generation", "desc": "Generate images", "risk": "low", "enabled": False},
    {"id": "browser_automation", "name": "Browser Automation", "desc": "Control a headless browser", "risk": "medium", "enabled": True},
    {"id": "memory_access", "name": "Memory Access", "desc": "Read/write persistent memory", "risk": "medium", "enabled": True},
]

DEFAULT_POLICY = {
    "general_restrictions": [
        "Do not share sensitive user information",
        "Do not execute destructive system commands",
        "Do not impersonate users or make decisions on their behalf",
    ],
    "content_filtering": {
        "filter_strength": "medium",
        "prompt_injection_protection": True,
        "jailbreak_detection": True,
        "blocked_categories": ["hate_speech", "violence", "sexual_content", "self_harm"],
    },
    "action_restrictions": {
        "allowed_actions": ["web_search", "read_file", "code_analysis", "image_generation", "summarize", "translate"],
        "approval_required": ["write_file", "send_email", "delete_file", "install_package", "modify_system"],
        "blocked_actions": ["delete_system_file", "modify_user_database", "send_spam", "execute_unknown_binary", "change_permissions"],
    },
    "data_governance": {
        "retention_days": 90,
        "audit_retention_days": 365,
        "auto_purge_after_expiry": True,
    },
    "rate_limits": {
        "max_requests_per_minute": 30,
        "max_tokens_per_hour": 500000,
        "max_concurrent_tasks": 3,
        "cooldown_after_violation_seconds": 300,
    },
    "monitoring": {
        "log_all_actions": True,
        "log_approval_requests": True,
        "alert_on_violation": True,
        "violation_threshold_before_suspension": 5,
    },
}


# ── Helpers ────────────────────────────────────────────────────────

async def _get_setting(db: AsyncSession, key: str) -> Optional[str]:
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else None


async def _set_setting(db: AsyncSession, key: str, value: str, admin: Client):
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        setting = Setting(key=key, value=value, encrypted=False)
        db.add(setting)
    await db.commit()


def _parse_json(raw: Optional[str], default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


# ── Skills ─────────────────────────────────────────────────────────

@router.get("/skills")
async def get_skills(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    raw = await _get_setting(db, "policy_skills")
    skills = _parse_json(raw, DEFAULT_SKILLS)
    enabled_count = sum(1 for s in skills if s.get("enabled"))
    return {"skills": skills, "enabled": enabled_count}


@router.put("/skills")
async def save_skills(
    data: dict,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    # Support: full array replacement OR just enabled_ids
    if "skills" in data:
        skills = data["skills"]
    else:
        enabled_ids = data.get("enabled_skills", [])
        raw = await _get_setting(db, "policy_skills")
        skills = _parse_json(raw, DEFAULT_SKILLS)
        for skill in skills:
            skill["enabled"] = skill["id"] in enabled_ids
    await _set_setting(db, "policy_skills", json.dumps(skills), admin)
    enabled_count = sum(1 for s in skills if s.get("enabled"))
    return {"message": f"Skills updated", "enabled": enabled_count, "skills": skills}


# ── Toolsets ───────────────────────────────────────────────────────

@router.get("/tools")
async def get_tools(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    raw = await _get_setting(db, "policy_tools")
    tools = _parse_json(raw, DEFAULT_TOOLS)
    enabled_count = sum(1 for t in tools if t.get("enabled"))
    return {"toolsets": tools, "enabled": enabled_count}


@router.put("/tools")
async def save_tools(
    data: dict,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    # Support: full array replacement OR just enabled_ids
    if "toolsets" in data:
        tools = data["toolsets"]
    else:
        enabled_ids = data.get("enabled_tools", [])
        raw = await _get_setting(db, "policy_tools")
        tools = _parse_json(raw, DEFAULT_TOOLS)
        for tool in tools:
            tool["enabled"] = tool["id"] in enabled_ids
    await _set_setting(db, "policy_tools", json.dumps(tools), admin)
    enabled_count = sum(1 for t in tools if t.get("enabled"))
    return {"message": f"Tools updated", "enabled": enabled_count, "toolsets": tools}


# ── Governance Policy ──────────────────────────────────────────────

@router.get("/policy")
async def get_policy(
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    raw = await _get_setting(db, "policy_data")
    return _parse_json(raw, DEFAULT_POLICY)


@router.put("/policy")
async def save_policy(
    data: dict,
    admin: Client = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    await _set_setting(db, "policy_data", json.dumps(data), admin)
    return {"message": "Governance policy saved"}
