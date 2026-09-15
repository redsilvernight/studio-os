from __future__ import annotations

import asyncio
import random

from studio_client.errors import ConflictError, ServerError, StudioApiError, TransportError

_RETRYABLE_STATUS = {429}


def is_retryable(error: Exception) -> bool:
    """Whitelist, not a blacklist (DEC-0024): transport failures, timeouts,
    429, 5xx, and the one transient 409 (`idempotency_key_in_progress`).
    Every other `StudioApiError` — including every other 409 — is a
    business error the caller must handle, never a retry target."""
    if isinstance(error, TransportError | ServerError):
        return True
    if isinstance(error, ConflictError):
        return error.error_code == "idempotency_key_in_progress"
    if isinstance(error, StudioApiError):
        return error.status_code in _RETRYABLE_STATUS
    return False


class RetryPolicy:
    """Bounded exponential backoff with jitter. `attempt` is 1-based: the
    first retry (after the first failed try) is `attempt=1`."""

    def __init__(
        self,
        max_attempts: int = 3,
        backoff_initial: float = 0.5,
        backoff_max: float = 20.0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if backoff_initial <= 0 or backoff_max <= 0:
            raise ValueError("backoff bounds must be positive")
        self.max_attempts = max_attempts
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max

    def delay_for(self, attempt: int) -> float:
        base = min(self.backoff_initial * (2.0 ** (attempt - 1)), self.backoff_max)
        return base * (0.5 + random.random() / 2)


async def sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)
