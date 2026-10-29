from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from studio_contracts.auth import Agent
from studio_contracts.common import ContractModel

HARNESS_IDENTITY_ALIASES = {
    "codex-cli": "codex",
    "codex-desktop": "codex",
    "claude-code": "claude",
    "claude-cli": "claude",
    "claude-desktop": "claude",
    "opencode-cli": "opencode",
    "opencode-desktop": "opencode",
}


def logical_harness(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    return HARNESS_IDENTITY_ALIASES.get(normalized, normalized)


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


class AgentIdentityLinkRequest(ContractModel):
    """Point a former identity at its canonical one: explicit,
    reversible, and never a merge — the former row is not rewritten."""

    canonical_agent_id: UUID


class AgentIdentityLink(ContractModel):
    legacy_agent_id: UUID
    canonical_agent_id: UUID
    owner_user_id: UUID
    logical_harness: str
    provider: str
    model: str


class AgentIdentityReconciliationPlan(ContractModel):
    """Dry-run report of the historical duplicates that an explicit
    reconciliation would link. Empty `links` means nothing to reconcile."""

    links: list[AgentIdentityLink]
    already_linked: int = 0
    unmatched_legacy: int = 0
