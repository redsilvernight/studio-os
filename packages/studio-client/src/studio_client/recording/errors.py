from __future__ import annotations


class RecordingError(Exception):
    """Typed failure for the local recording/marker/marketing pipeline.

    `reason` is machine-readable and stable; `message` is human detail.
    Raised instead of a bare `ValueError`/`KeyError` so the CLI and the
    daemon branch on the cause without parsing prose (same discipline as
    `studio_client.knowledge.errors.KnowledgeError`). Everything here is
    Bloc B local state — no server call is implied by a reason.
    """

    NO_ACTIVE_RECORDING = "no_active_recording"
    RECORDING_ALREADY_ACTIVE = "recording_already_active"
    INVALID_LABEL = "invalid_label"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_RANGE = "invalid_range"

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.message = message
