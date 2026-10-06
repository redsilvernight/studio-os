"""AI integration status contracts (AI Bootstrap P6, additive, read-only).

One project-level view that sets the *desired* state (the aggregated bootstrap
plan, P2) next to what each machine has *reported* (capability report, R1).
Every reported value is labelled as machine-reported with its reception time:
the server never states a write it has not been told about by the machine, and
a machine that never reported, or whose report is stale, says so explicitly
instead of being presented as current.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from studio_contracts.auth import HarnessReport, MachineStatus
from studio_contracts.bootstrap import BootstrapFileSummary
from studio_contracts.common import ContractModel


class ReportFreshness(StrEnum):
    """`fresh`: reported within the offline threshold. `stale`: older than
    that, shown for information only. `never_reported`: no report at all."""

    FRESH = "fresh"
    STALE = "stale"
    NEVER_REPORTED = "never_reported"


class DesiredIntegration(ContractModel):
    """Server-side expectation: the bootstrap plan of the project. Counts by
    artifact kind (`agent_definition`, `model_profile`, `skill`, `rule`)."""

    plan_hash: str
    agent_keys: list[str] = Field(default_factory=list)
    artifact_counts: dict[str, int] = Field(default_factory=dict)


class AppliedBootstrap(ContractModel):
    """The machine's own last local check of this project's AI bundle.
    `in_sync` is true only when every planned file was observed up to date;
    it is machine-observed, never inferred by the server."""

    checked_at: datetime
    summary: BootstrapFileSummary
    in_sync: bool


class ReportedMachineIntegration(ContractModel):
    """What one machine reported, and only that. `harnesses` are the
    machine's own `detected`/`configured` claims; `project_registered` is
    `None` when the machine never reported; `bootstrap` is `None` until the
    machine has reported a local check of this project."""

    machine_id: UUID
    display_name: str
    status: MachineStatus
    freshness: ReportFreshness
    reported_at: datetime | None = None
    project_registered: bool | None = None
    harnesses: list[HarnessReport] = Field(default_factory=list)
    bootstrap: AppliedBootstrap | None = None


class AiIntegrationStatus(ContractModel):
    """`desired` is `None` when the plan cannot be built; `desired_error`
    then carries the public error code (never a stack or a path). `machines`
    are the caller's own machines (every machine for `admin`)."""

    project_id: UUID
    desired: DesiredIntegration | None = None
    desired_error: str | None = None
    machines: list[ReportedMachineIntegration] = Field(default_factory=list)
