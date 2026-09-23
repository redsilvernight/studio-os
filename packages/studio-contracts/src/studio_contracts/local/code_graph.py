from __future__ import annotations

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from studio_contracts.local.common import (
    MAX_SEARCH_RESULTS,
    ComponentId,
    ComponentState,
    Identifier,
    LocalContractModel,
    LocalError,
    LocalErrorCode,
    LocalResourceKind,
    LocalResourceUri,
    OpaqueId,
    SafeText,
    ShortText,
    parse_local_uri,
)
from studio_contracts.local.graph import NodeKind
from studio_contracts.local.provider import (
    IndexInfo,
    IndexState,
    ProviderInfo,
    check_provider_state,
)


class CodeGraphStatus(LocalContractModel):
    """Status of the code-structure index behind the provider boundary. The
    contract names no concrete engine: an engine is an optional adapter that is
    installed separately, and its absence or incompatibility is an ordinary
    state, never a startup failure."""

    workspace_id: UUID
    state: ComponentState
    provider: ProviderInfo | None = None
    index: IndexInfo | None = None
    languages: list[Identifier] = Field(default=[], max_length=32)
    unsupported_languages: list[Identifier] = Field(default=[], max_length=32)
    error: LocalError | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        check_provider_state(
            ComponentId.CODE_GRAPH, self.state, self.index, self.error, self.provider
        )
        if self.index is not None:
            if self.index.state is IndexState.CORRUPT and (
                self.error is None or self.error.code is not LocalErrorCode.INDEX_CORRUPT
            ):
                raise ValueError("a corrupt index is reported as index_corrupt")
            if self.index.state is IndexState.ABSENT and (
                self.error is None or self.error.code is not LocalErrorCode.INDEX_ABSENT
            ):
                raise ValueError("an absent index is reported as index_absent")
        return self


class CodeSymbolRef(LocalContractModel):
    node_id: OpaqueId
    kind: NodeKind
    name: ShortText
    uri: LocalResourceUri

    @model_validator(mode="after")
    def _code_uri(self) -> Self:
        if parse_local_uri(self.uri)[0] is not LocalResourceKind.CODE:
            raise ValueError("a code symbol is addressed by a code URI")
        return self


class CodeSymbolQuery(LocalContractModel):
    workspace_id: UUID
    name: SafeText = Field(min_length=1, max_length=200)
    kinds: list[NodeKind] = Field(default=[], max_length=8)
    limit: int = Field(default=20, ge=1, le=MAX_SEARCH_RESULTS)
    cursor: OpaqueId | None = None


class CodeSymbolResult(LocalContractModel):
    symbols: list[CodeSymbolRef] = Field(default=[], max_length=MAX_SEARCH_RESULTS)
    next_cursor: OpaqueId | None = None
    index_state: IndexState
    complete: bool = True

    @model_validator(mode="after")
    def _partial_when_not_ready(self) -> Self:
        if self.index_state is not IndexState.READY and self.complete:
            raise ValueError("results from a non-ready index are marked incomplete")
        return self


class CodeReindexMode(StrEnum):
    INCREMENTAL = "incremental"
    FULL_REBUILD = "full_rebuild"


class CodeReindexRequest(LocalContractModel):
    workspace_id: UUID
    mode: CodeReindexMode = CodeReindexMode.INCREMENTAL
    repo_names: list[Identifier] = Field(default=[], max_length=32)


class CodeReindexResult(LocalContractModel):
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
