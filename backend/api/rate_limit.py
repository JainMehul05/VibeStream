"""Redis-backed rate limiting with sliding window.

Provides distributed rate limiting across multiple Django instances.
"""

import time
from typing import Optional

from django.conf import settings
from django.core.cache import cache

import structlog

logger = structlog.get_logger(__name__)

# Default rate limits
DEFAULT_LIMITS = {
    "recommendation": {"limit": 30, "window": 60},      # 30/min for recommendations
    "feedback": {"limit": 60, "window": 60},            # 60/min for feedback
    "text_emotion": {"limit": 45, "window": 60},        # 45/min for text emotion
    "auth": {"limit": 10, "window": 300},               # 10/5min for auth endpoints
    "default": {"limit": 100, "window": 60},            # 100/min default
}

RATE_LIMIT_PREFIX = "ratelimit:"


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, limit: int, window: int, retry_after: int):
        self.limit = limit
        self.window = window
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded: {limit} requests per {window}s")


def _get_client_identifier(request) -> str:
    """Get unique identifier for rate limiting."""
    # Prefer authenticated user
    if hasattr(request, "user") and request.user.is_authenticated:
        return f"user:{request.user.username}"

    # Fall back to IP
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR", "unknown")
    return f"ip:{ip}"


def _get_rate_limit_key(identifier: str, endpoint: str) -> str:
    """Generate Redis key for rate limiting."""
    return f"{RATE_LIMIT_PREFIX}{endpoint}:{identifier}"


def check_rate_limit(
    request,
    endpoint: str,
    limit: Optional[int] = None,
    window: Optional[int] = None,
) -> dict:
    """Check and consume rate limit for a request.

    Uses sliding window algorithm with Redis sorted sets.
    Returns dict with limit info and whether allowed.
    """
    # Get limits from config or defaults
    limits = DEFAULT_LIMITS.get(endpoint, DEFAULT_LIMITS["default"])
    limit = limit or limits["limit"]
    window = window or limits["window"]

    identifier = _get_client_identifier(request)
    key = _get_rate_limit_key(identifier, endpoint)
    now = time.time()
    window_start = now - window

    try:
        # Use Redis sorted set for sliding window
        # Score = timestamp, Member = unique request ID
        request_id = f"{now}:{id(request)}"

        pipe = cache._cache.get_client(write=True).pipeline()
        # Remove expired entries
        pipe.zremrangebyscore(key, 0, window_start)
        # Count current requests
        pipe.zcard(key)
        # Add current request
        pipe.zadd(key, {request_id: now})
        # Set expiry on key
        pipe.expire(key, window + 1)
        results = pipe.execute()

        current_count = results[1]  # zcard result

        allowed = current_count < limit
        remaining = max(0, limit - current_count - 1)

        # Get retry_after if limited
        retry_after = 0
        if not allowed:
            # Get oldest entry to calculate when slot frees up
            oldest = cache._cache.get_client(write=True).zrange(key, 0, 0, withscores=True)
            if oldest:
                oldest_time = oldest[0][1]
                retry_after = int(oldest_time + window - now) + 1

        return {
            "allowed": allowed,
            "limit": limit,
            "remaining": remaining,
            "window": window,
            "retry_after": retry_after,
            "identifier": identifier,
        }

    except Exception as e:  # noqa: BLE001
        logger.warning("rate_limit_check_failed", key=key, error=str(e))
        # Fail open - allow request if Redis unavailable
        return {
            "allowed": True,
            "limit": limit,
            "remaining": limit,
            "window": window,
            "retry_after": 0,
            "identifier": identifier,
            "degraded": True,
        }


def get_rate_limit_headers(rate_limit_info: dict) -> dict:
    """Generate rate limit headers for response."""
    return {
        "X-RateLimit-Limit": str(rate_limit_info["limit"]),
        "X-RateLimit-Remaining": str(rate_limit_info["remaining"]),
        "X-RateLimit-Window": str(rate_limit_info["window"]),
    }


class RateLimitMiddleware:
    """Middleware to enforce rate limits on specific endpoints."""

    ENDPOINT_MAP = {
        "/api/v1/music_recommendation/": "recommendation",
        "/api/v1/text_emotion/": "text_emotion",
        "/api/v1/feedback/": "feedback",
        "/api/v1/users/login/": "auth",
        "/api/v1/users/register/": "auth",
        "/api/v1/users/token/refresh/": "auth",
        "/api/v1/users/passkeys/": "auth",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if endpoint is rate limited
        endpoint_type = self.ENDPOINT_MAP.get(request.path)
        if endpoint_type and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            rate_limit_info = check_rate_limit(request, endpoint_type)

            # Add headers to request for view to use
            request.rate_limit_info = rate_limit_info

            if not rate_limit_info["allowed"]:
                from django.http import JsonResponse
                response = JsonResponse(
                    {
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": f"Rate limit exceeded. Try again in {rate_limit_info['retry_after']} seconds.",
                            "retry_after": rate_limit_info["retry_after"],
                        }
                    },
                    status=429,
                )
                for k, v in get_rate_limit_headers(rate_limit_info).items():
                    response[k] = v
                response["Retry-After"] = str(rate_limit_info["retry_after"])
                return response

        response = self.get_response(request)

        # Add rate limit headers to response
        if hasattr(request, "rate_limit_info"):
            for k, v in get_rate_limit_headers(request.rate_limit_info).items():
                response[k] = v

        return response