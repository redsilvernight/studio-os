from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from studio_client.recording.errors import RecordingError
from studio_client.recording.marker import Marker, to_iso

DEFAULT_PRE_ROLL_SECONDS = 15.0
DEFAULT_POST_ROLL_SECONDS = 15.0


@dataclass(frozen=True)
class MarketingCandidate:
    """A proposed clip range around a marker — the "moment interessant" the
    marketing worker turns into a proposition (`HUMAN/03`, workflow
    « Marquer un moment marketing »). It is a pure range, never raw video
    bytes: the pipeline reads the recording segment `[start, end]` locally.

    The range is a starting default (marker +/- roll); a later review step
    may trim it. Nothing here is persisted server-side beyond the
    `marketing.candidate.created` event."""

    candidate_id: UUID
    marker_id: UUID
    project_id: UUID
    label: str
    start: datetime
    end: datetime
    task_id: UUID | None = None
    session_id: UUID | None = None
    recording_id: UUID | None = None

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def event_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "candidate_id": str(self.candidate_id),
            "marker_id": str(self.marker_id),
            "label": self.label,
            "start": to_iso(self.start),
            "end": to_iso(self.end),
            "duration_seconds": round(self.duration_seconds, 3),
        }
        if self.session_id is not None:
            payload["session_id"] = str(self.session_id)
        if self.recording_id is not None:
            payload["recording_id"] = str(self.recording_id)
        return payload

    @classmethod
    def from_marker(
        cls,
        marker: Marker,
        *,
        candidate_id: UUID,
        pre_roll_seconds: float = DEFAULT_PRE_ROLL_SECONDS,
        post_roll_seconds: float = DEFAULT_POST_ROLL_SECONDS,
    ) -> MarketingCandidate:
        if pre_roll_seconds < 0 or post_roll_seconds < 0:
            raise RecordingError(
                RecordingError.INVALID_RANGE, "pre/post-roll seconds must not be negative"
            )
        start = marker.timestamp - timedelta(seconds=pre_roll_seconds)
        end = marker.timestamp + timedelta(seconds=post_roll_seconds)
        if end <= start:
            raise RecordingError(RecordingError.INVALID_RANGE, "marketing candidate range is empty")
        return cls(
            candidate_id=candidate_id,
            marker_id=marker.marker_id,
            project_id=marker.project_id,
            label=marker.label,
            start=start,
            end=end,
            task_id=marker.task_id,
            session_id=marker.session_id,
            recording_id=marker.recording_id,
        )
