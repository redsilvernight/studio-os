from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from pydantic import ConfigDict, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import HeartbeatRequest, MachineCapabilities, MachineStatus

from studio_api.db.models.machine import MachineModel
from studio_api.settings import Settings

logger = logging.getLogger(__name__)


class _StoredMachineCapabilities(MachineCapabilities):
    """Persisted capabilities are re-read on every machine listing, so a blob a
    foreign or older writer left behind (AIB R1 is additive) must not raise:
    the known fields are kept, unknown ones are ignored."""

    model_config = ConfigDict(extra="ignore")


_KNOWN_CAPABILITY_FIELDS = frozenset(MachineCapabilities.model_fields)


def parse_stored_capabilities(raw: dict[str, Any] | None) -> MachineCapabilities | None:
    """Parse a persisted `machines.capabilities` blob defensively. An absent,
    unrecognizable or entirely foreign blob yields `None` (treated as "no
    capabilities reported") instead of failing the whole endpoint, so one
    foreign row cannot take down a machine listing shared by every machine."""
    if raw is None or not (_KNOWN_CAPABILITY_FIELDS & raw.keys()):
        return None
    try:
        return _StoredMachineCapabilities.model_validate(raw)
    except ValidationError:
        logger.warning("ignoring unreadable stored machine capabilities", exc_info=True)
        return None


async def record_heartbeat(
    session: AsyncSession, machine: MachineModel, req: HeartbeatRequest, settings: Settings
) -> tuple[MachineModel, datetime]:
    if req.machine_id != machine.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "machine_id_mismatch",
                "message": "machine_id does not match the authenticated machine",
            },
        )
    now = datetime.now(UTC)
    machine.last_seen_at = now
    if req.capabilities is not None:
        machine.capabilities = req.capabilities.model_dump(mode="json")
        machine.capabilities_reported_at = now
    await session.commit()
    await session.refresh(machine)
    return machine, now


def derive_status(machine: MachineModel, settings: Settings) -> MachineStatus:
    """State derived from `last_seen_at` with configurable thresholds
    (TECH/04_AUTH_SYNC_CONTRACT.md) — never a value cached client-side."""
    if machine.last_seen_at is None:
        return MachineStatus.OFFLINE
    age = datetime.now(UTC) - machine.last_seen_at
    if age <= timedelta(seconds=settings.heartbeat_interval_seconds * 1.5):
        return MachineStatus.ONLINE
    if age <= timedelta(seconds=settings.heartbeat_offline_after_seconds):
        return MachineStatus.IDLE
    return MachineStatus.OFFLINE
