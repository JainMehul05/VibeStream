"""Common utilities and shared code for VibeStream backend."""

# Shared exception classes
class VibeStreamError(Exception):
    """Base exception for VibeStream backend errors."""
    pass


class ValidationError(VibeStreamError):
    """Raised when input validation fails."""
    pass


class NotFoundError(VibeStreamError):
    """Raised when a resource is not found."""
    pass


class AuthenticationError(VibeStreamError):
    """Raised when authentication fails."""
    pass


class AuthorizationError(VibeStreamError):
    """Raised when authorization fails (user lacks permission)."""
    pass


class ExternalServiceError(VibeStreamError):
    """Raised when an external service call fails."""
    pass


# Utility functions
def sanitize_string(value: str, max_length: int = 5000) -> str:
    """Sanitize a string input for safe processing."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


def get_client_ip(request) -> str:
    """Extract client IP from request, handling proxies."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")