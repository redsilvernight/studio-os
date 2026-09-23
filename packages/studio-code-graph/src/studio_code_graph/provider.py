from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from studio_contracts.local.graph import GraphEdge, GraphNode


class ProbeState(StrEnum):
    AVAILABLE = "available"
    NOT_INSTALLED = "not_installed"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ProviderProbe:
    state: ProbeState
    version: str | None = None
    reason: str = ""


class BuildFailure(StrEnum):
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PROCESS_FAILED = "process_failed"
    OUTPUT_MISSING = "output_missing"
    OUTPUT_CORRUPT = "output_corrupt"
    NOT_AVAILABLE = "not_available"


class CodeGraphBuildError(Exception):
    """A provider run that produced no usable graph. `detail` is bounded,
    path-free text safe to surface in a `LocalError`."""

    def __init__(self, failure: BuildFailure, detail: str = "") -> None:
        super().__init__(f"{failure.value}: {detail}" if detail else failure.value)
        self.failure = failure
        self.detail = detail


@dataclass(frozen=True)
class BuildRequest:
    workspace_id: UUID
    repo_name: str
    repo_root: Path
    work_dir: Path
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    full_rebuild: bool = False
    timeout_seconds: float = 300.0


@dataclass(frozen=True)
class RepoGraph:
    """Provider-neutral result of indexing one repository: already in the common
    graph schema. Nothing engine-specific crosses this boundary."""

    repo_name: str
    provider_id: str
    provider_version: str | None
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    languages: tuple[str, ...] = ()
    dropped: dict[str, int] = field(default_factory=dict)
    """Counts by reason of provider facts that were NOT represented (unresolved
    external symbols, unsupported relations, unsafe paths, ...)."""


@runtime_checkable
class CodeGraphProvider(Protocol):
    """What Studi'OS needs from a code-structure engine; the service depends
    on this protocol only."""

    provider_id: str
    display_name: str
    capabilities: tuple[str, ...]
    language_by_extension: Mapping[str, str]

    def probe(self) -> ProviderProbe: ...

    async def build(self, request: BuildRequest, source_id: str) -> RepoGraph: ...
