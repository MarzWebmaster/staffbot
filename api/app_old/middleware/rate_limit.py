from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status, Request
from typing import Callable


class RateLimiter:
    """Simple in-memory rate limiter. No Redis needed for MVP."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[datetime]] = defaultdict(list)

    async def __call__(self, request: Request):
        client_ip = request.client.host if request.client else "unknown"
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=self.window_seconds)

        # Clean old entries
        self._requests[client_ip] = [
            t for t in self._requests[client_ip] if t > cutoff
        ]

        # Check limit
        if len(self._requests[client_ip]) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Max {self.max_requests} requests per {self.window_seconds}s",
            )

        self._requests[client_ip].append(now)


def rate_limit(max_requests: int = 60, window_seconds: int = 60) -> Callable:
    """Factory for rate limiter dependency."""
    return RateLimiter(max_requests=max_requests, window_seconds=window_seconds)
