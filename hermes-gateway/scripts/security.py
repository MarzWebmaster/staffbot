#!/usr/bin/env python3
"""
StaffBot.my — Security Middleware
================================
Multi-tenant security enforcement for Hermes Gateway.

Protection Layers:
  1. Profile boundary — each client can only access their own resources
  2. Content filtering — block harmful/restricted content per governance policy
  3. Action authorization — check if tool/skill is allowed per client
  4. Audit logging — record all actions for compliance
  5. PII redaction — strip sensitive data from logs (delegated to Hermes)
  6. Rate limit enforcement — integrated with rate_limiter.py

Usage:
  from security import SecurityMiddleware
  
  security = SecurityMiddleware(db_url="postgresql://...")
  
  # Check before processing
  await security.enforce(client_id=1, action="llm_call", resource="chat")
  
  # Audit after
  await security.audit(client_id=1, action="llm_call", result="success", tokens=150)
"""

import asyncio
import hashlib
import json
import os
import re
import time
import argparse
from datetime import datetime, timezone
from typing import Optional

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False


class SecurityViolation(Exception):
    """Raised when a security policy is violated."""
    def __init__(self, message: str, client_id: int, action: str):
        self.client_id = client_id
        self.action = action
        super().__init__(f"[SECURITY] Client #{client_id} — {action}: {message}")


class ContentBlockedError(SecurityViolation):
    """Content blocked by governance policy."""
    pass


class CrossProfileAccessError(SecurityViolation):
    """Attempted to access another client's resources."""
    pass


class ActionNotAuthorizedError(SecurityViolation):
    """Action not allowed by governance policy."""
    pass


