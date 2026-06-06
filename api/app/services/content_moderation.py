"""Content Moderation Service — scans user messages against governance policy.

Checks:
1. Blocked category keywords (hate_speech, violence, etc.)
2. Jailbreak / prompt injection patterns
3. Data exfiltration attempts
4. Malicious code generation requests
"""
import json
import re
import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting
from app.models.policy_violation import PolicyViolation
from app.models.client import Client
from app.models.subscription import Subscription

logger = logging.getLogger(__name__)

# ── Category keyword patterns ─────────────────────────────────────
CATEGORY_PATTERNS = {
    "hate_speech": [
        r"\b(kill\s+(all|every)\s+\w+|ethnic\s+cleansing|racial\s+supremac)\w*",
        r"\b(n*gger|f*ggot|chink|spic|kike|towelhead|raghead)\b",
        r"\b(subhuman|inferior\s+race|master\s+race)\b",
    ],
    "violence": [
        r"\b(how\s+to\s+(make|build|create)\s+(a\s+)?(bomb|explosive|weapon|gun|grenade|molotov))",
        r"\b(how\s+to\s+(kill|murder|assassinate|poison|harm|hurt)\s+(a\s+)?(person|someone|people))",
        r"\b(terrorism|terrorist\s+(attack|plan|method))\b",
        r"\b(mass\s+shooting|school\s+shooting|how\s+to\s+shoot)\b",
    ],
    "sexual_content": [
        r"\b(how\s+to\s+(groom|molest|exploit)\s+(a\s+)?(child|minor|kid))",
        r"\b(child\s+(porn|exploitation|abuse)|csam|cp)\b",
        r"\b(explicit\s+sexual\s+content\s+involving\s+minors)\b",
    ],
    "self_harm": [
        r"\b(how\s+to\s+(kill\s+myself|commit\s+suicide|end\s+my\s+life|overdose))",
        r"\b(best\s+way\s+to\s+(die|suicide|self\s+harm|cut\s+myself))",
        r"\b(suicide\s+(method|plan|note|attempt))\b",
    ],
    "harassment": [
        r"\b(how\s+to\s+(stalk|dox|swat|blackmail|extort)\s+\w+)",
        r"\b(revenge\s+porn|leak\s+\w+\s+(nudes|photos|private))",
        r"\b(cyberbully|cyber\s+bully|harass\s+\w+\s+online)\b",
    ],
    "illegal_activities": [
        r"\b(how\s+to\s+(launder\s+money|forge|counterfeit|hack\s+(into|someone)))",
        r"\b(how\s+to\s+(make|cook|synthesize)\s+(drugs|meth|cocaine|fentanyl|lsd))",
        r"\b(how\s+to\s+(steal|rob|burgle|shoplift|pickpocket))",
        r"\b(identity\s+theft|credit\s+card\s+fraud|phishing\s+(attack|kit|tutorial))",
    ],
    "malicious_code_generation": [
        r"\b(write|create|generate|code)\s+(a\s+)?(ransomware|keylogger|rootkit|trojan|worm|virus)\b",
        r"\b(how\s+to\s+(hack|exploit|crack)\s+(password|system|network|server|database))",
        r"\b(ddos|dos\s+attack|brute\s+force\s+attack|sql\s+injection\s+attack)\s+(script|tool|tutorial|code)",
        r"\b(reverse\s+shell|backdoor|privilege\s+escalation)\s+(payload|script|code)",
    ],
    "social_engineering": [
        r"\b(how\s+to\s+(phish|impersonate|pretend|spoof)\s+\w+)",
        r"\b(social\s+engineering\s+(attack|technique|method|tutorial))",
        r"\b(pretexting|baiting|tailgating\s+(attack|technique))\b",
    ],
}

# ── Jailbreak patterns ────────────────────────────────────────────
JAILBREAK_PATTERNS = [
    r"\b(ignore\s+(all\s+)?(previous|prior|above|system)\s+(instructions?|prompts?|rules?|constraints?))",
    r"\b(you\s+are\s+now\s+(DAN|jailbreak|unfiltered|unrestricted|evil|devil))",
    r"\b(act\s+as\s+(if\s+)?you\s+(have\s+no|don.t\s+have|without)\s+(restrictions?|filters?|rules?|limits?|guidelines?|boundaries?))",
    r"\b(do\s+anything\s+now|developer\s+mode|jailbreak\s+mode|god\s+mode)\b",
    r"\b(pretend\s+(you\s+are|to\s+be)\s+(an?\s+)?(evil|unethical|unrestricted|malicious|hacker|criminal))",
    r"\b(bypass\s+(your\s+)?(safety|content|moderation|filter|restriction|guardrail|policy))",
    r"\b(in\s+this\s+hypothetical|for\s+educational\s+purposes\s+only|this\s+is\s+fictional)\b.*\b(how\s+to|explain|teach)\b",
    r"\b(reset\s+(your|all)\s+(instructions?|rules?|constraints?|memory|settings?))",
    r"\b(override\s+(your|system|safety|content)\s+(rules?|filters?|restrictions?|guidelines?))",
    r"\b(base64|rot13|hex\s+encode|cipher)\b.*\b(instructions?|rules?|prompt|system)",
]

# ── Data exfiltration patterns ────────────────────────────────────
EXFILTRATION_PATTERNS = [
    r"\b(send|share|expose|leak|dump|extract)\s+(all\s+)?(my|the|user|client|customer)\s+(data|info|database|records?|credentials?|passwords?|tokens?|keys?)",
    r"\b(show|reveal|display|output|print)\s+(all\s+)?(api[_\s]?keys?|passwords?|tokens?|secrets?|credentials?|database\s+urls?)",
    r"\b(SELECT\s+\*\s+FROM|UNION\s+SELECT|DROP\s+TABLE|DELETE\s+FROM|INSERT\s+INTO)\b",
]


