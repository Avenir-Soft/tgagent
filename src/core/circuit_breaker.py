"""Circuit breaker pattern for external service calls (OpenAI, etc.).

States:
  CLOSED   — normal operation, requests go through
  OPEN     — too many failures, reject immediately
  HALF_OPEN — cooldown expired, allow one probe request

Transitions:
  CLOSED → OPEN:      after ``failure_threshold`` consecutive failures
  OPEN → HALF_OPEN:   after ``recovery_timeout`` seconds
  HALF_OPEN → CLOSED: if probe request succeeds
  HALF_OPEN → OPEN:   if probe request fails
"""

import asyncio
import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is OPEN and rejecting calls."""

    def __init__(self, name: str, retry_after: float):
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{name}' is OPEN — retry after {retry_after:.0f}s"
        )


class CircuitBreaker:
    """Async-safe circuit breaker.

    Usage::

        cb = CircuitBreaker("openai", failure_threshold=5, recovery_timeout=30)

        async with cb:
            result = await openai_call(...)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    async def __aenter__(self):
        await self._before_call()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            await self._on_success()
        else:
            await self._on_failure(exc_val)
        return False  # don't suppress the exception

    async def _before_call(self) -> None:
        current = self.state
        if current == CircuitState.OPEN:
            retry_after = self.recovery_timeout - (time.monotonic() - self._last_failure_time)
            raise CircuitBreakerOpen(self.name, max(retry_after, 0))

        if current == CircuitState.HALF_OPEN:
            async with self._lock:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("Circuit breaker '%s' → CLOSED (recovered)", self.name)
            else:
                self._failure_count = 0

    async def _on_failure(self, exc: BaseException | None) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker '%s' → OPEN (probe failed: %s)",
                    self.name, exc,
                )
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker '%s' → OPEN after %d consecutive failures",
                    self.name, self._failure_count,
                )

    def status(self) -> dict:
        """Return current breaker status for health checks."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


# ── Singleton instances ─────────────────────────────────────────────────────

openai_breaker = CircuitBreaker(
    "openai",
    failure_threshold=5,
    recovery_timeout=30.0,
)
