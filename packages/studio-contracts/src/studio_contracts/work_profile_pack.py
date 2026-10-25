from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from studio_contracts.common import ContractModel
from studio_contracts.library import BindingRelation, LibraryKind, ResourceDependencyPin
from studio_contracts.profiles import MachinePolicy, ProfilePreview, WorkProfile


class WorkProfilePack(ContractModel):
    format: Literal["studio.work-profile-pack/v1"]
    profile: WorkProfile
    base: ResourceDependencyPin
    adaptations: list[ResourceDependencyPin] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def _explicit_agent_references(self) -> WorkProfilePack:
        refs = [self.base, *self.adaptations]
        if any(ref.kind != LibraryKind.AGENT_DEFINITION or ref.version < 1 for ref in refs):
            raise ValueError("pack references must name agent definitions at a positive version")
        if any(ref.relation not in (None, BindingRelation.COMPOSES_AGENT) for ref in refs):
            raise ValueError("pack references only support composes_agent")
        if len({ref.resource_id for ref in refs}) != len(refs):
            raise ValueError("each definition appears at most once in a pack")
        root = self.adaptations[-1] if self.adaptations else self.base
        if root.stable_key != self.profile.agent_stable_key:
            raise ValueError("the last adaptation, or base alone, must match the profile agent")
        return self


class WorkProfilePackRequest(ContractModel):
    pack: WorkProfilePack
    machine_policy: MachinePolicy
    project_id: UUID | None = None


class WorkProfilePackPreview(ContractModel):
    format: Literal["studio.work-profile-pack-preview/v1"] = "studio.work-profile-pack-preview/v1"
    authoritative: Literal[False] = False
    mutates: Literal[False] = False
    accepted: bool
    profile: ProfilePreview
    observed: list[ResourceDependencyPin] = Field(max_length=17)
    issues: list[Literal["composition_mismatch", "composition_too_large"]] = []
