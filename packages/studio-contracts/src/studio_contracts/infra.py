"""Internal infrastructure measurements (phase M, read-only, admin).

Aggregates only: a metric name, an optional table name or project id, and
numbers with their timestamp. No title, file name or content ever appears here
(DEC-0384). Same source as the Usage screen and the operator console.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, Field

from studio_contracts.common import ContractModel


class InfraPoint(ContractModel):
    measured_at: AwareDatetime
    value: int = Field(ge=0)


class InfraSeries(ContractModel):
    """One measured fact over the window, oldest point first. `subject` is a
    table name (empty for an instance-wide fact); `project_id` is set only for
    per-project facts."""

    metric: str
    subject: str = ""
    project_id: UUID | None = None
    latest: InfraPoint
    points: list[InfraPoint]


class InfraMeasurementsReport(ContractModel):
    window_days: int
    generated_at: AwareDatetime
    series: list[InfraSeries]
