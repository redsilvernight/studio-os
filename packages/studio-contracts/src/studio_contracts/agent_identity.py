from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from studio_contracts.auth import Agent
from studio_contracts.common import ContractModel


def logical_harness(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    for suffix in ("-cli", "-desktop", "-code"):
        normalized = normalized.removesuffix(suffix)
    return normalized


class AgentIdentityRequest(ContractModel):
    harness: str = Field(min_length=1, max_length=100)
    provider: str | None = Field(default=None, max_length=200)
    effective_model: str | None = Field(default=None, max_length=300)
    selection_alias: str | None = Field(default=None, max_length=300)


class AgentIdentityResult(ContractModel):
    state: Literal["resolved", "unknown"]
    logical_harness: str
    reason: Literal["unknown_model", "unknown_provider"] | None = None
    selection_alias: str | None = None
    agent: Agent | None = None
    created: bool = False

    @model_validator(mode="after")
    def _resolution_matches_state(self) -> Self:
        if self.state == "resolved" and (self.agent is None or self.reason is not None):
            raise ValueError("resolved identity requires an agent and no unknown reason")
        if self.state == "unknown" and (
            self.agent is not None or self.reason is None or self.created
        ):
            raise ValueError("unknown identity requires a reason and cannot create an agent")
        return self
