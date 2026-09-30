from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from studio_contracts.local.common import LocalContractModel, UtcDatetime

SkillStableKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,199}$")]


class SkillSyncState(StrEnum):
    CURRENT = "current"
    MISSING = "missing"
    OUTDATED = "outdated"
    LOCALLY_MODIFIED = "locally_modified"


class SkillHarnessTarget(StrEnum):
    AGENTS = "agents"
    ASSISTANT = "assistant"


class SkillsCheckRequest(LocalContractModel):
    """Read-only: the daemon resolves the Library, the profile and the home
    directory itself, so the Desktop supplies nothing."""


class SkillTargetState(LocalContractModel):
    """State of one harness copy of a skill. The contract carries no path and
    no skill content: only which harness directory and how it compares."""

    harness: SkillHarnessTarget
    state: SkillSyncState


class SkillCheckEntry(LocalContractModel):
    stable_key: SkillStableKey
    version: int = Field(ge=1)
    targets: list[SkillTargetState] = Field(min_length=1, max_length=len(SkillHarnessTarget))

    @model_validator(mode="after")
    def _one_target_per_harness(self) -> Self:
        harnesses = [target.harness for target in self.targets]
        if len(set(harnesses)) != len(harnesses):
            raise ValueError("a skill lists each harness at most once")
        return self


class SkillsCheckResult(LocalContractModel):
    """Effective Studio-scope Library skills compared with the two global
    harness directories. `in_sync` is true only when every target is current."""

    skills: list[SkillCheckEntry] = Field(default=[], max_length=500)
    current: int = Field(ge=0)
    missing: int = Field(ge=0)
    outdated: int = Field(ge=0)
    locally_modified: int = Field(ge=0)
    in_sync: bool
    checked_at: UtcDatetime

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        counts = dict.fromkeys(SkillSyncState, 0)
        keys = [entry.stable_key for entry in self.skills]
        if len(set(keys)) != len(keys):
            raise ValueError("a skill appears once in a check result")
        for entry in self.skills:
            for target in entry.targets:
                counts[target.state] += 1
        if (
            counts[SkillSyncState.CURRENT] != self.current
            or counts[SkillSyncState.MISSING] != self.missing
            or counts[SkillSyncState.OUTDATED] != self.outdated
            or counts[SkillSyncState.LOCALLY_MODIFIED] != self.locally_modified
        ):
            raise ValueError("counts must match the listed targets")
        if self.in_sync != (self.missing + self.outdated + self.locally_modified == 0):
            raise ValueError("in_sync is true only when no target is missing or drifted")
        return self
