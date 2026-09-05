"""Recommendation caching with Redis.

Provides caching for recommendation pipeline results with
cache key generation, TTL management, and invalidation.
"""

import hashlib
import json
from typing import Any, Optional

from django.conf import settings
from django.core.cache import cache

import structlog

logger = structlog.get_logger(__name__)

# Cache configuration
DEFAULT_TTL = 600  # 10 minutes
CACHE_PREFIX = "rec:"
PIPELINE_VERSION = getattr(settings, "PIPELINE_VERSION", "1")


def _generate_cache_key(
    user_id: str,
    emotion: str,
    genre: Optional[str] = None,
    history: Optional[list] = None,
) -> str:
    """Generate a deterministic cache key for recommendations.

    Key format: rec:{pipeline_version}:{user_id}:{emotion}:{genre}:{history_hash}
    """
    # Normalize inputs
    user_id = user_id or "anon"
    emotion = (emotion or "").strip().lower()
    genre = (genre or "").strip().lower() if genre else "none"

    # Hash history for key (last 10 moods)
    history_str = ""
    if history:
        recent = [str(m).strip().lower() for m in history[-10:] if m]
        history_str = "|".join(recent)

    # Create deterministic key
    key_parts = f"{PIPELINE_VERSION}:{user_id}:{emotion}:{genre}:{history_str}"
    key_hash = hashlib.sha256(key_parts.encode()).hexdigest()[:16]

    return f"{CACHE_PREFIX}{key_hash}"


def get_cached_recommendations(
    user_id: str,
    emotion: str,
    genre: Optional[str] = None,
    history: Optional[list] = None,
) -> Optional[dict]:
    """Retrieve cached recommendations if available.

    Returns cached response dict or None on cache miss/error.
    """
    try:
        key = _generate_cache_key(user_id, emotion, genre, history)
        cached = cache.get(key)
        if cached is not None:
            logger.info("cache_hit", key=key, user_id=user_id, emotion=emotion)
            return json.loads(cached)
        logger.info("cache_miss", key=key, user_id=user_id, emotion=emotion)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("cache_get_failed", user_id=user_id, error=str(e))
        return None


def set_cached_recommendations(
    user_id: str,
    emotion: str,
    response: dict,
    genre: Optional[str] = None,
    history: Optional[list] = None,
    ttl: int = DEFAULT_TTL,
) -> bool:
    """Store recommendations in cache.

    Returns True if cached successfully.
    """
    try:
        key = _generate_cache_key(user_id, emotion, genre, history)
        # Don't cache degraded responses
        if response.get("degraded"):
            logger.debug("cache_skip_degraded", key=key)
            return False

        cache.set(key, json.dumps(response, separators=(",", ":")), ttl)
        logger.info("cache_set", key=key, user_id=user_id, ttl=ttl)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("cache_set_failed", user_id=user_id, error=str(e))
        return False


def invalidate_user_recommendations(user_id: str) -> int:
    """Invalidate all recommendation cache entries for a user.

    Uses SCAN-based iteration to avoid blocking Redis.
    Returns number of keys deleted.
    """
    try:
        pattern = f"{CACHE_PREFIX}*:{user_id}:*"
        # Note: Django's cache doesn't support pattern delete directly
        # We need to use Redis client directly for this
        from django.core.cache import caches
        redis_cache = caches["default"]
        if hasattr(redis_cache, "_cache"):
            client = redis_cache._cache.get_client(write=True)
            deleted = 0
            cursor = 0
            while True:
                cursor, keys = client.scan(cursor, match=pattern, count=100)
                if keys:
                    deleted += client.delete(*keys)
                if cursor == 0:
                    break
            if deleted:
                logger.info("cache_invalidated", user_id=user_id, pattern=pattern, deleted=deleted)
            return deleted
        return 0
    except Exception as e:  # noqa: BLE001
        logger.warning("cache_invalidate_failed", user_id=user_id, error=str(e))
        return 0


def invalidate_all_recommendations() -> int:
    """Invalidate all recommendation cache entries (use with caution).

    Uses SCAN-based iteration to avoid blocking Redis.
    """
    try:
        pattern = f"{CACHE_PREFIX}*"
        from django.core.cache import caches
        redis_cache = caches["default"]
        if hasattr(redis_cache, "_cache"):
            client = redis_cache._cache.get_client(write=True)
            deleted = 0
            cursor = 0
            while True:
                cursor, keys = client.scan(cursor, match=pattern, count=100)
                if keys:
                    deleted += client.delete(*keys)
                if cursor == 0:
                    break
            if deleted:
                logger.warning("cache_all_invalidated", deleted=deleted)
            return deleted
        return 0
    except Exception as e:  # noqa: BLE001
        logger.warning("cache_all_invalidate_failed", error=str(e))
        return 0


def get_cache_stats() -> dict:
    """Get cache statistics for monitoring."""
    try:
        from django.core.cache import caches
        redis_cache = caches["default"]
        if hasattr(redis_cache, "_cache"):
            client = redis_cache._cache.get_client(write=True)
            info = client.info("memory")
            keys = client.dbsize()
            return {
                "connected": True,
                "used_memory_human": info.get("used_memory_human"),
                "used_memory_peak_human": info.get("used_memory_peak_human"),
                "total_keys": keys,
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("cache_stats_failed", error=str(e))
    return {"connected": False}