"""Standardized error responses for API v1."""

import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

# Use standard logging for exception handler to avoid structlog kwarg issues
logger = logging.getLogger(__name__)

ERROR_CODES = {
    "VALIDATION_ERROR": "Invalid request data",
    "AUTHENTICATION_FAILED": "Authentication credentials invalid or missing",
    "PERMISSION_DENIED": "Insufficient permissions for this action",
    "NOT_FOUND": "Resource not found",
    "RATE_LIMITED": "Too many requests",
    "IDEMPOTENCY_CONFLICT": "Idempotency key conflict",
    "INFERENCE_UNAVAILABLE": "ML inference service temporarily unavailable",
    "CACHE_UNAVAILABLE": "Cache service temporarily unavailable",
    "INTERNAL_ERROR": "An unexpected error occurred",
}


def custom_exception_handler(exc, context):
    """Transform DRF exceptions into standardized error format."""
    response = exception_handler(exc, context)

    if response is None:
        # Unhandled exception - log and return generic error
        logger.exception(
            "Unhandled exception: %s: %s",
            type(exc).__name__, str(exc),
            extra={
                "view": str(context.get("view")),
                "path": context.get("request").path if context.get("request") else None,
            }
        )
        return Response(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": ERROR_CODES["INTERNAL_ERROR"],
                    "request_id": getattr(context.get("request"), "request_id", None),
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Get request_id from context
    request = context.get("request")
    request_id = getattr(request, "request_id", None) if request else None

    # Map DRF status codes to error codes
    error_code = _map_status_to_code(response.status_code)

    # Build standardized error response
    error_data = {
        "error": {
            "code": error_code,
            "message": ERROR_CODES.get(error_code, "Error"),
            "request_id": request_id,
        }
    }

    # Include validation details if present
    if response.status_code == status.HTTP_400_BAD_REQUEST and isinstance(response.data, dict):
        if "detail" in response.data:
            error_data["error"]["details"] = response.data["detail"]
        elif "error" in response.data:
            error_data["error"]["details"] = response.data["error"]
        else:
            error_data["error"]["details"] = response.data

    response.data = error_data
    return response


def _map_status_to_code(status_code: int) -> str:
    """Map HTTP status code to error code."""
    mapping = {
        400: "VALIDATION_ERROR",
        401: "AUTHENTICATION_FAILED",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        409: "IDEMPOTENCY_CONFLICT",
        429: "RATE_LIMITED",
        502: "INFERENCE_UNAVAILABLE",
        503: "CACHE_UNAVAILABLE",
    }
    return mapping.get(status_code, "INTERNAL_ERROR")


class APIError(Exception):
    """Base API error with code and status."""

    def __init__(self, code: str, message: str = None, status_code: int = 400):
        self.code = code
        self.message = message or ERROR_CODES.get(code, "Error")
        self.status_code = status_code
        super().__init__(self.message)


def error_response(code: str, message: str = None, status_code: int = 400) -> Response:
    """Create a standardized error response."""
    return Response(
        {
            "error": {
                "code": code,
                "message": message or ERROR_CODES.get(code, "Error"),
            }
        },
        status=status_code,
    )