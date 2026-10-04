"""Workstation setup (« Configurer ce poste »): a read-only plan, then an
explicit, plan-bound apply.

The contract carries no filesystem path, no file content beyond a bounded,
redacted diff of a file the setup would replace, and no credential. The MCP
wiring of each harness keeps going through ``harness.preview`` / ``harness.apply``
(AIB-E): this contract only covers what is machine-global — session hooks, the
git guard, the harness plugin and the Library skills — plus the read-only
adapter drift report.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from studio_contracts.local.common import (
    Identifier,
    LocalContractModel,
    OpaqueId,
    SafeText,
    Sha256Hex,
    UtcDatetime,
)

SetupDiff = Annotated[SafeText, StringConstraints(max_length=8200)]


class SetupItemKind(StrEnum):
    HOOK = "hook"
    GUARD = "guard"
    PLUGIN = "plugin"


class SetupItemState(StrEnum):
    MISSING = "missing"
    CURRENT = "current"
    # The file exists and differs from the managed render (foreign, or a managed
    # copy edited by hand): replaced only on an explicit, named confirmation.
    DIFFERS = "differs"


class SetupItemOutcome(StrEnum):
    WRITTEN = "written"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"


class SetupSkillsState(StrEnum):
    CHECKED = "checked"
    UNAVAILABLE = "unavailable"


class SetupUnavailableReason(StrEnum):
    NOT_SIGNED_IN = "not_signed_in"
    CREDENTIAL_REJECTED = "credential_rejected"
    LIBRARY_UNREACHABLE = "library_unreachable"
    INVALID_SKILL = "invalid_skill"


class SetupAdaptersState(StrEnum):
    CHECKED = "checked"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


class SetupSkillsOutcome(StrEnum):
    SYNCED = "synced"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class SetupPlanRequest(LocalContractModel):
    """Read-only: the daemon resolves the home directory, the Library, the
    profile and the registered folders itself."""


class SetupHarness(LocalContractModel):
    harness: Identifier
    detected: bool


class SetupItemPlan(LocalContractModel):
    item_id: OpaqueId
    kind: SetupItemKind
    harness: Identifier
    state: SetupItemState
    managed: bool
    lines_added: int = Field(default=0, ge=0)
    lines_removed: int = Field(default=0, ge=0)
    diff: SetupDiff = ""
    diff_truncated: bool = False
    # A deployed hook file is wired by the harness' own settings, which the
    # setup never edits: the registration stays a manual step.
    needs_registration: bool = False

    @model_validator(mode="after")
    def _diff_only_when_differs(self) -> Self:
        if self.state is not SetupItemState.DIFFERS and (
            self.diff or self.lines_added or self.lines_removed or self.diff_truncated
        ):
            raise ValueError("only a differing file carries a diff")
        return self


class SetupSkillsStep(LocalContractModel):
    state: SetupSkillsState
    reason: SetupUnavailableReason | None = None
    current: int = Field(default=0, ge=0)
    missing: int = Field(default=0, ge=0)
    outdated: int = Field(default=0, ge=0)
    locally_modified: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _reason_matches_state(self) -> Self:
        unavailable = self.state is SetupSkillsState.UNAVAILABLE
        if unavailable != (self.reason is not None):
            raise ValueError("an unavailable skills check states why, a checked one does not")
        if unavailable and (self.current or self.missing or self.outdated or self.locally_modified):
            raise ValueError("an unavailable skills check reports no counts")
        return self


class SetupAdaptersStep(LocalContractModel):
    state: SetupAdaptersState
    workspaces: int = Field(default=0, ge=0)
    checked: int = Field(default=0, ge=0)
    drifted: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _counts(self) -> Self:
        if self.state is not SetupAdaptersState.CHECKED and (self.checked or self.drifted):
            raise ValueError("only a completed check reports counts")
        if self.drifted > self.checked:
            raise ValueError("drifted files are among the checked ones")
        return self


class SetupPlan(LocalContractModel):
    """What « Configurer ce poste » would do. Bound to ``plan_hash``: a file
    edited after the preview invalidates the confirmation."""

    plan_id: OpaqueId
    plan_hash: Sha256Hex
    created_at: UtcDatetime
    expires_at: UtcDatetime
    requires_confirmation: Literal[True] = True
    harnesses: list[SetupHarness] = Field(default=[], max_length=16)
    hooks: list[SetupItemPlan] = Field(default=[], max_length=16)
    skills: SetupSkillsStep
    adapters: SetupAdaptersStep

    @model_validator(mode="after")
    def _plan_window(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("a plan expires after it is created")
        ids = [item.item_id for item in self.hooks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate item ids in plan")
        return self


class SetupApplyRequest(LocalContractModel):
    """Bound to a previewed plan by id and hash, with an explicit confirmation.
    ``overwrite_items`` names, one by one, the differing files to replace (each is
    backed up first); a differing file that is not named is left untouched."""

    plan_id: OpaqueId
    plan_hash: Sha256Hex
    confirmed: Literal[True]
    overwrite_items: list[OpaqueId] = Field(default=[], max_length=16)
    sync_skills: bool = True

    @model_validator(mode="after")
    def _unique_items(self) -> Self:
        if len(set(self.overwrite_items)) != len(self.overwrite_items):
            raise ValueError("an item is named once")
        return self


class SetupItemResult(LocalContractModel):
    item_id: OpaqueId
    outcome: SetupItemOutcome
    backed_up: bool = False

    @model_validator(mode="after")
    def _backup_implies_write_attempt(self) -> Self:
        if self.backed_up and self.outcome not in (
            SetupItemOutcome.WRITTEN,
            SetupItemOutcome.FAILED,
        ):
            raise ValueError("a backup precedes a write")
        return self


class SetupSkillsResult(LocalContractModel):
    outcome: SetupSkillsOutcome
    written: int = Field(default=0, ge=0)
    # Locally modified skill files are never overwritten from the Desktop.
    left_modified: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _written_only_when_synced(self) -> Self:
        if (self.outcome is SetupSkillsOutcome.SYNCED) != (self.written > 0):
            raise ValueError("written counts match a synced outcome")
        return self


class SetupApplyResult(LocalContractModel):
    """Only what was read back from disk is reported as written."""

    plan_id: OpaqueId
    hooks: list[SetupItemResult] = Field(default=[], max_length=16)
    skills: SetupSkillsResult
    backups_created: bool = False

    @model_validator(mode="after")
    def _backups_flag(self) -> Self:
        if self.backups_created != any(item.backed_up for item in self.hooks):
            raise ValueError("backups_created reflects the item results")
        return self
