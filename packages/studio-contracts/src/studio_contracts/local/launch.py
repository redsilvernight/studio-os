from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from studio_contracts.local.common import Identifier, LocalContractModel

MAX_LAUNCH_CONCURRENCY = 8
MAX_LAUNCH_HARNESSES = 16


class LaunchSettingsRequest(LocalContractModel):
    """Read-only: the daemon owns the settings, the Desktop supplies nothing."""


class LaunchSettings(LocalContractModel):
    """What this machine agrees to when a remote launch is requested for it.
    Opting in never allows a harness implicitly: `allowed_harnesses` is an
    explicit list, and empty means none."""

    opt_in: bool
    max_concurrent: int = Field(ge=1, le=MAX_LAUNCH_CONCURRENCY)
    allowed_harnesses: list[Identifier] = Field(default=[], max_length=MAX_LAUNCH_HARNESSES)

    @model_validator(mode="after")
    def _unique_harnesses(self) -> Self:
        if len(set(self.allowed_harnesses)) != len(self.allowed_harnesses):
            raise ValueError("a harness is allowed at most once")
        return self


class LaunchSettingsView(LaunchSettings):
    """The settings plus the harnesses this machine can currently offer, so the
    Desktop only proposes ids the daemon will accept. Ids only: no path, no
    version, no inventory beyond the harness identifiers."""

    detected_harnesses: list[Identifier] = Field(default=[], max_length=MAX_LAUNCH_HARNESSES)

    @model_validator(mode="after")
    def _unique_detected(self) -> Self:
        if len(set(self.detected_harnesses)) != len(self.detected_harnesses):
            raise ValueError("a detected harness is listed at most once")
        return self


class LaunchSettingsSaveRequest(LaunchSettings):
    """Writing the opt-in is a deliberate act of the machine owner: nothing is
    saved from a request that does not carry an explicit confirmation."""

    confirmed: Literal[True]
