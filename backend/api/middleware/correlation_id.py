"""Correlation ID middleware for request tracing.

Generates or extracts a request ID and makes it available via
structlog contextvars for structured logging throughout the request lifecycle.
"""

import uuid
from django.utils.deprecation import MiddlewareMixin

import structlog

_REQUEST_ID_HEADER = "X-Request-ID"
_RESPONSE_HEADER = "X-Request-ID"


class CorrelationIdMiddleware(MiddlewareMixin):
    """Attach a correlation ID to each request for distributed tracing.

    - Reads X-Request-ID from incoming headers (for client-generated IDs)
    - Generates a new UUIDv4 if not provided
    - Binds to structlog contextvars for automatic inclusion in all log lines
    - Returns the ID in response header for client-side correlation
    """

    def process_request(self, request):
        request_id = request.META.get(f"HTTP_{_REQUEST_ID_HEADER.replace('-', '_').upper()}")
        if not request_id:
            request_id = uuid.uuid4().hex[:16]
        request.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

    def process_response(self, request, response):
        request_id = getattr(request, "request_id", None)
        if request_id:
            response[_RESPONSE_HEADER] = request_id
        structlog.contextvars.clear_contextvars()
        return response