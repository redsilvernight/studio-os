from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from studio_contracts.local.common import (
    CapabilityName,
    ComponentId,
    Identifier,
    LocalContractModel,
    LocalError,
    LocalErrorCode,
    OpaqueId,
    RelativePath,
    SemVer,
    Sha256Hex,
    ShortText,
    UtcDatetime,
)


class HarnessState(StrEnum):
    DETECTED = "detected"
    CONFIGURED = "configured"
    INCOMPATIBLE = "incompatible"
    NOT_DETECTED = "not_detected"
    ERROR = "error"


_HARNESS_STATE_ERROR: dict[HarnessState, LocalErrorCode | None] = {
    HarnessState.DETECTED: None,
    HarnessState.CONFIGURED: None,
    HarnessState.INCOMPATIBLE: LocalErrorCode.PROVIDER_INCOMPATIBLE,
    HarnessState.NOT_DETECTED: LocalErrorCode.PROVIDER_NOT_INSTALLED,
    HarnessState.ERROR: None,
}


class ChangeKind(StrEnum):
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


class HarnessStatus(LocalContractModel):
    """What the Desktop knows about one agent harness on this machine. A
    harness is identified by an opaque adapter id; the contract carries no
    vendor concept and never a provider credential — only whether Studio OS's
    own integration files are in place."""

    adapter_id: Identifier
    harness_id: Identifier
    display_name: ShortText
    state: HarnessState
    detected_version: SemVer | None = None
    capabilities: list[CapabilityName] = Field(default=[], max_length=32)
    managed_files: list[RelativePath] = Field(default=[], max_length=64)
    error: LocalError | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        expected = _HARNESS_STATE_ERROR[self.state]
        if self.state is HarnessState.ERROR:
            if self.error is None:
                raise ValueError("an errored harness carries an error")
        elif expected is None:
            if self.error is not None:
                raise ValueError(f"state {self.state.value} carries no error")
        elif self.error is None or self.error.code is not expected:
            raise ValueError(f"state {self.state.value} requires error {expected.value}")
        if self.error is not None and self.error.component is not ComponentId.HARNESS:
            raise ValueError("harness errors are reported by the harness component")
        if self.state in (HarnessState.NOT_DETECTED, HarnessState.INCOMPATIBLE) and (
            self.capabilities
        ):
            raise ValueError("an unusable harness offers no capability")
        if self.state is not HarnessState.CONFIGURED and self.managed_files:
            raise ValueError("only a configured harness has managed files")
        return self


class HarnessDetectResult(LocalContractModel):
    harnesses: list[HarnessStatus] = Field(default=[], max_length=32)


class HarnessStatusRequest(LocalContractModel):
    workspace_id: UUID
    adapter_id: Identifier


PROTECTED_TARGET_SEGMENTS = frozenset({".git", ".ssh", ".gnupg", ".aws", ".kube"})


class ChangeScope(StrEnum):
    WORKSPACE = "workspace"
    USER = "user"


class HarnessChange(LocalContractModel):
    """One file-level change of a plan. Hashes and a short summary describe it;
    file content is deliberately absent so that a plan can be shown, logged and
    diffed without ever exposing a credential a config file might hold.

    `target` is relative to the workspace, or to the user's home directory when
    `scope` is `user` (the tool's own configuration, DEC-0104 §2). A user-scope
    change describes one entry of that file and its hashes are computed on the
    entry with every credential masked."""

    change_id: OpaqueId
    kind: ChangeKind
    target: RelativePath
    scope: ChangeScope = ChangeScope.WORKSPACE
    summary: ShortText
    before_hash: Sha256Hex | None = None
    after_hash: Sha256Hex | None = None

    @model_validator(mode="after")
    def _hashes_fit_kind(self) -> Self:
        segments = [part.lower() for part in self.target.split("/")]
        if any(part in PROTECTED_TARGET_SEGMENTS or part.startswith(".env") for part in segments):
            raise ValueError("a harness change never targets a protected location")
        if self.kind is ChangeKind.CREATE and (self.before_hash or not self.after_hash):
            raise ValueError("create has an after hash only")
        if self.kind is ChangeKind.MODIFY and not (self.before_hash and self.after_hash):
            raise ValueError("modify has before and after hashes")
        if self.kind is ChangeKind.DELETE and (self.after_hash or not self.before_hash):
            raise ValueError("delete has a before hash only")
        return self


