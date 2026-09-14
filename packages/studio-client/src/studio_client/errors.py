from __future__ import annotations

from typing import Any

import httpx


class StudioApiError(Exception):
    """Base for every error `StudioApiClient` raises. Never leaks the
    `Authorization` header: messages are built only from the parsed error
    body, never from raw request/response headers."""

    def __init__(
        self,
        status_code: int,
        error_code: str | None,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{status_code} {error_code or message}")
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details or {}


class AuthenticationError(StudioApiError):
    """401 — missing, malformed, invalid or revoked machine token. Never
    retryable: retrying a dead credential just wastes the retry budget."""


class ForbiddenError(StudioApiError):
    """403 — authenticated but insufficient role. Never retryable."""


class NotFoundError(StudioApiError):
    """404. Never retryable."""


class ConflictError(StudioApiError):
    """409. Only `error_code == "idempotency_key_in_progress"` is transient
    (another request with the same key is still being processed, per
    `services/api/src/studio_api/services/idempotency.py`); every other 409
    (`version_conflict`, `already_claimed`, `idempotency_key_payload_mismatch`)
    is a business conflict the caller must resolve, never a retry target."""


class QuotaError(StudioApiError):
    """413 `transfer_too_large` / 507 `quota_exceeded`."""

    @property
    def remaining_bytes(self) -> int | None:
        """The server's `quota_exceeded` detail carries `quota_bytes` and
        `consumed_bytes`, never a `remaining_bytes` key directly
        (`services/api/src/studio_api/services/transfers.py`) — computed
        here rather than always returning `None`. Falls back to a literal
        `remaining_bytes` key in case the server ever adds one."""
        value = self.details.get("remaining_bytes")
        if isinstance(value, int | float):
            return int(value)
        quota = self.details.get("quota_bytes")
        consumed = self.details.get("consumed_bytes")
        if isinstance(quota, int | float) and isinstance(consumed, int | float):
            return int(quota) - int(consumed)
        return None


class ServerError(StudioApiError):
    """5xx — transient, retryable."""


class TransportError(StudioApiError):
    """No HTTP response at all: connection failure or timeout. Transient,
    retryable."""

    def __init__(self, message: str) -> None:
        super().__init__(status_code=0, error_code=None, message=message)


class TransferError(Exception):
    """Raised by `TransferClient` for a failure talking directly to
    MinIO/S3 via a presigned URL (never the Studio API, so never a
    `StudioApiError`) — a rejected PUT/GET (expired URL, checksum
    mismatch) or a broken transfer stream."""


_STATUS_TO_ERROR: dict[int, type[StudioApiError]] = {
    401: AuthenticationError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    413: QuotaError,
    507: QuotaError,
}


def parse_error_body(body: object) -> tuple[str | None, str, dict[str, Any]]:
    """Tolerant parse of the server's error envelope. The real shape
    (DEC-0024) is `{"detail": {"error_code": ..., ...}}` — FastAPI always
    wraps `HTTPException.detail`. Also accepts `{"detail": "<message>"}`
    (401/403/404 without an `error_code`) and a flat `{"error_code": ...}`
    in case the server ever stops enveloping. Never raises on an
    unexpected shape."""
    if isinstance(body, dict):
        detail = body.get("detail", body)
        if isinstance(detail, dict):
            error_code = detail.get("error_code")
            message = str(detail.get("message") or error_code or "request failed")
            details = {k: v for k, v in detail.items() if k not in {"error_code", "message"}}
            return (str(error_code) if error_code else None, message, details)
        if isinstance(detail, str):
            return None, detail, {}
    return None, "request failed", {}


def error_from_response(response: httpx.Response) -> StudioApiError:
    try:
        body: object = response.json()
    except ValueError:
        body = None
    error_code, message, details = parse_error_body(body)
    error_cls = _STATUS_TO_ERROR.get(
        response.status_code, ServerError if response.status_code >= 500 else StudioApiError
    )
    return error_cls(response.status_code, error_code, message, details)
