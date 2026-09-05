"""Idempotency middleware for deduplicating requests.

Uses Redis to store responses keyed by Idempotency-Key header.
Returns cached response for duplicate requests within TTL window.
"""

import json
from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
from django.http import JsonResponse

import structlog

logger = structlog.get_logger(__name__)

_IDEMPOTENCY_HEADER = "Idempotency-Key"
_IDEMPOTENCY_TTL = 86400  # 24 hours
_CACHE_PREFIX = "idem:"


class IdempotencyMiddleware(MiddlewareMixin):
    """Handle Idempotency-Key header for safe retry semantics.

    Flow:
    1. Check for Idempotency-Key header on mutating methods (POST, PUT, PATCH, DELETE)
    2. If present, look up cached response in Redis
    3. If found, return cached response immediately
    4. If not found, process request normally
    5. Cache successful responses (2xx) for future duplicates
    6. Do not cache error responses (allow retry on failure)
    """

    IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def process_request(self, request):
        if request.method not in self.IDEMPOTENT_METHODS:
            return None

        idem_key = request.META.get(f"HTTP_{_IDEMPOTENCY_HEADER.replace('-', '_').upper()}")
        if not idem_key:
            return None

        # Scope key to user if authenticated
        user_id = "anon"
        if hasattr(request, "user") and request.user.is_authenticated:
            user_id = request.user.username

        cache_key = f"{_CACHE_PREFIX}{user_id}:{idem_key}"

        cached = cache.get(cache_key)
        if cached is not None:
            logger.info("idempotency_hit", key=cache_key, user_id=user_id)
            response_data = json.loads(cached)
            response = JsonResponse(response_data["data"], status=response_data["status"])
            response["X-Idempotency-Replay"] = "true"
            return response

        # Store key on request for process_response to use
        request._idempotency_key = cache_key
        return None

    def process_response(self, request, response):
        cache_key = getattr(request, "_idempotency_key", None)
        if not cache_key:
            return response

        # Only cache successful responses (2xx)
        if 200 <= response.status_code < 300:
            try:
                # Handle streaming responses
                if hasattr(response, "data"):
                    data = response.data
                else:
                    data = response.content.decode("utf-8")
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        data = {"raw": data}

                cached = json.dumps({"data": data, "status": response.status_code})
                cache.set(cache_key, cached, _IDEMPOTENCY_TTL)
                logger.info("idempotency_stored", key=cache_key, status=response.status_code)
            except Exception as e:  # noqa: BLE001
                logger.warning("idempotency_store_failed", key=cache_key, error=str(e))

        return response