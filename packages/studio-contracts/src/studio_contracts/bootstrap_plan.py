"""Aggregated bootstrap plan contracts (AI Bootstrap P2, AIB-B/DEC-0144).

The plan is the read-only, deterministic aggregation of the expected Library
artifacts of a project: every agent definition visible in the project context
resolved through `resolve_full` (never a second resolution engine), merged into
one de-duplicated artifact list with provenance and a content hash.

By construction the plan is harness-agnostic and free of any wall-clock value,
machine path or secret: the same inputs yield the same bytes, and adapters
project it afterwards (P3).
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from studio_contracts.common import ContractModel
from studio_contracts.library import LibraryKind, LibraryScope, VersionOrigin
from studio_contracts.resolution import Provenance, RulePath

MAX_BOOTSTRAP_PLAN_AGENTS = 50
MAX_AGENT_KEY = 200


class BootstrapSegment(StrEnum):
    """Common (Studio-wide or user-owned) versus project-owned artifact."""

    COMMON = "common"
    PROJECT = "project"


def segment_for_scope(scope: LibraryScope) -> BootstrapSegment:
    return BootstrapSegment.PROJECT if scope == LibraryScope.PROJECT else BootstrapSegment.COMMON


def content_hash(content: dict[str, object]) -> str:
    """SHA-256 of the canonical JSON encoding (sorted keys, no whitespace)."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class BootstrapPlanRequest(ContractModel):
    """`agent_keys` empty selects every active agent definition visible in the
    project context; otherwise exactly the named ones (unknown or invisible key
    fails closed with the public `definition_not_found`)."""

    project_id: UUID
    agent_keys: list[str] = Field(default_factory=list, max_length=MAX_BOOTSTRAP_PLAN_AGENTS)


class BootstrapPlanArtifact(ContractModel):
    """One expected artifact, de-duplicated by `(resource_id, version)`.
    `required_by` lists the agent stable keys that need it; `provenance`
    (agents, skills) or `paths` (rules) explains why this version was chosen."""

    resource_id: UUID
    kind: LibraryKind
    stable_key: str
    scope: LibraryScope
    segment: BootstrapSegment
    version: int
    version_origin: VersionOrigin
    deprecated: bool = False
    title: str = ""
    content_hash: str
    required_by: list[str] = []
    provenance: Provenance | None = None
    paths: list[RulePath] = []


class BootstrapPlan(ContractModel):
    """`plan_hash` covers `(kind, stable_key, scope, version, content_hash)` of
    every artifact in order: two equal hashes mean two equal expected bundles."""

    project_id: UUID
    agent_keys: list[str] = []
    artifacts: list[BootstrapPlanArtifact] = []
    plan_hash: str
