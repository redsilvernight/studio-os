from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from studio_contracts.local.common import LocalContractModel

LEGACY_OUTBOX_TABLES = frozenset(
    {
        "pending_events",
        "pending_mutations",
        "pending_markers",
        "dead_letter",
        "multipart_uploads",
    }
)


class OutboxLegacyStatus(LocalContractModel):
    """Read-only view of the pre-identity outbox.

    Never carries a filesystem path: the daemon holds the location, the
    Desktop only learns whether queued work remains and how much per table.
    Phase 1 exposes no purge or import, only this status.
    """

    exists: bool
    has_queued_work: bool
    counts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _counts_match_presence(self) -> Self:
        for table, count in self.counts.items():
            if table not in LEGACY_OUTBOX_TABLES:
                raise ValueError(f"unknown legacy outbox table {table!r}")
            if count < 0:
                raise ValueError(f"count for {table!r} cannot be negative")
        if not self.exists and self.counts:
            raise ValueError("an absent legacy outbox carries no counts")
        if self.has_queued_work != any(count > 0 for count in self.counts.values()):
            raise ValueError("has_queued_work must reflect the counts")
        return self
