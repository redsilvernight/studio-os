from __future__ import annotations

from typing import Literal

from pydantic import Field

from studio_contracts.common import ContractModel

DiscoveryIntent = Literal["overview", "start_project", "configuration"]
CapabilityState = Literal["available", "needs_configuration", "not_authorized", "unsupported"]


class ProductCapability(ContractModel):
    key: str
    title: str
    summary: str
    state: CapabilityState
    reason: str | None = None
    write_allowed: bool
    example: str | None = None
    prerequisites: list[str] = Field(default_factory=list, max_length=8)
    restrictions: list[str] = Field(default_factory=list, max_length=8)


class ProductDiscovery(ContractModel):
    format: Literal["studio.capabilities/v1"] = "studio.capabilities/v1"
    intent: DiscoveryIntent
    summary: str
    capabilities: list[ProductCapability] = Field(default_factory=list, max_length=24)
    additional_available: int = Field(default=0, ge=0)
    next_steps: list[str] = Field(default_factory=list, max_length=6)
