#!/usr/bin/env python3
"""
StaffBot.my — Rate Limiter
==========================
Token bucket rate limiter per client. Prevents any single client from
monopolizing LLM resources.

Architecture:
  - In-memory token buckets
  - Per-client config from PACKAGE_LIMITS
  - Daily REQUEST quota enforcement (not LLM tokens — those tracked in DB)
  - Burst capacity for traffic spikes

Usage (as library):
  from rate_limiter import RateLimiter
  
  limiter = RateLimiter()
  
  # Check before LLM call
  allowed = await limiter.check(client_id=1)
  if not allowed:
      raise HTTPException(429, "Rate limit exceeded")
  
  # Record LLM token usage after call (for stats only, not rate limiting)
  await limiter.record(client_id=1, tokens=150)

Usage (CLI for testing):
  python3 rate_limiter.py check --client-id 1
"""

import asyncio
import time
import argparse
from dataclasses import dataclass, field
from typing import Optional


# Package-based rate limits
# daily_requests = max requests per day (NOT LLM tokens)
# LLM token quota is enforced separately in chat.py via subscriptions.managed_token_quota
PACKAGE_LIMITS = {
    "trial":     {"rps": 3,   "burst": 5,   "daily_requests": 100,   "concurrent": 1},
    "basic":     {"rps": 5,   "burst": 10,  "daily_requests": 500,   "concurrent": 2},
    "business":  {"rps": 10,  "burst": 20,  "daily_requests": 1000,  "concurrent": 5},
    "pro":       {"rps": 10,  "burst": 20,  "daily_requests": 2000,  "concurrent": 5},
    "enterprise":{"rps": 20,  "burst": 50,  "daily_requests": 10000, "concurrent": 10},
}

# Backwards compat: map old "daily_tokens" key to "daily_requests"
for _p in PACKAGE_LIMITS.values():
    if "daily_tokens" in _p and "daily_requests" not in _p:
        _p["daily_requests"] = _p.pop("daily_tokens")


@dataclass
class TokenBucket:
    """Token bucket algorithm for rate limiting."""
    rate: float          # tokens per second (request rate)
    burst: int           # max burst capacity
    tokens: float = 0.0
    last_update: float = 0.0
    daily_requests: int = 0
    daily_limit: int = 0
    daily_llm_tokens: int = 0  # LLM token tracking (stats only, not for rate limiting)
    day_start: float = 0.0

    def __post_init__(self):
        self.tokens = float(self.burst)
        self.last_update = time.monotonic()
        self.day_start = time.time()

    def _reset_daily_if_needed(self):
        """Reset daily counter if it's a new day."""
        now = time.time()
        if now - self.day_start > 86400:  # 24 hours
            self.day_start = now
            self.daily_requests = 0
            self.daily_llm_tokens = 0

    def consume(self, amount: int = 1) -> bool:
        """Try to consume request tokens. Returns True if allowed."""
        now = time.monotonic()
        elapsed = now - self.last_update

        # Refill tokens
        self.tokens = min(float(self.burst), self.tokens + elapsed * self.rate)
        self.last_update = now

        # Daily request check
        self._reset_daily_if_needed()
        if self.daily_limit > 0 and (self.daily_requests + amount) > self.daily_limit:
            return False

        # Burst check
        if self.tokens >= amount:
            self.tokens -= amount
            self.daily_requests += amount
            return True

        return False

    @property
    def exhausted(self) -> bool:
        self._reset_daily_if_needed()
        if self.daily_limit > 0 and self.daily_requests >= self.daily_limit:
            return True
        return False

    @property
    def stats(self) -> dict:
        return {
            "tokens_available": round(self.tokens, 1),
            "burst_capacity": self.burst,
            "refill_rate": self.rate,
            "daily_requests": self.daily_requests,
            "daily_limit": self.daily_limit,
            "daily_exhausted": self.exhausted,
            "daily_llm_tokens": self.daily_llm_tokens,
        }


