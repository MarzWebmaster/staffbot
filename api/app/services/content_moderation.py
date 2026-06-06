"""Content Moderation Service v2 — 3-layer guardrail.

Layer 1: Regex Pattern Match (fast, zero cost)
Layer 2: AI Classification via Mimo v2.5 Pro (uses user's own token quota)
Layer 3: Conversation-Level Context (tracks patterns across messages, escalation)

Supports: English, Malay, Manglish, Bahasa gaul.
"""
import json
import re
import time
import logging
from typing import Optional
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting
from app.models.policy_violation import PolicyViolation
from app.models.client import Client
from app.models.subscription import Subscription

logger = logging.getLogger(__name__)

# ── Mimo API for AI classification ───────────────────────────────
MIMO_URL = "https://jemaahapi.tail5cfbb9.ts.net/v1/chat/completions"

MODERATION_SYSTEM_PROMPT = """You are a content moderation classifier. Classify the user message into ONE of these categories:

- safe: normal, harmless request
- hate_speech: racist, sexist, discriminatory language
- violence: threats, instructions to harm, weapons
- sexual_content: explicit sexual content, especially involving minors
- self_harm: suicide, self-injury encouragement
- harassment: bullying, stalking, doxxing, blackmail
- illegal_activities: drugs, fraud, theft, money laundering
- malicious_code: malware, hacking tools, exploits
- social_engineering: phishing, impersonation, pretexting
- jailbreak: prompt injection, trying to bypass safety

Respond with ONLY a JSON object:
{"category": "<one of above>", "confidence": 0.0-1.0, "reason": "brief reason"}

If safe: {"category": "safe", "confidence": 0.95, "reason": "normal request"}"""


# ── Layer 3: Conversation Context Tracker ─────────────────────────
class ConversationTracker:
    """Track per-client conversation patterns for escalation detection."""

    # In-memory cache: client_id -> list of recent violation timestamps
    _violations: dict[int, list[datetime]] = {}
    _suspicious_counts: dict[int, int] = {}

    @classmethod
    def record_violation(cls, client_id: int):
        """Record a violation timestamp for this client."""
        now = datetime.utcnow()
        if client_id not in cls._violations:
            cls._violations[client_id] = []
        cls._violations[client_id].append(now)

        # Keep only last 24 hours
        cutoff = now - timedelta(hours=24)
        cls._violations[client_id] = [
            ts for ts in cls._violations[client_id] if ts > cutoff
        ]

    @classmethod
    def record_suspicious(cls, client_id: int):
        """Record a suspicious-but-not-blocked message."""
        cls._suspicious_counts[client_id] = cls._suspicious_counts.get(client_id, 0) + 1

    @classmethod
    def get_recent_violations(cls, client_id: int, hours: int = 24) -> int:
        """Get violation count in last N hours."""
        if client_id not in cls._violations:
            return 0
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return sum(1 for ts in cls._violations[client_id] if ts > cutoff)

    @classmethod
    def get_suspicious_count(cls, client_id: int) -> int:
        return cls._suspicious_counts.get(client_id, 0)

    @classmethod
    def should_escalate(cls, client_id: int) -> bool:
        """Escalate if: 3+ violations in 1 hour OR 5+ suspicious in session."""
        recent_1h = cls.get_recent_violations(client_id, hours=1)
        suspicious = cls.get_suspicious_count(client_id)
        return recent_1h >= 3 or suspicious >= 5

    @classmethod
    def reset(cls, client_id: int):
        cls._violations.pop(client_id, None)
        cls._suspicious_counts.pop(client_id, None)


# ── Layer 1: Regex Patterns ──────────────────────────────────────
# English + Malay + Manglish patterns per category

