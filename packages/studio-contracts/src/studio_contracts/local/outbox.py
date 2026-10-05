from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, NonNegativeInt, model_validator

from studio_contracts.local.common import LocalContractModel


class LegacyOutboxTable(StrEnum):
    """Closed set of tables a pre-identity outbox may hold."""

    PENDING_EVENTS = "pending_events"
    PENDING_MUTATIONS = "pending_mutations"
    PENDING_MARKERS = "pending_markers"
    DEAD_LETTER = "dead_letter"
    MULTIPART_UPLOADS = "multipart_uploads"


class OutboxLegacyStatus(LocalContractModel):
    """Read-only view of the pre-identity outbox.

    Never carries a filesystem path: the daemon holds the location, the
    Desktop only learns whether queued work remains and how much per table.
    Phase 1 exposes no purge or import, only this status.
    """

    exists: bool
    has_queued_work: bool
    counts: dict[LegacyOutboxTable, NonNegativeInt] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _counts_match_presence(self) -> Self:
        if not self.exists and self.counts:
            raise ValueError("an absent legacy outbox carries no counts")
        if self.has_queued_work != any(count > 0 for count in self.counts.values()):
            raise ValueError("has_queued_work must reflect the counts")
        return self