class SecurityMiddleware:
    """Multi-tenant security enforcement."""

    def __init__(self, db_url: str = ""):
        self.db_url = db_url
        self._policy_cache: dict[int, dict] = {}  # client_id → governance policy
        self._cache_timestamps: dict[int, float] = {}
        self._cache_ttl = 300  # 5 minutes
        self._lock = asyncio.Lock()

    # ── Layer 1: Profile boundary ──────────────────────────────────────

    async def enforce_profile_boundary(self, client_id: int, target_client_id: int):
        """Ensure client can only access their own resources.
        
        Raises CrossProfileAccessError if attempting cross-profile access.
        """
        if target_client_id is not None and client_id != target_client_id:
            raise CrossProfileAccessError(
                f"Cross-profile access denied: #{client_id} → #{target_client_id}",
                client_id, "profile_access"
            )

    async def enforce_resource_owner(self, client_id: int, resource_path: str):
        """Verify that a resource path belongs to this client."""
        # Resource paths should contain client_id marker
        expected_marker = f"client_{client_id}"
        if expected_marker not in resource_path and f"/{client_id}/" not in resource_path:
            # Only enforce if the path looks like a profile resource
            if "client_" in resource_path or "/profiles/" in resource_path:
                raise CrossProfileAccessError(
                    f"Resource '{resource_path}' does not belong to client #{client_id}",
                    client_id, "resource_access"
                )

    # ── Layer 2: Content filtering ────────────────────────────────────

    async def filter_content(self, client_id: int, content: str) -> str:
        """Apply content filters per governance policy.
        
        Returns filtered content (or raises ContentBlockedError).
        """
        policy = await self._get_policy(client_id)
        filters = policy.get("content_filtering", {})

        # Blocked keywords/phrases
        blocked = filters.get("blocked_keywords", [])
        for keyword in blocked:
            if keyword.lower() in content.lower():
                raise ContentBlockedError(
                    f"Content contains blocked keyword: '{keyword}'",
                    client_id, "content_filter"
                )

        # Blocked regex patterns
        patterns = filters.get("blocked_patterns", [])
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                raise ContentBlockedError(
                    f"Content matches blocked pattern",
                    client_id, "content_filter"
                )

        # Max content length
        max_length = filters.get("max_content_length", 50000)
        if len(content) > max_length:
            raise ContentBlockedError(
                f"Content exceeds max length ({max_length} chars)",
                client_id, "content_length"
            )

        return content

    # ── Layer 3: Action authorization ─────────────────────────────────

    async def authorize_action(self, client_id: int, action: str) -> bool:
        """Check if an action is allowed by governance policy.
        
        Returns True if allowed, raises ActionNotAuthorizedError if blocked.
        """
        policy = await self._get_policy(client_id)
        restrictions = policy.get("action_restrictions", {})

        # Check globally blocked actions
        blocked_actions = restrictions.get("blocked_actions", [])
        if action in blocked_actions:
            raise ActionNotAuthorizedError(
                f"Action '{action}' is blocked by governance policy",
                client_id, action
            )

        # Check allowed-only mode
        allowed_actions = restrictions.get("allowed_actions", [])
        if allowed_actions and action not in allowed_actions:
            raise ActionNotAuthorizedError(
                f"Action '{action}' is not in allowed list",
                client_id, action
            )

        return True

    async def authorize_tool(self, client_id: int, tool_name: str) -> bool:
        """Check if a tool is allowed for this client."""
        policy = await self._get_policy(client_id)
        disabled_tools = policy.get("disabled_tools", [])
        enabled_tools = policy.get("enabled_tools", [])

        if tool_name in disabled_tools:
            raise ActionNotAuthorizedError(
                f"Tool '{tool_name}' is disabled for this client",
                client_id, f"tool:{tool_name}"
            )

        if enabled_tools and tool_name not in enabled_tools:
            raise ActionNotAuthorizedError(
                f"Tool '{tool_name}' is not enabled for this client",
                client_id, f"tool:{tool_name}"
            )

        return True

    async def authorize_skill(self, client_id: int, skill_name: str) -> bool:
        """Check if a skill is allowed for this client."""
        policy = await self._get_policy(client_id)
        disabled_skills = policy.get("disabled_skills", [])

        if skill_name in disabled_skills:
            raise ActionNotAuthorizedError(
                f"Skill '{skill_name}' is disabled for this client",
                client_id, f"skill:{skill_name}"
            )

        return True

    # ── Layer 4: Data governance ──────────────────────────────────────

    async def enforce_data_policy(self, client_id: int, data: dict) -> dict:
        """Apply data retention and privacy rules."""
        policy = await self._get_policy(client_id)
        data_gov = policy.get("data_governance", {})

        # Strip fields marked as sensitive
        sensitive_fields = data_gov.get("sensitive_fields", [])
        for field in sensitive_fields:
            if field in data:
                data[field] = "[REDACTED]"

        # Enforce retention
        retention_days = data_gov.get("retention_days", 365)
        data["_retention_days"] = retention_days

        return data

    # ── Layer 5: Audit logging ────────────────────────────────────────

    async def audit(self, client_id: int, action: str, resource: str = "",
                    result: str = "success", details: dict = None):
        """Log action to audit trail."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "client_id": client_id,
            "action": action,
            "resource": resource,
            "result": result,
            "details": details or {},
        }

        # Log to console (structured for log aggregation)
        print(f"[AUDIT] {json.dumps(entry, default=str)}")

        # Log to DB if available
        if self.db_url and HAS_ASYNCPG:
            try:
                await self._audit_to_db(entry)
            except Exception:
                pass  # Don't fail the request if audit logging fails

    async def _audit_to_db(self, entry: dict):
        """Write audit entry to PostgreSQL."""
        conn = await asyncpg.connect(self.db_url)
        try:
            await conn.execute("""
                INSERT INTO audit_log (client_id, timestamp, action, resource, result, details)
                VALUES ($1, NOW(), $2, $3, $4, $5)
            """, entry["client_id"], entry["action"], entry["resource"],
               entry["result"], json.dumps(entry["details"]))
        finally:
            await conn.close()

    # ── Policy management ──────────────────────────────────────────────

    async def _get_policy(self, client_id: int) -> dict:
        """Get governance policy for a client (with cache)."""
        now = time.time()

        # Check cache
        if client_id in self._policy_cache:
            age = now - self._cache_timestamps.get(client_id, 0)
            if age < self._cache_ttl:
                return self._policy_cache[client_id]

        # Load from DB
        policy = await self._load_policy(client_id)
        if policy:
            async with self._lock:
                self._policy_cache[client_id] = policy
                self._cache_timestamps[client_id] = now
                return policy

        return {}  # No policy = default (no restrictions)

    async def _load_policy(self, client_id: int) -> dict:
        """Load governance policy from DB."""
        if not self.db_url or not HAS_ASYNCPG:
            return {}

        try:
            conn = await asyncpg.connect(self.db_url)
            try:
                row = await conn.fetchrow("""
                    SELECT value FROM soul_config
                    WHERE category = 'staffbot.governance' AND key = $1
                """, f"client_{client_id}")
                if row:
                    return json.loads(row["value"])
            finally:
                await conn.close()
        except Exception:
            pass
        return {}

    async def set_policy(self, client_id: int, policy: dict):
        """Update governance policy (and invalidate cache)."""
        async with self._lock:
            self._policy_cache[client_id] = policy
            self._cache_timestamps[client_id] = time.time()

        # Persist to DB
        if self.db_url and HAS_ASYNCPG:
            try:
                conn = await asyncpg.connect(self.db_url)
                try:
                    await conn.execute("""
                        INSERT INTO soul_config (category, key, value, updated_at)
                        VALUES ('staffbot.governance', $1, $2, NOW())
                        ON CONFLICT (category, key) DO UPDATE SET
                            value = EXCLUDED.value,
                            updated_at = NOW()
                    """, f"client_{client_id}", json.dumps(policy))
                finally:
                    await conn.close()
            except Exception:
                pass

    async def invalidate_cache(self, client_id: int = None):
        """Invalidate policy cache (for a client or all)."""
        async with self._lock:
            if client_id:
                self._policy_cache.pop(client_id, None)
                self._cache_timestamps.pop(client_id, None)
            else:
                self._policy_cache.clear()
                self._cache_timestamps.clear()

    # ── Bulk enforcement ───────────────────────────────────────────────

    async def enforce_all(self, client_id: int, action: str, content: str = "",
                          resource: str = "", tool: str = ""):
        """Run all security checks for a request.
        
        Returns True if all checks pass.
        Raises SecurityViolation on any failure.
        """
        # 1. Authorize action
        await self.authorize_action(client_id, action)

        # 2. Filter content
        if content:
            await self.filter_content(client_id, content)

        # 3. Authorize tool if specified
        if tool:
            await self.authorize_tool(client_id, tool)

        # 4. Verify resource ownership
        if resource and "client_" in resource:
            await self.enforce_resource_owner(client_id, resource)

        return True


# ── CLI for testing ─────────────────────────────────────────────────────

async def _cli_test(client_id: int):
    security = SecurityMiddleware()

    print(f"Testing security for client #{client_id}...")

    # Test action authorization
    try:
        await security.authorize_action(client_id, "llm_call")
        print("✅ llm_call authorized")
    except SecurityViolation as e:
        print(f"❌ {e}")

    # Test tool authorization
    try:
        await security.authorize_tool(client_id, "browser")
        print("✅ browser tool authorized")
    except SecurityViolation as e:
        print(f"❌ {e}")

    # Test content filtering
    try:
        result = await security.filter_content(client_id, "Hello, can you help me?")
        print(f"✅ Content passed filter")
    except SecurityViolation as e:
        print(f"❌ {e}")


def main():
    parser = argparse.ArgumentParser(description="StaffBot Security Middleware")
    parser.add_argument("--client-id", type=int, required=True)
    parser.add_argument("--action", default="test")
    parser.add_argument("--db-url", default="")

    args = parser.parse_args()

    security = SecurityMiddleware(db_url=args.db_url)
    asyncio.run(_cli_test(args.client_id))


if __name__ == "__main__":
    main()
