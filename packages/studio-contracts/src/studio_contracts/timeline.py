from __future__ import annotations

from datetime import date
from uuid import UUID

from studio_contracts.common import ContractModel
from studio_contracts.events import EventEnvelope


class TimelineDay(ContractModel):
    date: date
    events: list[EventEnvelope]


class Timeline(ContractModel):
    """Day-grouped project activity (newest day first, events ascending
    within a day) — unfiltered, unlike the Review Queue (DEC-0049): this is
    history, not an actionable signal. Inherits `GET /events`'s "not claimed
    exhaustive" honesty (DEC-0051) since it reads the same underlying data."""

    project_id: UUID
    days: list[TimelineDay]