class HarnessPreviewRequest(LocalContractModel):
    """`renew` plans a new dedicated credential even when the tool is already
    configured; the previous one is revoked once the new one is in place."""

    workspace_id: UUID
    adapter_id: Identifier
    renew: bool = False


class HarnessPlan(LocalContractModel):
    plan_id: OpaqueId
    adapter_id: Identifier
    workspace_id: UUID
    changes: list[HarnessChange] = Field(default=[], max_length=50)
    plan_hash: Sha256Hex
    created_at: UtcDatetime
    expires_at: UtcDatetime
    requires_confirmation: Literal[True] = True

    @model_validator(mode="after")
    def _plan_window(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("a plan expires after it is created")
        ids = [change.change_id for change in self.changes]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate change ids in plan")
        return self


class HarnessApplyRequest(LocalContractModel):
    """Apply is bound to a previously previewed plan by id and hash, and needs
    an explicit confirmation: nothing is applied from a fresh request."""

    plan_id: OpaqueId
    plan_hash: Sha256Hex
    confirmed: Literal[True]


class HarnessApplyResult(LocalContractModel):
    plan_id: OpaqueId
    applied: list[OpaqueId] = Field(default=[], max_length=50)
    rollback_id: OpaqueId | None = None
    state: HarnessState
    error: LocalError | None = None

    @model_validator(mode="after")
    def _applied_is_reversible(self) -> Self:
        if self.applied and self.rollback_id is None:
            raise ValueError("applied changes are reversible through a rollback id")
        if (
            self.error is not None
            and self.error.code is LocalErrorCode.PLAN_EXPIRED
            and self.applied
        ):
            raise ValueError("an expired plan applies nothing")
        return self


class HarnessRollbackRequest(LocalContractModel):
    rollback_id: OpaqueId
    confirmed: Literal[True]


class HarnessRollbackResult(LocalContractModel):
    rollback_id: OpaqueId
    restored: list[OpaqueId] = Field(default=[], max_length=50)
    state: HarnessState
    error: LocalError | None = None


class VerifyState(StrEnum):
    UNCONFIGURED = "unconfigured"
    CONFIGURED = "configured"
    TOKEN_MISSING = "token_missing"
    VERIFIED = "verified"
    FAILED = "failed"


class HarnessVerifyRequest(LocalContractModel):
    """Ask the harness to prove it can reach Studi'OS via MCP. CONFIGURED
    means the config file is in place; TOKEN_MISSING means the config is in
    place but no machine token is available to the harness, so its MCP calls
    cannot authenticate; VERIFIED means a real MCP call succeeded end-to-end
    (auth + at least one tool call)."""

    workspace_id: UUID
    adapter_id: Identifier


class HarnessVerifyResult(LocalContractModel):
    adapter_id: Identifier
    state: VerifyState
    mcp_url: str | None = None
    error: LocalError | None = None
    details: dict[str, str] = Field(default={}, max_length=16)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.state is VerifyState.VERIFIED:
            if self.error is not None:
                raise ValueError("verified state carries no error")
            if self.mcp_url is None:
                raise ValueError("verified state requires mcp_url")
        if self.state in (
            VerifyState.UNCONFIGURED,
            VerifyState.CONFIGURED,
            VerifyState.TOKEN_MISSING,
        ):
            if self.error is not None:
                raise ValueError(f"state {self.state.value} carries no error")
        if self.state is VerifyState.FAILED:
            if self.error is None:
                raise ValueError("failed state requires error")
        return self
