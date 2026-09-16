from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class SourceRef:
    """One source captured in the Context Package (DEC-0057)."""

    kind: str
    ref: str
    version: int | None = None
    server_timestamp: datetime | None = None
    seq: int | None = None
    stale: bool = False
    stale_reason: str | None = None
    included: int | None = None
    truncated: bool = False


@dataclass(frozen=True)
class Omission:
    """Something deliberately left out of the package, with a reason."""

    kind: str
    count: int
    reason: str


@dataclass(frozen=True)
class Limits:
    """Limits applied during composition."""

    budget_bytes: int
    events_limit: int
    decisions_limit: int
    ai_work_limit: int
    memory_limit: int
    graph_limit: int
    git_commits_limit: int


@dataclass(frozen=True)
class Generator:
    """Who/what produced the package."""

    machine_id: UUID | None


@dataclass(frozen=True)
class ContextPackageManifest:
    """Versioned, ephemeral artifact manifest (DEC-0057, schema_version: 1)."""

    schema_version: int = 1
    package_id: UUID = field(default_factory=uuid4)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    project_id: UUID | None = None
    task_id: UUID | None = None
    generator: Generator = field(default_factory=lambda: Generator(machine_id=None))
    manifest_scope: str = "local"
    limits: Limits = field(
        default_factory=lambda: Limits(
            budget_bytes=0,
            events_limit=0,
            decisions_limit=0,
            ai_work_limit=0,
            memory_limit=0,
            graph_limit=0,
            git_commits_limit=0,
        )
    )
    sources: list[SourceRef] = field(default_factory=list)
    omitted: list[Omission] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-serializable dict."""

        def _convert(value: object) -> Any:
            if isinstance(value, UUID):
                return str(value)
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, list):
                return [_convert(item) for item in value]
            if isinstance(value, dict):
                return {k: _convert(v) for k, v in value.items()}
            return value

        raw = asdict(self)
        return {k: _convert(v) for k, v in raw.items()}

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def package_size_bytes(self) -> int:
        """Rough serialized size of the manifest itself."""
        return len(self.to_json().encode("utf-8"))
