from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import HeartbeatRequest, MachineStatus

from studio_api.db.models.machine import MachineModel
from studio_api.settings import Settings


async def record_heartbeat(
    session: AsyncSession, machine: MachineModel, req: HeartbeatRequest, settings: Settings
) -> tuple[MachineModel, datetime]:
    now = datetime.now(UTC)
    machine.last_seen_at = now
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
