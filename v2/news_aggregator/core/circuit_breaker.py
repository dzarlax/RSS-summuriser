"""Circuit breaker pattern for external service calls."""

import time
import asyncio
from enum import Enum
from typing import Optional, Callable, Any, TypeVar
from functools import wraps
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Circuit is open, requests fail immediately
    HALF_OPEN = "half_open"  # Testing if service has recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """
    Circuit breaker implementation for external services.

    Prevents cascading failures by:
    1. OPEN state: Blocks requests after threshold failures
    2. HALF_OPEN: Allows one test request after timeout
    3. CLOSED: Normal operation after successful recovery
    """

    def __init__(
        self,
        failure_threshold: int = 5,  # Open circuit after N failures
        recovery_timeout: float = 60.0,  # Wait N seconds before trying again
        expected_exception: type = Exception,
        name: str = "default"
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            expected_exception: Exception type that counts as failure
            name: Circuit breaker name for logging
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.name = name

        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._state = CircuitState.CLOSED
        self._lock = asyncio.Lock()

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt circuit reset."""
        if self._last_failure_time is None:
            return True
        return (time.time() - self._last_failure_time) >= self.recovery_timeout

    async def _transition_to_open(self):
        """Transition circuit to OPEN state."""
        self._state = CircuitState.OPEN
        self._last_failure_time = time.time()
        logger.warning(
            f"Circuit breaker '{self.name}' opened after {self._failure_count} failures. "
            f"Will reset after {self.recovery_timeout}s"
        )

    async def _transition_to_half_open(self):
        """Transition circuit to HALF_OPEN state for testing."""
        self._state = CircuitState.HALF_OPEN
        logger.info(f"Circuit breaker '{self.name}' transitioned to HALF_OPEN for testing")

    async def _transition_to_closed(self):
        """Transition circuit to CLOSED state (recovered)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        logger.info(f"Circuit breaker '{self.name}' closed - service recovered")

    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to call
            *args: Function positional arguments
            **kwargs: Function keyword arguments

        Returns:
            Function return value

        Raises:
            CircuitBreakerError: If circuit is open
            Exception: If function raises exception
        """
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    await self._transition_to_half_open()
                else:
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' is OPEN. "
                        f"Rejecting request. Try again in {self.recovery_timeout - (time.time() - self._last_failure_time):.1f}s"
                    )

        try:
            result = await func(*args, **kwargs)

            # Success - reset failure count and close circuit if testing
            async with self._lock:
                if self._state == CircuitState.HALF_OPEN:
                    await self._transition_to_closed()
                elif self._state == CircuitState.CLOSED:
                    self._failure_count = 0

            return result

        except self.expected_exception as e:
            async with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.time()

                if self._failure_count >= self.failure_threshold:
                    if self._state == CircuitState.HALF_OPEN:
                        # Failed during test, keep circuit open
                        await self._transition_to_open()
                    elif self._state == CircuitState.CLOSED:
                        # Threshold reached, open circuit
                        await self._transition_to_open()
                else:
                    logger.warning(
                        f"Circuit breaker '{self.name}' failure {self._failure_count}/{self.failure_threshold}: {e}"
                    )

            raise e

    def reset(self):
        """Manually reset circuit breaker to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        logger.info(f"Circuit breaker '{self.name}' manually reset")

    def get_state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            'name': self.name,
            'state': self._state.value,
            'failure_count': self._failure_count,
            'failure_threshold': self.failure_threshold,
            'last_failure_time': self._last_failure_time,
            'recovery_timeout': self.recovery_timeout,
            'will_attempt_reset_at': (
                self._last_failure_time + self.recovery_timeout
                if self._last_failure_time and self._state == CircuitState.OPEN
                else None
            )
        }


def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    expected_exception: type = Exception,
    name: str = "default"
):
    """
    Decorator for circuit breaker protection.

    Usage:
        @circuit_breaker(failure_threshold=3, recovery_timeout=30, name="ai_service")
        async def my_function():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exception=expected_exception,
            name=name or func.__name__
        )

        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await breaker.call(func, *args, **kwargs)

        # Attach circuit breaker to wrapper for access to stats/reset
        wrapper.circuit_breaker = breaker
        return wrapper

    return decorator


# Pre-configured circuit breakers for different services
ai_service_breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60.0,
    expected_exception=Exception,
    name="ai_service"
)

http_service_breaker = CircuitBreaker(
    failure_threshold=10,
    recovery_timeout=30.0,
    expected_exception=Exception,
    name="http_service"
)