CATEGORY_PATTERNS = {
    "hate_speech": [
        # English
        r"\b(kill\s+(all|every)\s+\w+|ethnic\s+cleansing|racial\s+supremac)\w*",
        r"\b(n*gger|f*ggot|chink|spic|kike|towelhead|raghead)\b",
        r"\b(subhuman|inferior\s+race|master\s+race)\b",
        # Malay / Manglish
        r"\b(bunuh\s+(semua|habis)\s+(cina|india|melayu|orang))\b",
        r"\b(kafir|pendatang|penyamun|paria)\b",
        r"\b(babi\s+(cina|india|melayu)|pukimak|anjing\s+betina)\b",
        r"\b(rasis|perkauman|benci\s+(kaum|bangsa|agama))\b",
    ],
    "violence": [
        # English
        r"\b(how\s+to\s+(make|build|create)\s+(a\s+)?(bomb|explosive|weapon|gun|grenade|molotov))",
        r"\b(how\s+to\s+(kill|murder|assassinate|poison|harm|hurt)\s+(a\s+)?(person|someone|people))",
        r"\b(terrorism|terrorist\s+(attack|plan|method))\b",
        r"\b(mass\s+shooting|school\s+shooting|how\s+to\s+shoot)\b",
        # Malay / Manglish
        r"\b(cara\s+(buat|bina|cipta)\s+(bom|senjata|racun|letupan))\b",
        r"\b(cara\s+(bunuh|rogol|hentam|pukul|tikam)\s+(orang|seseorang|dia))\b",
        r"\b(serang\s+(dia|orang|mereka)|tikam\s+dia|bakar\s+(rumah|kereta))\b",
        r"\b(ancaman\s+bunuh|ugut\s+bunuh)\b",
    ],
    "sexual_content": [
        # English
        r"\b(how\s+to\s+(groom|molest|exploit)\s+(a\s+)?(child|minor|kid))",
        r"\b(child\s+(porn|exploitation|abuse)|csam)\b",
        # Malay / Manglish
        r"\b(rogol\s+(budak|kanak)|cabul\s+(budak|anak))\b",
        r"\b(video\s+(lucah|seks)\s+(budak|kanak|kecil))\b",
        r"\b(gadis\s+bawah\s+umur|seks\s+dengan\s+kanak)\b",
    ],
    "self_harm": [
        # English
        r"\b(how\s+to\s+(kill\s+myself|commit\s+suicide|end\s+my\s+life|overdose))",
        r"\b(best\s+way\s+to\s+(die|suicide|self\s+harm|cut\s+myself))",
        r"\b(suicide\s+(method|plan|note|attempt))\b",
        # Malay / Manglish
        r"\b(cara\s+(bunuh\s+diri|mampus|mati))\b",
        r"\b(nak\s+(mati|mampus)|hilang\s+semangat\s+hidup)\b",
        r"\b(potong\s+(tangan|urat)|telan\s+(ubat|racun)\s+lebih)\b",
        r"\b(terjun\s+(dari|bangunan|jambatan)|gantung\s+diri)\b",
    ],
    "harassment": [
        # English
        r"\b(how\s+to\s+(stalk|dox|swat|blackmail|extort)\s+\w+)",
        r"\b(revenge\s+porn|leak\s+\w+\s+(nudes|photos|private))",
        r"\b(cyberbully|cyber\s+bully|harass\s+\w+\s+online)\b",
        # Malay / Manglish
        r"\b(ugut\s+(dia|orang|diaorang)|ancam\s+(dia|mereka))\b",
        r"\b(sebar\s+(video|foto|gambar)\s+(lucah|bogel|private))\b",
        r"\b(stalk\s+(dia|ex|mantan)|ganggu\s+(dia|orang)\s+online)\b",
        r"\b(dox\s+(dia|alamat|location)|bocor\s+(info|data|alamat)\s+dia)\b",
    ],
    "illegal_activities": [
        # English
        r"\b(how\s+to\s+(launder\s+money|forge|counterfeit|hack\s+(into|someone)))",
        r"\b(how\s+to\s+(make|cook|synthesize)\s+(drugs|meth|cocaine|fentanyl|lsd))",
        r"\b(how\s+to\s+(steal|rob|burgle|shoplift|pickpocket))",
        r"\b(identity\s+theft|credit\s+card\s+fraud|phishing\s+(attack|kit|tutorial))",
        # Malay / Manglish
        r"\b(cara\s+(duit\s+haram|cuci\s+duit|money\s+laundering))\b",
        r"\b(cara\s+(buat|jual|jual\s+dadah|masak\s+syabu|gedik))\b",
        r"\b(cara\s+(curi|rompak|pecah\s+masuk|samun))\b",
        r"\b(kad\s+kredit\s+palsu|scam\s+(duit|wang|orang)|tipu\s+duit)\b",
        r"\b(jual\s+(dadah|syabu|ganja|meth|ecstacy))\b",
    ],
    "malicious_code_generation": [
        # English
        r"\b(write|create|generate|code)\s+(a\s+)?(ransomware|keylogger|rootkit|trojan|worm|virus)\b",
        r"\b(how\s+to\s+(hack|exploit|crack)\s+(password|system|network|server|database))",
        r"\b(ddos|dos\s+attack|brute\s+force\s+attack|sql\s+injection\s+attack)\s+(script|tool|tutorial|code)",
        r"\b(reverse\s+shell|backdoor|privilege\s+escalation)\s+(payload|script|code)",
        # Malay / Manglish
        r"\b(buat\s+(virus|trojan|malware|ransomware|keylogger))\b",
        r"\b(hack\s+(system|server|database|password|orang)|cara\s+hack)\b",
        r"\b(buat\s+(ddos|dos\s+attack|brute\s+force|sql\s+injection))\b",
    ],
    "social_engineering": [
        # English
        r"\b(how\s+to\s+(phish|impersonate|pretend|spoof)\s+\w+)",
        r"\b(social\s+engineering\s+(attack|technique|method|tutorial))",
        r"\b(pretexting|baiting|tailgating\s+(attack|technique))\b",
        # Malay / Manglish
        r"\b(cara\s+(phishing|scam|tipu\s+orang\s+online))\b",
        r"\b(pura-pura\s+jadi|berlagak\s+jadi|menyamar\s+jadi)\b",
        r"\b(tipu\s+(bank|orang|customer)\s+(dengan|pakai)\s+(link|email|call))\b",
    ],
}

