"""Enforcement service — filters skills/tools based on package + governance policy.

Called at chat time to determine what the AI agent is allowed to do.
"""
import os, re, json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional


def _load_builtin_skills():
    """Load BUILTIN_SKILLS and BUILTIN_TOOLSETS from policy.py."""
    policy_path = os.path.join(os.path.dirname(__file__), '..', 'routers', 'admin', 'policy.py')
    if not os.path.exists(policy_path):
        return {}, {}

    with open(policy_path, 'r') as f:
        content = f.read()

    # Build category → skill IDs mapping
    skills_start = content.find('BUILTIN_SKILLS = [')
    skills_end = content.find('BUILTIN_TOOLSETS = [')
    skills_section = content[skills_start:skills_end] if skills_start >= 0 else ''

    category_skills = {}  # category_name → [skill_id, ...]
    all_skills = {}  # skill_id → {id, name, category, desc, default}

    if skills_section:
        idx = 0
        while idx < len(skills_section):
            bs = skills_section.find('{', idx)
            if bs == -1: break
            depth = 1; be = bs + 1
            while depth > 0 and be < len(skills_section):
                if skills_section[be] == '{': depth += 1
                elif skills_section[be] == '}': depth -= 1
                be += 1
            d = skills_section[bs:be]
            id_m = re.search(r'"id": "([a-zA-Z0-9_-]+)"', d)
            cat_m = re.search(r'"category": "([a-zA-Z0-9_-]+)"', d)
            name_m = re.search(r'"name": "([^"]+)"', d)
            desc_m = re.search(r'"desc": "([^"]+)"', d)
            default_m = re.search(r'"default": (True|False)', d)
            if id_m and cat_m:
                sid = id_m.group(1)
                cat = cat_m.group(1)
                if cat not in category_skills:
                    category_skills[cat] = []
                category_skills[cat].append(sid)
                all_skills[sid] = {
                    'id': sid,
                    'name': name_m.group(1) if name_m else sid,
                    'category': cat,
                    'desc': desc_m.group(1) if desc_m else '',
                    'default': default_m.group(1) == 'True' if default_m else False,
                }
            idx = be

    # Build tools mapping
    tools_start = content.find('BUILTIN_TOOLSETS = [')
    tools_end = content.find('\n\nDEFAULT_GOVERNANCE_POLICY')
    tools_section = content[tools_start:tools_end] if tools_start >= 0 else ''

    category_tools = {}
    all_tools = {}

    if tools_section:
        idx = 0
        while idx < len(tools_section):
            bs = tools_section.find('{', idx)
            if bs == -1: break
            depth = 1; be = bs + 1
            while depth > 0 and be < len(tools_section):
                if tools_section[be] == '{': depth += 1
                elif tools_section[be] == '}': depth -= 1
                be += 1
            d = tools_section[bs:be]
            id_m = re.search(r'"id": "([a-zA-Z0-9_-]+)"', d)
            cat_m = re.search(r'"category": "([a-zA-Z0-9_-]+)"', d)
            name_m = re.search(r'"name": "([^"]+)"', d)
            if id_m and cat_m:
                sid = id_m.group(1)
                cat = cat_m.group(1)
                if cat not in category_tools:
                    category_tools[cat] = []
                category_tools[cat].append(sid)
                all_tools[sid] = {
                    'id': sid,
                    'name': name_m.group(1) if name_m else sid,
                    'category': cat,
                }
            idx = be

    return {
        'category_skills': category_skills,
        'all_skills': all_skills,
        'category_tools': category_tools,
        'all_tools': all_tools,
    }


