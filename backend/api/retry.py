"""Retry policies with exponential backoff for transient failures."""

import logging
import random
import time
from functools import wraps
from typing import Callable, Type, Tuple, Optional

import structlog

logger = structlog.get_logger(__name__)

# Retryable exception types
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    IOError,
)

# Non-retryable exception types (explicit)
NON_RETRYABLE_EXCEPTIONS = (
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
)


class RetryExhausted(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, attempts: int, last_exception: Exception):
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(f"Retry exhausted after {attempts} attempts: {last_exception}")


class RetryPolicy:
    """Configurable retry policy with exponential backoff."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
        non_retryable_exceptions: Tuple[Type[Exception], ...] = NON_RETRYABLE_EXCEPTIONS,
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions
        self.non_retryable_exceptions = non_retryable_exceptions

    def _is_retryable(self, exc: Exception) -> bool:
        """Determine if an exception is retryable."""
        # Non-retryable takes precedence
        if isinstance(exc, self.non_retryable_exceptions):
            return False
        # Check if it's a retryable type
        return isinstance(exc, self.retryable_exceptions)

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and optional jitter."""
        delay = min(self.base_delay * (self.exponential_base ** attempt), self.max_delay)
        if self.jitter:
            delay *= random.uniform(0.5, 1.5)
        return delay

    def execute(self, func: Callable, *args, **kwargs):
        """Execute function with retry policy."""
        last_exception = None

        for attempt in range(self.max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_exception = exc

                if not self._is_retryable(exc):
                    logger.warning(
                        "retry_non_retryable",
                        attempt=attempt + 1,
                        exc_type=type(exc).__name__,
                        exc_message=str(exc),
                    )
                    raise

                if attempt < self.max_attempts - 1:
                    delay = self._calculate_delay(attempt)
                    logger.warning(
                        "retry_attempt",
                        attempt=attempt + 1,
                        max_attempts=self.max_attempts,
                        delay=round(delay, 2),
                        exc_type=type(exc).__name__,
                        exc_message=str(exc),
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "retry_exhausted",
                        attempts=self.max_attempts,
                        exc_type=type(last_exception).__name__,
                        exc_message=str(last_exception),
                    )

        raise RetryExhausted(self.max_attempts, last_exception)


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
    non_retryable_exceptions: Tuple[Type[Exception], ...] = NON_RETRYABLE_EXCEPTIONS,
):
    """Decorator for adding retry logic to a function."""
    policy = RetryPolicy(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        retryable_exceptions=retryable_exceptions,
        non_retryable_exceptions=non_retryable_exceptions,
    )

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return policy.execute(func, *args, **kwargs)
        return wrapper
    return decorator


# Predefined policies for common use cases
MODAL_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay=1.0,
    max_delay=10.0,
    exponential_base=2.0,
    retryable_exceptions=(ConnectionError, TimeoutError, IOError, RuntimeError),
)

MONGODB_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay=0.5,
    max_delay=5.0,
    exponential_base=2.0,
    retryable_exceptions=(ConnectionError, TimeoutError, IOError),
)

REDIS_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay=0.1,
    max_delay=1.0,
    exponential_base=2.0,
    retryable_exceptions=(ConnectionError, TimeoutError, IOError),
)