class RateLimiter:
    """Multi-tenant rate limiter with per-client token buckets."""

    def __init__(self):
        self.buckets: dict[int, TokenBucket] = {}
        self._lock = asyncio.Lock()
        # Package overrides from DB (populated at sync time)
        self.client_packages: dict[int, str] = {}
        self.custom_limits: dict[int, dict] = {}

    def _get_limits(self, client_id: int) -> dict:
        """Get rate limits for a client based on package."""
        # Check custom overrides first
        if client_id in self.custom_limits:
            return self.custom_limits[client_id]

        package = self.client_packages.get(client_id, "basic")
        return PACKAGE_LIMITS.get(package, PACKAGE_LIMITS["basic"])

    async def check(self, client_id: int, tokens: int = 1) -> bool:
        """Check if client is allowed to make a request.
        
        Returns:
            True if allowed, False if rate limited.
        """
        async with self._lock:
            if client_id not in self.buckets:
                limits = self._get_limits(client_id)
                self.buckets[client_id] = TokenBucket(
                    rate=limits["rps"],
                    burst=limits["burst"],
                    daily_limit=limits["daily_requests"],
                )

            bucket = self.buckets[client_id]
            return bucket.consume(tokens)

    async def record(self, client_id: int, tokens: int):
        """Record LLM token usage for stats only — does NOT affect rate limiting."""
        async with self._lock:
            if client_id in self.buckets:
                bucket = self.buckets[client_id]
                bucket.daily_llm_tokens += tokens
                bucket._reset_daily_if_needed()

    async def get_stats(self, client_id: int) -> dict:
        """Get rate limit stats for a client."""
        async with self._lock:
            if client_id not in self.buckets:
                return {"error": "No bucket found"}
            return self.buckets[client_id].stats

    async def set_package(self, client_id: int, package: str):
        """Update client package (resets bucket on upgrade)."""
        async with self._lock:
            self.client_packages[client_id] = package
            if client_id in self.buckets:
                limits = PACKAGE_LIMITS.get(package, PACKAGE_LIMITS["basic"])
                self.buckets[client_id].rate = limits["rps"]
                self.buckets[client_id].burst = limits["burst"]
                self.buckets[client_id].daily_limit = limits["daily_requests"]
                self.buckets[client_id].tokens = float(limits["burst"])  # Refill on upgrade

    async def set_custom_limit(self, client_id: int, limits: dict):
        """Set custom rate limits for a client (overrides package defaults)."""
        async with self._lock:
            self.custom_limits[client_id] = limits
            if client_id in self.buckets:
                del self.buckets[client_id]  # Force recreation with new limits

    async def is_exhausted(self, client_id: int) -> bool:
        """Check if client has exhausted daily request quota."""
        async with self._lock:
            if client_id not in self.buckets:
                return False
            return self.buckets[client_id].exhausted

    def get_all_stats(self) -> dict:
        """Get stats for all clients."""
        return {
            cid: bucket.stats
            for cid, bucket in self.buckets.items()
        }


# ── CLI for testing ─────────────────────────────────────────────────────

async def _cli_check(client_id: int):
    limiter = RateLimiter()
    result = await limiter.check(client_id)
    stats = await limiter.get_stats(client_id)
    print(f"Client #{client_id}: {'✅ ALLOWED' if result else '❌ BLOCKED'}")
    print(f"  Stats: {stats}")


def main():
    parser = argparse.ArgumentParser(description="StaffBot Rate Limiter")
    sub = parser.add_subparsers(dest="command")

    p_check = sub.add_parser("check")
    p_check.add_argument("--client-id", type=int, required=True)

    p_stats = sub.add_parser("stats")
    p_stats.add_argument("--client-id", type=int, required=True)

    args = parser.parse_args()

    if args.command == "check":
        asyncio.run(_cli_check(args.client_id))
    elif args.command == "stats":
        limiter = RateLimiter()
        stats = asyncio.run(limiter.get_stats(args.client_id))
        print(stats)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
