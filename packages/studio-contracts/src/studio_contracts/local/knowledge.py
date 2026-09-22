from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from studio_contracts.local.common import (
    MAX_SEARCH_RESULTS,
    ComponentId,
    ComponentState,
    Identifier,
    LocalContractModel,
    LocalError,
    LocalResourceKind,
    LocalResourceUri,
    OpaqueId,
    RelativePath,
    SafeText,
    Sha256Hex,
    ShortText,
    UtcDatetime,
    parse_local_uri,
)
from studio_contracts.local.graph import GraphNodeRef
from studio_contracts.local.provider import IndexInfo, ProviderInfo, check_provider_state


class KnowledgeIntegration(LocalContractModel):
    """An optional tool layered on the same Markdown files (for example a note
    editor). Never required: Knowledge works without any integration."""

    integration_id: Identifier
    state: ComponentState
    required: Literal[False] = False


class KnowledgeStatus(LocalContractModel):
    """Markdown files are the canonical content; everything else — search
    index, link graph — is derived from them and can be rebuilt at any time."""

    workspace_id: UUID
    state: ComponentState
    canonical_source: Literal["markdown_files"] = "markdown_files"
    provider: ProviderInfo | None = None
    index: IndexInfo | None = None
    integrations: list[KnowledgeIntegration] = []
    error: LocalError | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        check_provider_state(
            ComponentId.KNOWLEDGE, self.state, self.index, self.error, self.provider
        )
        return self


class KnowledgeDocumentRef(LocalContractModel):
    uri: LocalResourceUri
    title: ShortText
    content_hash: Sha256Hex
    modified_at: UtcDatetime

    @model_validator(mode="after")
    def _knowledge_uri(self) -> Self:
        if parse_local_uri(self.uri)[0] is not LocalResourceKind.KNOWLEDGE:
            raise ValueError("a knowledge document is addressed by a knowledge URI")
        return self


class KnowledgeSearchRequest(LocalContractModel):
    workspace_id: UUID
    query: SafeText = Field(min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=MAX_SEARCH_RESULTS)
    cursor: OpaqueId | None = None


class KnowledgeSearchHit(LocalContractModel):
    document: KnowledgeDocumentRef
    score: float = Field(ge=0.0, le=1.0)
    snippet: SafeText = Field(default="", max_length=300)


class KnowledgeSearchResult(LocalContractModel):
    hits: list[KnowledgeSearchHit] = Field(default=[], max_length=MAX_SEARCH_RESULTS)
    next_cursor: OpaqueId | None = None
    index_state: ComponentState
    complete: bool = True

    @model_validator(mode="after")
    def _partial_when_not_ready(self) -> Self:
        if self.index_state is not ComponentState.READY and self.complete:
            raise ValueError("results from a non-ready index are marked incomplete")
        return self


class KnowledgeGetDocumentRequest(LocalContractModel):
    uri: LocalResourceUri
    max_bytes: int = Field(default=65_536, ge=1, le=262_144)


class KnowledgeDocument(LocalContractModel):
    document: KnowledgeDocumentRef
    markdown: str = Field(max_length=262_144)
    truncated: bool = False
    outgoing_links: list[GraphNodeRef] = Field(default=[], max_length=200)


class KnowledgeReindexMode(StrEnum):
    INCREMENTAL = "incremental"
    FULL_REBUILD = "full_rebuild"


class KnowledgeVaultState(StrEnum):
    MISSING = "missing"
    EMPTY = "empty"
    MARKDOWN_EXISTING = "markdown_existing"
    STUDIOS_VAULT = "studios_vault"


class KnowledgeInitVaultRequest(LocalContractModel):
    workspace_id: UUID
    confirmed: Literal[True]


class KnowledgeInitVaultResult(LocalContractModel):
    workspace_id: UUID
    state_before: KnowledgeVaultState
    created: list[RelativePath] = Field(default_factory=list, max_length=32)
    skipped: list[RelativePath] = Field(default_factory=list, max_length=32)


class KnowledgeReindexRequest(LocalContractModel):
    workspace_id: UUID
    mode: KnowledgeReindexMode = KnowledgeReindexMode.INCREMENTAL


class KnowledgeReindexResult(LocalContractModel):
    accepted: bool
    operation_id: OpaqueId | None = None
    state: ComponentState
    error: LocalError | None = None

    @model_validator(mode="after")
    def _accepted_has_operation(self) -> Self:
        if self.accepted != (self.operation_id is not None):
            raise ValueError("an accepted reindex has an operation id, a refused one does not")
        if not self.accepted and self.error is None:
            raise ValueError("a refused reindex carries an error")
        return self