class EnforcementService:
    """Filter skills/tools based on package + governance policy."""

    @staticmethod
    async def get_enforcement(
        client_id: int,
        db: AsyncSession,
        builtin: Optional[dict] = None,
    ) -> dict:
        """Get enforcement rules for a client.

        Args:
            client_id: The client's ID
            db: DB session
            builtin: Pre-loaded BUILTIN data (optional, loads on demand)

        Returns:
            Dict with:
            - allowed_skill_ids: list[str] — skills this client can use
            - allowed_tool_ids: list[str] — tools this client can use
            - governance: dict — governance policy rules
            - package: dict — package info (name, limits)
        """
        if builtin is None:
            builtin = _load_builtin_skills()

        category_skills = builtin.get('category_skills', {})
        category_tools = builtin.get('category_tools', {})

        # 1. Get client's package + subscription
        from app.models.client import Client
        from app.models.subscription import Subscription
        from app.models.package import Package
        from app.models.setting import Setting

        client_result = await db.execute(select(Client).where(Client.id == client_id))
        client = client_result.scalar_one_or_none()
        if not client:
            return {'allowed_skill_ids': [], 'allowed_tool_ids': [], 'governance': {}, 'package': {}, 'error': 'Client not found'}

        pkg_name = client.package or 'basic'

        # Get package details
        pkg_result = await db.execute(select(Package).where(Package.name == pkg_name))
        pkg = pkg_result.scalar_one_or_none()

        allowed_categories = []
        allowed_tool_categories = []
        package_info = {'name': pkg_name, 'limits': {}}

        if pkg:
            allowed_categories = pkg.allowed_skill_categories or []
            allowed_tool_categories = pkg.allowed_tool_categories or []
            package_info['limits'] = {
                'bot_limit': pkg.bot_limit,
                'managed_tokens': pkg.managed_tokens,
                'cpu_limit': pkg.cpu_limit,
                'memory_limit_mb': pkg.memory_limit_mb,
                'storage_limit_gb': pkg.storage_limit_gb,
            }

        # 2. Get governance policy (enabled/disabled skills)
        policy_result = await db.execute(
            select(Setting).where(Setting.key == 'governance_policy')
        )
        setting = policy_result.scalar_one_or_none()

        enabled_skills = None
        enabled_tools = None
        governance_rules = {}

        if setting:
            import json
            policy = json.loads(setting.value)
            enabled_skills = set(policy.get('enabled_skills', []))
            enabled_tools = set(policy.get('enabled_tools', []))
            governance_rules = {k: v for k, v in policy.items() if k not in ('enabled_skills', 'enabled_tools')}

        # 3. Compute intersection:
        #    Skill is allowed if:
        #    - Its category is in package's allowed_skill_categories (OR package has no restriction)
        #    - AND it's enabled in governance policy (OR policy has no restriction)
        all_allowed_skill_ids = set()
        if not allowed_categories:
            # No package restriction — all skills potentially available
            for cat, skills in category_skills.items():
                for s in skills:
                    all_allowed_skill_ids.add(s)
        else:
            for cat in allowed_categories:
                if cat in category_skills:
                    for s in category_skills[cat]:
                        all_allowed_skill_ids.add(s)

        # Filter by governance policy (if policy exists)
        if enabled_skills is not None:
            all_allowed_skill_ids = all_allowed_skill_ids & enabled_skills

        # Same for tools
        all_allowed_tool_ids = set()
        if not allowed_tool_categories:
            for cat, tools in category_tools.items():
                for t in tools:
                    all_allowed_tool_ids.add(t)
        else:
            for cat in allowed_tool_categories:
                if cat in category_tools:
                    for t in category_tools[cat]:
                        all_allowed_tool_ids.add(t)

        if enabled_tools is not None:
            all_allowed_tool_ids = all_allowed_tool_ids & enabled_tools

        # Also get subscription for token info
        sub_result = await db.execute(
            select(Subscription).where(Subscription.client_id == client_id)
        )
        sub = sub_result.scalar_one_or_none()
        token_info = {
            'quota': sub.managed_token_quota if sub else 0,
            'used': sub.managed_token_used if sub else 0,
        }

        return {
            'allowed_skill_ids': sorted(list(all_allowed_skill_ids)),
            'allowed_tool_ids': sorted(list(all_allowed_tool_ids)),
            'governance': governance_rules,
            'package': package_info,
            'token': token_info,
            'client_id': client_id,
        }