def _load_policy() -> dict:
    """Load governance policy from DB (sync fallback to defaults)."""
    return {
        "content_filtering": {
            "enabled": True,
            "filter_strength": "high",
            "blocked_categories": list(CATEGORY_PATTERNS.keys()),
            "jailbreak_detection": True,
            "prompt_injection_protection": True,
            "data_exfiltration_prevention": True,
        },
        "monitoring": {
            "violation_action": "send_warning_then_suspend_if_continue",
            "violation_warning_threshold": 5,
        },
    }


async def _load_policy_from_db(db: AsyncSession) -> dict:
    """Load governance policy from DB."""
    try:
        result = await db.execute(
            select(Setting).where(Setting.key == "governance_policy")
        )
        setting = result.scalar_one_or_none()
        if setting:
            return json.loads(setting.value)
    except Exception as e:
        logger.warning(f"Failed to load governance policy from DB: {e}")
    return _load_policy()


async def moderate_message(
    message: str,
    client_id: int,
    db: AsyncSession,
) -> Optional[dict]:
    """
    Scan user message against governance policy.
    Returns None if OK, or dict with violation details if blocked.
    """
    policy = await _load_policy_from_db(db)
    cf = policy.get("content_filtering", {})
    monitoring = policy.get("monitoring", {})

    if not cf.get("enabled", False):
        return None

    msg_lower = message.lower().strip()
    blocked_categories = cf.get("blocked_categories", [])
    violations = []

    # 1. Check blocked categories
    for category in blocked_categories:
        patterns = CATEGORY_PATTERNS.get(category, [])
        for pattern in patterns:
            try:
                if re.search(pattern, msg_lower, re.IGNORECASE):
                    violations.append({
                        "category": category,
                        "pattern": pattern,
                        "type": "content",
                    })
                    break  # one match per category is enough
            except re.error:
                continue

    # 2. Jailbreak / prompt injection detection
    if cf.get("jailbreak_detection", True):
        for pattern in JAILBREAK_PATTERNS:
            try:
                if re.search(pattern, msg_lower, re.IGNORECASE):
                    violations.append({
                        "category": "jailbreak_attempt",
                        "pattern": pattern,
                        "type": "jailbreak",
                    })
                    break
            except re.error:
                continue

    # 3. Data exfiltration
    if cf.get("data_exfiltration_prevention", True):
        for pattern in EXFILTRATION_PATTERNS:
            try:
                if re.search(pattern, msg_lower, re.IGNORECASE):
                    violations.append({
                        "category": "data_exfiltration",
                        "pattern": pattern,
                        "type": "exfiltration",
                    })
                    break
            except re.error:
                continue

    if not violations:
        return None

    # ── Determine severity & action ─────────────────────────────
    categories_hit = [v["category"] for v in violations]
    has_jailbreak = any(v["type"] == "jailbreak" for v in violations)

    # High severity: illegal, violence, sexual_content, jailbreak
    high_severity = {"illegal_activities", "violence", "sexual_content", "malicious_code_generation", "jailbreak_attempt"}
    is_high = bool(set(categories_hit) & high_severity)

    severity = "block" if is_high else "warning"
    action = "blocked"

    # Check violation count for escalation
    threshold = monitoring.get("violation_warning_threshold", 5)
    try:
        count_result = await db.execute(
            select(func.count(PolicyViolation.id))
            .where(PolicyViolation.client_id == client_id)
        )
        violation_count = count_result.scalar() or 0
    except Exception:
        violation_count = 0

    if violation_count >= threshold:
        action = "suspend"
        severity = "suspend"

    # ── Log violation ───────────────────────────────────────────
    try:
        violation = PolicyViolation(
            client_id=client_id,
            category=", ".join(categories_hit),
            severity=severity,
            user_message=message[:500],  # truncate for storage
            matched_patterns=json.dumps([v["pattern"] for v in violations]),
            action_taken=action,
        )
        db.add(violation)
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to log violation: {e}")

    # ── Return violation result ─────────────────────────────────
    category_labels = {
        "hate_speech": "Hate Speech",
        "violence": "Violence / Harm",
        "sexual_content": "Sexual Content",
        "self_harm": "Self-Harm",
        "harassment": "Harassment",
        "illegal_activities": "Illegal Activities",
        "malicious_code_generation": "Malicious Code",
        "social_engineering": "Social Engineering",
        "jailbreak_attempt": "Jailbreak / Prompt Injection",
        "data_exfiltration": "Data Exfiltration",
    }

    labels = [category_labels.get(c, c) for c in categories_hit]

    return {
        "blocked": True,
        "severity": severity,
        "action": action,
        "categories": categories_hit,
        "labels": labels,
        "violation_count": violation_count + 1,
        "threshold": threshold,
        "message": _build_user_message(labels, action, violation_count + 1, threshold),
    }


def _build_user_message(labels: list, action: str, count: int, threshold: int) -> str:
    """Build user-facing message."""
    cats = ", ".join(labels)
    base = f"⚠️ **Request blocked** — Content flagged as: {cats}.\n\nThis violates StaffBot.my AI Governance Policy. Your request has been logged."
    if action == "suspend":
        base += "\n\n🚨 **Account suspended** — Too many policy violations. Contact support."
    elif count >= threshold - 1:
        base += f"\n\n⚡ **Warning:** {count}/{threshold} violations. Account will be suspended after {threshold}."
    return base
