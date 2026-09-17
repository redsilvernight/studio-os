"""P5 Resolution Engine — pure logical core (DEC-0069).

Harness-neutral, provider-neutral, infrastructure-free: this module imports
only the standard library, pydantic (via `ContractModel`) and sibling
`studio_contracts` models. It performs no SQL, no HTTP, no machine contact,
no provider call, no LLM call, no secret access and reads no clock — the
same snapshot always yields the same result.

Two entry points:

- `select_runtime` — the single total-order runtime-choice selector
  (`session > project_override > user > project_default > studio_default`,
  agent key before profile key per level). Shared by the P4 service and the
  P5 engine so precedence has exactly one implementation.
- `resolve_agent` — assembles a fully loaded snapshot into a
  `ResolvedAgentDefinition` with complete structured provenance, judging
  compatibility *after* selection and never falling back to a lower level.

Loading and authorization stay outside: the caller (Bloc A service layer,
later Bloc B loader) resolves visibility, liveness and ownership first and
hands this core only objects that already passed those gates.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from studio_contracts.common import ContractModel
from studio_contracts.library import (
    BindingRelation,
    CapabilityRequirement,
    LibraryKind,
    LibraryScope,
    RuntimeCapabilities,
    VersionOrigin,
    binding_relation_for,
    check_compatibility,
)
from studio_contracts.runtime import RuntimeLevel, RuntimeTarget

_LEVEL_ORDER: tuple[RuntimeLevel, ...] = (
    RuntimeLevel.SESSION,
    RuntimeLevel.PROJECT_OVERRIDE,
    RuntimeLevel.USER,
    RuntimeLevel.PROJECT_DEFAULT,
    RuntimeLevel.STUDIO_DEFAULT,
)
"""Total runtime precedence (P4/DEC-0068, frozen here as the single source)."""


class ResolutionErrorCode(StrEnum):
    """Closed vocabulary of P5 resolution failures (machine-readable)."""

    DEFINITION_NOT_FOUND = "definition_not_found"
    UNRESOLVABLE_DEPENDENCY = "unresolvable_dependency"
    RUNTIME_INCOMPATIBLE = "runtime_incompatible"
    INVALID_RESOLUTION_INPUT = "invalid_resolution_input"


class ResolutionError(ContractModel):
    """Structured resolution failure. Carries codes and JSON-safe details only —
    never a private resource body. The service adapter maps dependency
    failures to the public `definition_not_found` (DEC-0065 §2, non-oracle)."""

    error_code: ResolutionErrorCode
    details: dict[str, object] = {}


class ResolutionFailure(Exception):
    """Pure `raise` carrier for a `ResolutionError` (no HTTP, no FastAPI)."""

    def __init__(self, error: ResolutionError) -> None:
        super().__init__(error.error_code.value)
        self.error = error


class ProvenanceSource(StrEnum):
    """Where a resolved element came from (structured, never prose)."""

    ACTIVE_POINTER = "active_pointer"
    PROJECT_LOCK = "project_lock"
    VERSION_PIN = "version_pin"
    RUNTIME_BINDING = "runtime_binding"
    SESSION_OVERRIDE = "session_override"


class Provenance(ContractModel):
    """Complete provenance for one resolved element.

    Answers: why this resource, why this version (lock vs active vs pin),
    through which relation, which runtime level won and whether an override
    decided. Every field is data, never a human sentence."""

    source: ProvenanceSource
    resource_id: UUID | None = None
    stable_key: str | None = None
    scope: LibraryScope | None = None
    version: int | None = None
    version_origin: VersionOrigin | None = None
    locked: bool = False
    relation: BindingRelation | None = None
    binding_level: RuntimeLevel | None = None
    via: str | None = None


class ResolvedAgent(ContractModel):
    resource_id: UUID
    kind: LibraryKind
    stable_key: str
    scope: LibraryScope
    version: int
    version_origin: VersionOrigin
    deprecated: bool = False
    title: str = ""
    content: dict[str, object] = {}
    provenance: Provenance


class RulePath(ContractModel):
    """One provenance path that produced a resolved rule.

    The same rule reached through several paths yields one logical object
    with one `RulePath` per path — deduplicated content, preserved history."""

    relation: BindingRelation
    via_kind: LibraryKind
    via_resource_id: UUID
    via_stable_key: str
    via_version: int


class ResolvedRule(ContractModel):
    resource_id: UUID
    stable_key: str
    scope: LibraryScope
    version: int
    version_origin: VersionOrigin
    deprecated: bool = False
    title: str = ""
    content: dict[str, object] = {}
    paths: list[RulePath] = []


class ResolvedSkill(ContractModel):
    resource_id: UUID
    stable_key: str
    scope: LibraryScope
    version: int
    version_origin: VersionOrigin
    deprecated: bool = False
    title: str = ""
    content: dict[str, object] = {}
    provenance: Provenance


class ResolvedModelProfile(ContractModel):
    resource_id: UUID
    stable_key: str
    scope: LibraryScope
    version: int
    version_origin: VersionOrigin
    deprecated: bool = False
    title: str = ""
    requirements: CapabilityRequirement = CapabilityRequirement()
    provenance: Provenance


class PreservedReference(ContractModel):
    """A `composes_agent` / `references_workflow` dependency, preserved with
    identity, exact version and provenance — never expanded: workflow
    execution semantics belong to P11 and agent-composition execution has no
    defined semantics yet (DEC-0067, DEC-0069)."""

    resource_id: UUID
    kind: LibraryKind
    stable_key: str
    scope: LibraryScope
    version: int
    version_origin: VersionOrigin
    deprecated: bool = False
    relation: BindingRelation
    provenance: Provenance


class ResolvedRuntime(ContractModel):
    """The winning runtime choice. `compatible` is always `True` here: an
    explicitly selected but incompatible target is a `runtime_incompatible`
    error, never a silent fallback and never a silent `null`."""

    target: RuntimeTarget
    level: RuntimeLevel
    matched_kind: LibraryKind
    matched_stable_key: str
    compatible: bool = True
    unsatisfied: list[str] = []
    provenance: Provenance | None = None


class ResolvedAgentDefinition(ContractModel):
    """Canonical P5 output: the complete logical agent specification.

    Harness-neutral (no Claude/Code/Cursor/Continue branch) and
    provider-neutral (`provider_ref`/`model_ref` travel as opaque strings
    when a binding carries them; no vendor catalog lives here). Stable input
    for P7 HTTP, P8 MCP, P9 Context Package and P10 adapters."""

    agent: ResolvedAgent
    rules: list[ResolvedRule] = []
    skills: list[ResolvedSkill] = []
    model_profile: ResolvedModelProfile | None = None
    requirements: CapabilityRequirement = CapabilityRequirement()
    composed_agents: list[PreservedReference] = []
    workflows: list[PreservedReference] = []
    runtime: ResolvedRuntime | None = None


class NodeBinding(ContractModel):
    """One already-loaded, already-authorized version pin."""

    relation: BindingRelation
    target_resource_id: UUID
    target_version: int


class ResolutionNode(ContractModel):
    """One loaded resource version. `version_origin` records how the loader
    picked the version (`lock` / `active` for the root via P2, `pin` for
    exact dependency pins) — the core trusts it and reports it."""

    resource_id: UUID
    kind: LibraryKind
    stable_key: str
    scope: LibraryScope
    version: int
    version_origin: VersionOrigin
    deprecated: bool = False
    title: str = ""
    content: dict[str, object] = {}
    bindings: list[NodeBinding] = []


class RuntimeCandidate(ContractModel):
    """One already-loaded, already-authorized, liveness-checked runtime
    choice. Non-live entries (deleted/revoked machine) are skipped by
    selection, never an error — liveness was decided at load time."""

    level: RuntimeLevel
    kind: LibraryKind
    stable_key: str
    target: RuntimeTarget
    live: bool = True


class AgentResolutionSnapshot(ContractModel):
    """Complete pure input: root definition, every binding target reachable
    from it (including skill sub-rules), and every visible live runtime
    choice. No DB session, no principal, no I/O handle of any kind."""

    agent: ResolutionNode
    nodes: list[ResolutionNode] = []
    runtime_candidates: list[RuntimeCandidate] = []


def _fail(code: ResolutionErrorCode, **details: object) -> ResolutionFailure:
    return ResolutionFailure(ResolutionError(error_code=code, details=dict(details)))


def select_runtime(
    candidates: list[RuntimeCandidate],
    agent_key: tuple[LibraryKind, str],
    profile_key: tuple[LibraryKind, str] | None = None,
) -> RuntimeCandidate | None:
    """Single precedence implementation (P4 order, P5 strictness).

    Total order: `session > project_override > user > project_default >
    studio_default`; within a level the agent key wins over the linked model
    profile key (DEC-0068). Non-live candidates are skipped. Duplicate live
    entries for one `(level, key)` are conflicting input, never resolved by
    guesswork (`invalid_resolution_input`). Returns `None` when no level
    holds a live choice — a valid outcome, not an error."""

    keys = [agent_key] + ([profile_key] if profile_key is not None else [])
    for level in _LEVEL_ORDER:
        for key_kind, key_name in keys:
            matches = [
                c
                for c in candidates
                if c.live and c.level == level and c.kind == key_kind and c.stable_key == key_name
            ]
            if len(matches) > 1:
                raise _fail(
                    ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                    reason="duplicate_runtime_candidate",
                    level=level.value,
                    stable_key=key_name,
                )
            if matches:
                return matches[0]
    return None


def _node_provenance(
    node: ResolutionNode,
    source: ProvenanceSource,
    relation: BindingRelation | None = None,
    via: str | None = None,
) -> Provenance:
    return Provenance(
        source=source,
        resource_id=node.resource_id,
        stable_key=node.stable_key,
        scope=node.scope,
        version=node.version,
        version_origin=node.version_origin,
        locked=(node.version_origin == VersionOrigin.LOCK),
        relation=relation,
        via=via,
    )


def _pin_source(origin: VersionOrigin) -> ProvenanceSource:
    if origin == VersionOrigin.LOCK:
        return ProvenanceSource.PROJECT_LOCK
    if origin == VersionOrigin.ACTIVE:
        return ProvenanceSource.ACTIVE_POINTER
    return ProvenanceSource.VERSION_PIN


def resolve_agent(snapshot: AgentResolutionSnapshot) -> ResolvedAgentDefinition:
    """Pure assembly: snapshot in, resolved definition or structured error out.

    Pipeline: root validation → direct dependency partition → skill→rule
    transitive expansion (exactly one defined level) → rule dedup with merged
    paths → model-profile requirements → runtime selection → compatibility
    judgment (`selection → compatibility → success | structured
    incompatibility`, never `search until compatible`)."""

    root = snapshot.agent
    if root.kind != LibraryKind.AGENT_DEFINITION:
        raise _fail(
            ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
            reason="root_not_agent_definition",
            kind=root.kind.value,
        )

    index: dict[tuple[UUID, int], ResolutionNode] = {}
    for node in [root, *snapshot.nodes]:
        key = (node.resource_id, node.version)
        existing = index.get(key)
        if existing is not None and existing != node:
            raise _fail(
                ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                reason="conflicting_snapshot_node",
                resource_id=str(node.resource_id),
                version=node.version,
            )
        index[key] = node

    def _lookup(binding: NodeBinding, via: str) -> ResolutionNode:
        node = index.get((binding.target_resource_id, binding.target_version))
        if node is None:
            raise _fail(
                ResolutionErrorCode.UNRESOLVABLE_DEPENDENCY,
                reason="missing_snapshot_node",
                via=via,
                resource_id=str(binding.target_resource_id),
                version=binding.target_version,
            )
        return node

    def _checked_relation(
        source_kind: LibraryKind, binding: NodeBinding, node: ResolutionNode, via: str
    ) -> BindingRelation:
        expected = binding_relation_for(source_kind, node.kind)
        if expected is None or expected != binding.relation:
            raise _fail(
                ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                reason="forbidden_kind_pair_or_relation_mismatch",
                via=via,
            )
        return expected

    root_path = f"{root.kind.value}:{root.stable_key}"
    direct_rules: list[tuple[ResolutionNode, RulePath]] = []
    skill_nodes: list[ResolutionNode] = []
    profile_nodes: list[ResolutionNode] = []
    composed_nodes: list[ResolutionNode] = []
    workflow_nodes: list[ResolutionNode] = []

    for binding in root.bindings:
        node = _lookup(binding, root_path)
        relation = _checked_relation(root.kind, binding, node, root_path)
        if relation == BindingRelation.APPLIES_RULE:
            if node.kind != LibraryKind.RULE:
                raise _fail(
                    ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                    reason="rule_target_not_rule",
                    via=root_path,
                )
            direct_rules.append(
                (
                    node,
                    RulePath(
                        relation=relation,
                        via_kind=root.kind,
                        via_resource_id=root.resource_id,
                        via_stable_key=root.stable_key,
                        via_version=root.version,
                    ),
                )
            )
        elif relation == BindingRelation.USES_SKILL:
            skill_nodes.append(node)
        elif relation == BindingRelation.REQUIRES_MODEL_PROFILE:
            profile_nodes.append(node)
        elif relation == BindingRelation.COMPOSES_AGENT:
            composed_nodes.append(node)
        elif relation == BindingRelation.REFERENCES_WORKFLOW:
            workflow_nodes.append(node)
        else:  # pragma: no cover - matrix makes this unreachable for agents
            raise _fail(
                ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                reason="unexpected_agent_relation",
                via=root_path,
            )

    if len(profile_nodes) > 1:
        raise _fail(
            ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
            reason="too_many_model_profiles",
            stable_key=root.stable_key,
        )

    skills: list[ResolvedSkill] = []
    transitive_rules: list[tuple[ResolutionNode, RulePath]] = []
    for skill in skill_nodes:
        if skill.kind != LibraryKind.SKILL:
            raise _fail(
                ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                reason="skill_target_not_skill",
                via=root_path,
            )
        skills.append(
            ResolvedSkill(
                resource_id=skill.resource_id,
                stable_key=skill.stable_key,
                scope=skill.scope,
                version=skill.version,
                version_origin=skill.version_origin,
                deprecated=skill.deprecated,
                title=skill.title,
                content=dict(skill.content),
                provenance=_node_provenance(
                    skill,
                    _pin_source(skill.version_origin),
                    relation=BindingRelation.USES_SKILL,
                    via=root_path,
                ),
            )
        )
        skill_path = f"{root_path}>{skill.kind.value}:{skill.stable_key}"
        for binding in skill.bindings:
            rule = _lookup(binding, skill_path)
            relation = _checked_relation(skill.kind, binding, rule, skill_path)
            if relation != BindingRelation.REFINES_SKILL_RULE or rule.kind != LibraryKind.RULE:
                raise _fail(
                    ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                    reason="skill_binding_not_rule",
                    via=skill_path,
                )
            transitive_rules.append(
                (
                    rule,
                    RulePath(
                        relation=relation,
                        via_kind=skill.kind,
                        via_resource_id=skill.resource_id,
                        via_stable_key=skill.stable_key,
                        via_version=skill.version,
                    ),
                )
            )

    rules: list[ResolvedRule] = []
    rule_index: dict[UUID, ResolvedRule] = {}
    for node, path in [*direct_rules, *transitive_rules]:
        if node.kind != LibraryKind.RULE:
            raise _fail(
                ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                reason="rule_target_not_rule",
                via=f"{path.via_kind.value}:{path.via_stable_key}",
            )
        existing_rule = rule_index.get(node.resource_id)
        if existing_rule is None:
            resolved = ResolvedRule(
                resource_id=node.resource_id,
                stable_key=node.stable_key,
                scope=node.scope,
                version=node.version,
                version_origin=node.version_origin,
                deprecated=node.deprecated,
                title=node.title,
                content=dict(node.content),
                paths=[path],
            )
            rule_index[node.resource_id] = resolved
            rules.append(resolved)
        else:
            if existing_rule.version != node.version:
                raise _fail(
                    ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                    reason="rule_pinned_at_two_versions",
                    resource_id=str(node.resource_id),
                )
            existing_rule.paths.append(path)

    requirements = CapabilityRequirement()
    model_profile: ResolvedModelProfile | None = None
    profile_key: tuple[LibraryKind, str] | None = None
    if profile_nodes:
        profile = profile_nodes[0]
        if profile.kind != LibraryKind.MODEL_PROFILE:
            raise _fail(
                ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                reason="profile_target_not_model_profile",
                via=root_path,
            )
        raw_requirements = profile.content.get("requirements", {})
        if not isinstance(raw_requirements, dict):
            raise _fail(
                ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                reason="profile_requirements_not_object",
                via=root_path,
            )
        try:
            requirements = CapabilityRequirement.model_validate(dict(raw_requirements))
        except Exception as exc:
            raise _fail(
                ResolutionErrorCode.INVALID_RESOLUTION_INPUT,
                reason="profile_requirements_invalid",
                via=root_path,
            ) from exc
        profile_key = (profile.kind, profile.stable_key)
        model_profile = ResolvedModelProfile(
            resource_id=profile.resource_id,
            stable_key=profile.stable_key,
            scope=profile.scope,
            version=profile.version,
            version_origin=profile.version_origin,
            deprecated=profile.deprecated,
            title=profile.title,
            requirements=requirements,
            provenance=_node_provenance(
                profile,
                _pin_source(profile.version_origin),
                relation=BindingRelation.REQUIRES_MODEL_PROFILE,
                via=root_path,
            ),
        )

    def _preserved(node: ResolutionNode, relation: BindingRelation) -> PreservedReference:
        return PreservedReference(
            resource_id=node.resource_id,
            kind=node.kind,
            stable_key=node.stable_key,
            scope=node.scope,
            version=node.version,
            version_origin=node.version_origin,
            deprecated=node.deprecated,
            relation=relation,
            provenance=_node_provenance(
                node,
                _pin_source(node.version_origin),
                relation=relation,
                via=root_path,
            ),
        )

    composed_agents = [_preserved(node, BindingRelation.COMPOSES_AGENT) for node in composed_nodes]
    workflows = [_preserved(node, BindingRelation.REFERENCES_WORKFLOW) for node in workflow_nodes]

    agent_key = (LibraryKind.AGENT_DEFINITION, root.stable_key)
    winner = select_runtime(snapshot.runtime_candidates, agent_key, profile_key)
    runtime: ResolvedRuntime | None = None
    if winner is not None:
        capabilities = winner.target.capabilities or RuntimeCapabilities()
        unsatisfied = check_compatibility(requirements, capabilities)
        if unsatisfied:
            raise _fail(
                ResolutionErrorCode.RUNTIME_INCOMPATIBLE,
                level=winner.level.value,
                matched_kind=winner.kind.value,
                matched_stable_key=winner.stable_key,
                unsatisfied=list(unsatisfied),
            )
        runtime = ResolvedRuntime(
            target=winner.target,
            level=winner.level,
            matched_kind=winner.kind,
            matched_stable_key=winner.stable_key,
            compatible=True,
            unsatisfied=[],
            provenance=Provenance(
                source=(
                    ProvenanceSource.SESSION_OVERRIDE
                    if winner.level == RuntimeLevel.SESSION
                    else ProvenanceSource.RUNTIME_BINDING
                ),
                binding_level=winner.level,
                via=f"{winner.kind.value}:{winner.stable_key}",
            ),
        )

    return ResolvedAgentDefinition(
        agent=ResolvedAgent(
            resource_id=root.resource_id,
            kind=root.kind,
            stable_key=root.stable_key,
            scope=root.scope,
            version=root.version,
            version_origin=root.version_origin,
            deprecated=root.deprecated,
            title=root.title,
            content=dict(root.content),
            provenance=_node_provenance(
                root,
                _pin_source(root.version_origin),
                via=None,
            ),
        ),
        rules=rules,
        skills=skills,
        model_profile=model_profile,
        requirements=requirements,
        composed_agents=composed_agents,
        workflows=workflows,
        runtime=runtime,
    )