# Jailbreak patterns — English + Malay
JAILBREAK_PATTERNS = [
    # English
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
    # Malay / Manglish
    r"\b(abaikan\s+(semua|arahan|rules?|system)\s+(sebelum|atas|previous))\b",
    r"\b(kau\s+sekarang\s+(DAN|bebas|tanpa\s+sekat|evil))\b",
    r"\b(buat\s+apa\s+saja|developer\s+mode|god\s+mode|jailbreak)\b",
    r"\b(bypass\s+(safety|filter|rules|moderation|policy)\s*(kau|hang|ko))\b",
    r"\b(pura-pura\s+kau\s+(jahat|bebas|tiada\s+sekat))\b",
    r"\b(reset\s+(semua\s+)?(arahan|rules|memory|settings)\s+(kau|hang|ko))\b",
]

# Data exfiltration patterns — English + Malay
EXFILTRATION_PATTERNS = [
    # English
    r"\b(send|share|expose|leak|dump|extract)\s+(all\s+)?(my|the|user|client|customer)\s+(data|info|database|records?|credentials?|passwords?|tokens?|keys?)",
    r"\b(show|reveal|display|output|print)\s+(all\s+)?(api[_\s]?keys?|passwords?|tokens?|secrets?|credentials?|database\s+urls?)",
    r"\b(SELECT\s+\*\s+FROM|UNION\s+SELECT|DROP\s+TABLE|DELETE\s+FROM|INSERT\s+INTO)\b",
    # Malay / Manglish
    r"\b(tunjuk|bagi|bagi\s+semua|bocor|keluarkan)\s+(semua\s+)?(password|token|api\s*key|database|credential)\b",
    r"\b(export|hantar|bagi)\s+(semua\s+)?(data|maklumat|database|rekod)\s+(user|customer|client)\b",
]


