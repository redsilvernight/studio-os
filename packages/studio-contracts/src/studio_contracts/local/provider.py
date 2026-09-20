from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from studio_contracts.local.common import (
    CapabilityName,
    ComponentId,
    ComponentState,
    Identifier,
    LocalContractModel,
    LocalError,
    LocalErrorCode,
    SemVer,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)


class IndexState(StrEnum):
    ABSENT = "absent"
    INDEXING = "indexing"
    READY = "ready"
    STALE = "stale"
    CORRUPT = "corrupt"


class IndexInfo(LocalContractModel):
    """Description of a derived index. An index is always rebuildable from its
    canonical source; `derived` and `rebuildable` are constants of the model,
    not settings."""

    state: IndexState
    derived: bool = True
    rebuildable: bool = True
    built_at: UtcDatetime | None = None
    source_fingerprint: Sha256Hex | None = None
    item_count: int | None = Field(default=None, ge=0)
    progress_percent: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if not (self.derived and self.rebuildable):
            raise ValueError("an index is derived and rebuildable")
        if self.state is IndexState.READY and self.built_at is None:
            raise ValueError("a ready index records when it was built")
        if self.state is IndexState.ABSENT and self.item_count:
            raise ValueError("an absent index has no items")
        if self.state is not IndexState.INDEXING and self.progress_percent is not None:
            raise ValueError("progress applies only while indexing")
        return self


class ProviderInfo(LocalContractModel):
    provider_id: Identifier
    display_name: ShortText
    provider_version: SemVer | None = None
    capabilities: list[CapabilityName] = Field(default=[], max_length=64)


INDEX_STATE_COMPONENT: dict[IndexState, ComponentState] = {
    IndexState.ABSENT: ComponentState.UNAVAILABLE,
    IndexState.INDEXING: ComponentState.INDEXING,
    IndexState.READY: ComponentState.READY,
    IndexState.STALE: ComponentState.STALE,
    IndexState.CORRUPT: ComponentState.ERROR,
}

_STATE_ERROR: dict[ComponentState, LocalErrorCode] = {
    ComponentState.DISABLED: LocalErrorCode.FEATURE_DISABLED,
    ComponentState.NOT_INSTALLED: LocalErrorCode.PROVIDER_NOT_INSTALLED,
    ComponentState.PERMISSION_DENIED: LocalErrorCode.PERMISSION_DENIED,
    ComponentState.INCOMPATIBLE: LocalErrorCode.PROVIDER_INCOMPATIBLE,
}
_NO_ERROR_STATES = frozenset(
    {
        ComponentState.READY,
        ComponentState.STALE,
        ComponentState.INDEXING,
        ComponentState.STARTING,
        ComponentState.STOPPING,
        ComponentState.RECOVERING,
    }
)


def check_provider_state(
    component: ComponentId,
    state: ComponentState,
    index: IndexInfo | None,
    error: LocalError | None,
    provider: ProviderInfo | None,
) -> None:
    """Shared invariant of Knowledge and Code Graph status: the top-level state,
    the index state and the error tell one consistent story."""
    if state in _NO_ERROR_STATES:
        if error is not None:
            raise ValueError(f"state {state.value} carries no error")
    else:
        if error is None:
            raise ValueError(f"state {state.value} requires a structured error")
        expected = _STATE_ERROR.get(state)
        if expected is not None and error.code is not expected:
            raise ValueError(f"state {state.value} requires error {expected.value}")
        if error.component is not component:
            raise ValueError(f"error must be reported by {component.value}")
    if state in (ComponentState.READY, ComponentState.STALE, ComponentState.INDEXING):
        if index is None or provider is None:
            raise ValueError(f"state {state.value} requires a provider and an index")
        if INDEX_STATE_COMPONENT[index.state] is not state:
            raise ValueError("index state contradicts component state")
    if state in (ComponentState.DISABLED, ComponentState.NOT_INSTALLED) and (
        index is not None and index.state is IndexState.READY
    ):
        raise ValueError("a disabled or missing provider serves no ready index")
