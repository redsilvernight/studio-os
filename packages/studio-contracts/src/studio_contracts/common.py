from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base for every schema that crosses an API/event/MCP boundary (TECH/02-05_*.md)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class TimestampedModel(ContractModel):
    created_at: datetime
    updated_at: datetime


class VersionedModel(TimestampedModel):
    """Optimistic concurrency per AUTH_SYNC_CONTRACT: version int, 409 + server
    version on a stale write."""

    version: int


class Page[T](ContractModel):
    items: list[T]
    limit: int
    offset: int
    total: int | None = None


# TODO(DEC-0024): unused by any server code today — FastAPI's actual error
# shape is {"detail": {"error_code": ..., ...}} (HTTPException.detail), not
# this flat model. Either wire it as the real response (FastAPI `responses=`
# / a shared exception handler) or remove it — don't let it keep looking
# like the live contract to a future reader.
class ErrorResponse(ContractModel):
    error_code: str
    message: str
    details: dict[str, object] | None = None


class VersionConflictError(ErrorResponse):
    error_code: str = "version_conflict"
    server_version: int
    server_updated_at: datetime


class IdempotentCreate(ContractModel):
    """Marker for creation payloads accepted on a replayable POST. The actual
    idempotency key travels in the `Idempotency-Key` HTTP header, not a body
    field (.claude/rules/contracts.md) — this base carries no field of its own."""