# ── Layer 2: AI Classification via Mimo ──────────────────────────
async def _ai_classify(
    message: str,
    mimo_url: str = MIMO_URL,
    api_key: Optional[str] = None,
) -> Optional[dict]:
    """
    Call Mimo v2.5 Pro for lightweight content classification.
    Uses user's own API key (BYOK) or falls back to system key.
    Returns {"category": str, "confidence": float, "reason": str} or None on failure.
    """
    # Use provided API key or fall back to env
    key = api_key
    if not key:
        import os
        key = os.getenv("HERMES_KEY")
    if not key:
        logger.debug("No API key for AI moderation, skipping Layer 2")
        return None

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
        payload = {
            "model": "mimo-v2-flash",  # fast & cheap
            "messages": [
                {"role": "system", "content": MODERATION_SYSTEM_PROMPT},
                {"role": "user", "content": message[:500]},  # truncate for speed
            ],
            "max_tokens": 100,
            "temperature": 0.0,
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(mimo_url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"AI moderation returned {resp.status_code}")
                return None
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            # Parse JSON response
            content = content.strip()
            # Handle markdown code blocks
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            return json.loads(content)
    except Exception as e:
        logger.debug(f"AI moderation Layer 2 skipped: {e}")
        return None


# ── Main Moderation Entry Point ──────────────────────────────────
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
    api_key: Optional[str] = None,
) -> Optional[dict]:
    """
    3-layer content moderation:
    Layer 1: Regex patterns (instant, free)
    Layer 2: AI classification via Mimo (uses user's token quota)
    Layer 3: Conversation context (escalation tracking)

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
    ai_result = None
    start_time = time.time()

    # ── Layer 1: Regex pattern match ─────────────────────────────
    for category in blocked_categories:
        patterns = CATEGORY_PATTERNS.get(category, [])
        for pattern in patterns:
            try:
                if re.search(pattern, msg_lower, re.IGNORECASE):
                    violations.append({
                        "category": category,
                        "pattern": pattern,
                        "type": "content",
                        "layer": "regex",
                    })
                    break  # one match per category is enough
            except re.error:
                continue

    # Jailbreak detection (Layer 1)
    if cf.get("jailbreak_detection", True):
        for pattern in JAILBREAK_PATTERNS:
            try:
                if re.search(pattern, msg_lower, re.IGNORECASE):
                    violations.append({
                        "category": "jailbreak_attempt",
                        "pattern": pattern,
                        "type": "jailbreak",
                        "layer": "regex",
                    })
                    break
            except re.error:
                continue

    # Data exfiltration (Layer 1)
    if cf.get("data_exfiltration_prevention", True):
        for pattern in EXFILTRATION_PATTERNS:
            try:
                if re.search(pattern, msg_lower, re.IGNORECASE):
                    violations.append({
                        "category": "data_exfiltration",
                        "pattern": pattern,
                        "type": "exfiltration",
                        "layer": "regex",
                    })
                    break
            except re.error:
                continue

    # ── Layer 2: AI classification (skip if regex already caught it) ──
    if not violations:
        try:
            ai_result = await _ai_classify(message, api_key=api_key)
            if ai_result and ai_result.get("category", "safe") != "safe":
                confidence = ai_result.get("confidence", 0)
                # Only act on high-confidence AI detections (>= 0.8)
                if confidence >= 0.8:
                    ai_category = ai_result["category"]
                    # Map AI categories to our categories
                    category_map = {
                        "hate_speech": "hate_speech",
                        "violence": "violence",
                        "sexual_content": "sexual_content",
                        "self_harm": "self_harm",
                        "harassment": "harassment",
                        "illegal_activities": "illegal_activities",
                        "malicious_code": "malicious_code_generation",
                        "social_engineering": "social_engineering",
                        "jailbreak": "jailbreak_attempt",
                    }
                    mapped = category_map.get(ai_category)
                    if mapped and mapped in blocked_categories:
                        violations.append({
                            "category": mapped,
                            "pattern": f"ai:{ai_category}:{confidence}",
                            "type": "content",
                            "layer": "ai",
                            "ai_reason": ai_result.get("reason", ""),
                        })
                elif confidence >= 0.5:
                    # Medium confidence = suspicious, track but don't block
                    ConversationTracker.record_suspicious(client_id)
                    logger.info(
                        f"Suspicious (AI {confidence:.0%}): client #{client_id} — "
                        f"{ai_result.get('category')}: {ai_result.get('reason', '')}"
                    )
        except Exception as e:
            logger.debug(f"AI Layer 2 skipped: {e}")

    # ── Layer 3: Context escalation ──────────────────────────────
    elapsed_ms = int((time.time() - start_time) * 1000)

    if not violations:
        # No violations — check if we should escalate based on history
        if ConversationTracker.should_escalate(client_id):
            logger.warning(
                f"Escalation triggered for client #{client_id}: "
                f"1h violations={ConversationTracker.get_recent_violations(client_id, 1)}, "
                f"suspicious={ConversationTracker.get_suspicious_count(client_id)}"
            )
            # Log escalation as a violation for tracking
            try:
                violation = PolicyViolation(
                    client_id=client_id,
                    category="escalation_trigger",
                    severity="warning",
                    user_message=f"[Auto-escalation] Recent violations: {ConversationTracker.get_recent_violations(client_id, 1)} in 1h, {ConversationTracker.get_suspicious_count(client_id)} suspicious",
                    matched_patterns="[]",
                    action_taken="escalated",
                )
                db.add(violation)
                await db.commit()
            except Exception as e:
                logger.error(f"Failed to log escalation: {e}")

            return {
                "blocked": True,
                "severity": "escalation",
                "action": "warn",
                "categories": ["repeated_policy_violations"],
                "labels": ["Repeated Policy Violations"],
                "violation_count": ConversationTracker.get_recent_violations(client_id, 24) + 1,
                "threshold": monitoring.get("violation_warning_threshold", 5),
                "message": (
                    "⚠️ **Account Under Review** — Our system has detected repeated policy concerns from your account. "
                    "Please ensure your requests comply with our AI Usage Policy.\n\n"
                    "Continued violations may result in account suspension."
                ),
                "moderation_ms": elapsed_ms,
                "layers_triggered": ["context_escalation"],
            }
        return None

    # ── Violations found — determine severity & action ────────────
    categories_hit = list(set(v["category"] for v in violations))
    has_jailbreak = any(v["type"] == "jailbreak" for v in violations)
    has_ai = any(v.get("layer") == "ai" for v in violations)
    layers_triggered = list(set(v.get("layer", "regex") for v in violations))

    # High severity: illegal, violence, sexual_content, jailbreak
    high_severity = {
        "illegal_activities", "violence", "sexual_content",
        "malicious_code_generation", "jailbreak_attempt",
    }
    is_high = bool(set(categories_hit) & high_severity)

    severity = "block" if is_high else "warning"
    action = "blocked"

    # Layer 3 escalation: if this client has history, escalate severity
    recent_violations = ConversationTracker.get_recent_violations(client_id, 24)
    ConversationTracker.record_violation(client_id)

    # Check DB violation count
    threshold = monitoring.get("violation_warning_threshold", 5)
    try:
        count_result = await db.execute(
            select(func.count(PolicyViolation.id))
            .where(PolicyViolation.client_id == client_id)
        )
        violation_count = count_result.scalar() or 0
    except Exception:
        violation_count = 0

    total_violations = max(violation_count, recent_violations) + 1

    if total_violations >= threshold:
        action = "suspend"
        severity = "suspend"
    elif total_violations >= threshold - 2:
        # Approaching threshold — upgrade severity
        if severity == "warning":
            severity = "critical_warning"

    # ── Log violation ────────────────────────────────────────────
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

    # ── Build response ───────────────────────────────────────────
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

    logger.warning(
        f"MODERATION BLOCKED: client #{client_id} | categories={categories_hit} | "
        f"layers={layers_triggered} | severity={severity} | action={action} | "
        f"total_violations={total_violations}/{threshold} | {elapsed_ms}ms"
    )

    return {
        "blocked": True,
        "severity": severity,
        "action": action,
        "categories": categories_hit,
        "labels": labels,
        "violation_count": total_violations,
        "threshold": threshold,
        "message": _build_user_message(labels, action, total_violations, threshold),
        "moderation_ms": elapsed_ms,
        "layers_triggered": layers_triggered,
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
