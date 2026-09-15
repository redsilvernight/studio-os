from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from studio_client.recording.errors import RecordingError

MAX_LABEL_LENGTH = 200

_RELATIVE_RE = re.compile(r"^(?P<sign>[+-]?)(?P<amount>\d+(?:\.\d+)?)(?P<unit>s|m|h)?$")
_UNIT_SECONDS: dict[str, float] = {"s": 1.0, "m": 60.0, "h": 3600.0}


def to_iso(value: datetime) -> str:
    """One canonical serialization for every event payload: UTC, always
    tz-aware. A naive datetime is read as UTC rather than silently dropped."""
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat()


def normalize_label(label: str) -> str:
    """Trim/collapse whitespace and bound the length — a marker label is a
    short human handle, never a paragraph echoed into shared history."""
    cleaned = " ".join(label.split())
    if not cleaned:
        raise RecordingError(RecordingError.INVALID_LABEL, "marker label must not be empty")
    if len(cleaned) > MAX_LABEL_LENGTH:
        raise RecordingError(
            RecordingError.INVALID_LABEL,
            f"marker label exceeds {MAX_LABEL_LENGTH} characters",
        )
    return cleaned


def parse_timestamp(
    value: str, *, now: datetime, relative_base: datetime | None = None
) -> datetime:
    """Accept an absolute ISO-8601 timestamp or a signed relative offset
    (`-45s`, `+2m`, `+90`).

    A relative offset is measured from `relative_base` when a recording is
    active (so `+90` means "1:30 into the capture") and from `now`
    otherwise. The default unit is seconds. This is the `--at` grammar;
    an unrecognized value raises `INVALID_TIMESTAMP` instead of guessing.
    """
    text = value.strip()
    if not text:
        raise RecordingError(RecordingError.INVALID_TIMESTAMP, "empty timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is not None:
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    match = _RELATIVE_RE.match(text)
    if match is None:
        raise RecordingError(
            RecordingError.INVALID_TIMESTAMP,
            f"unrecognized timestamp {value!r} (expected ISO-8601 or a signed offset like +90)",
        )
    seconds = float(match.group("amount")) * _UNIT_SECONDS[match.group("unit") or "s"]
    if match.group("sign") == "-":
        seconds = -seconds
    return (relative_base or now) + timedelta(seconds=seconds)


@dataclass(frozen=True)
class Marker:
    """A manual video marker (`studio mark "..."`). The `project_id`/`task_id`
    travel in the event envelope; everything else non-null travels in the
    compact payload. `offset_seconds` is the marker's position inside the
    recording and is only known when a recording was active."""

    marker_id: UUID
    label: str
    project_id: UUID
    timestamp: datetime
    task_id: UUID | None = None
    session_id: UUID | None = None
    recording_id: UUID | None = None
    offset_seconds: float | None = None

    def event_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "marker_id": str(self.marker_id),
            "label": self.label,
            "recorded_at": to_iso(self.timestamp),
        }
        if self.offset_seconds is not None:
            payload["offset_seconds"] = round(self.offset_seconds, 3)
        if self.session_id is not None:
            payload["session_id"] = str(self.session_id)
        if self.recording_id is not None:
            payload["recording_id"] = str(self.recording_id)
        return payload
