"""P5 Resolution Engine — pure tests (no DB, no I/O, no LLM).

Every test builds in-memory `AgentResolutionSnapshot` fixtures and calls the
pure core directly. Determinism, precedence, provenance, strict
compatibility (no silent fallback) and harness/provider neutrality are
proven here; the DB loader boundary is covered in
`test_resolution_service.py`."""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from studio_contracts.library import (
    BindingRelation,
    LibraryKind,
    LibraryScope,
    VersionOrigin,
)
from studio_contracts.resolution import (
    AgentResolutionSnapshot,
    NodeBinding,
    ResolutionErrorCode,
    ResolutionFailure,
    ResolutionNode,
    RuntimeCandidate,
    resolve_agent,
    select_runtime,
)
from studio_contracts.runtime import RuntimeLevel, RuntimeTarget

AGENT = LibraryKind.AGENT_DEFINITION
RULE = LibraryKind.RULE
SKILL = LibraryKind.SKILL
PROFILE = LibraryKind.MODEL_PROFILE
WORKFLOW = LibraryKind.WORKFLOW


def _rid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"studio-os:p5:{name}")


def _agent_content() -> dict[str, object]:
    return {
        "content_schema": "studio.library.agent_definition/v1",
        "summary": "Pure fixture agent.",
    }


def _rule_content(text: str = "Obey.") -> dict[str, object]:
    return {"content_schema": "studio.library.rule/v1", "text": text}


def _skill_content(text: str = "Do things.") -> dict[str, object]:
    return {"content_schema": "studio.library.skill/v1", "text": text}


def _profile_content(**requirements: object) -> dict[str, object]:
    return {
        "content_schema": "studio.library.model_profile/v1",
        "requirements": dict(requirements),
        "description": "Pure fixture profile.",
    }


def _node(
    kind: LibraryKind,
    key: str,
    content: dict[str, object],
    bindings: list[NodeBinding] | None = None,
    version: int = 1,
    origin: VersionOrigin = VersionOrigin.PIN,
) -> ResolutionNode:
    return ResolutionNode(
        resource_id=_rid(f"{kind.value}:{key}:v{version}"),
        kind=kind,
        stable_key=key,
        scope=LibraryScope.STUDIO,
        version=version,
        version_origin=origin,
        deprecated=False,
        title=f"{key} title",
        content=content,
        bindings=bindings or [],
    )


def _pin(relation: BindingRelation, target: ResolutionNode) -> NodeBinding:
    return NodeBinding(
        relation=relation,
        target_resource_id=target.resource_id,
        target_version=target.version,
    )


def _target(**capabilities: object) -> RuntimeTarget:
    return RuntimeTarget(
        provider_ref="provider_a",
        model_ref="model_a",
        capabilities={"reasoning": None, **capabilities},  # type: ignore[dict-item]
    )


def _candidate(
    level: RuntimeLevel,
    kind: LibraryKind,
    key: str,
    target: RuntimeTarget | None = None,
    live: bool = True,
) -> RuntimeCandidate:
    return RuntimeCandidate(
        level=level,
        kind=kind,
        stable_key=key,
        target=target or _target(),
        live=live,
    )


def _snapshot(
    agent: ResolutionNode,
    nodes: list[ResolutionNode] | None = None,
    candidates: list[RuntimeCandidate] | None = None,
) -> AgentResolutionSnapshot:
    return AgentResolutionSnapshot(
        agent=agent, nodes=nodes or [], runtime_candidates=candidates or []
    )


def test_simple_assembly_rule_skill_profile() -> None:
    rule = _node(RULE, "r1", _rule_content())
    skill = _node(SKILL, "s1", _skill_content())
    profile = _node(PROFILE, "m", _profile_content(coding=True))
    agent = _node(
        AGENT,
        "a",
        _agent_content(),
        bindings=[
            _pin(BindingRelation.APPLIES_RULE, rule),
            _pin(BindingRelation.USES_SKILL, skill),
            _pin(BindingRelation.REQUIRES_MODEL_PROFILE, profile),
        ],
        origin=VersionOrigin.ACTIVE,
    )
    resolved = resolve_agent(_snapshot(agent, [rule, skill, profile]))

    assert resolved.agent.stable_key == "a"
    assert resolved.agent.version_origin == VersionOrigin.ACTIVE
    assert [r.stable_key for r in resolved.rules] == ["r1"]
    assert [s.stable_key for s in resolved.skills] == ["s1"]
    assert resolved.model_profile is not None
    assert resolved.model_profile.stable_key == "m"
    assert resolved.requirements.coding is True
    assert resolved.runtime is None
    assert resolved.agent.provenance.source.value == "active_pointer"
    assert resolved.rules[0].paths[0].relation == BindingRelation.APPLIES_RULE


def test_pins_keep_exact_versions() -> None:
    rule = _node(RULE, "r1", _rule_content(), version=1, origin=VersionOrigin.PIN)
    agent = _node(AGENT, "a", _agent_content(), bindings=[_pin(BindingRelation.APPLIES_RULE, rule)])
    resolved = resolve_agent(_snapshot(agent, [rule]))

    assert resolved.rules[0].version == 1
    assert resolved.rules[0].version_origin == VersionOrigin.PIN


def test_skill_to_rule_transitive() -> None:
    sub = _node(RULE, "r2", _rule_content("Sub."))
    skill = _node(
        SKILL,
        "s1",
        _skill_content(),
        bindings=[_pin(BindingRelation.REFINES_SKILL_RULE, sub)],
    )
    agent = _node(AGENT, "a", _agent_content(), bindings=[_pin(BindingRelation.USES_SKILL, skill)])
    resolved = resolve_agent(_snapshot(agent, [skill, sub]))

    assert [r.stable_key for r in resolved.rules] == ["r2"]
    (path,) = resolved.rules[0].paths
    assert path.relation == BindingRelation.REFINES_SKILL_RULE
    assert path.via_kind == SKILL
    assert path.via_stable_key == "s1"


def test_dedup_rule_reached_by_two_paths_keeps_both() -> None:
    shared = _node(RULE, "rx", _rule_content("Shared."))
    skill = _node(
        SKILL,
        "s1",
        _skill_content(),
        bindings=[_pin(BindingRelation.REFINES_SKILL_RULE, shared)],
    )
    agent = _node(
        AGENT,
        "a",
        _agent_content(),
        bindings=[
            _pin(BindingRelation.APPLIES_RULE, shared),
            _pin(BindingRelation.USES_SKILL, skill),
        ],
    )
    resolved = resolve_agent(_snapshot(agent, [shared, skill]))

    assert len(resolved.rules) == 1
    assert len(resolved.rules[0].paths) == 2
    relations = {p.relation for p in resolved.rules[0].paths}
    assert relations == {
        BindingRelation.APPLIES_RULE,
        BindingRelation.REFINES_SKILL_RULE,
    }


def test_no_profile_means_no_implicit_requirements() -> None:
    agent = _node(AGENT, "a", _agent_content())
    resolved = resolve_agent(_snapshot(agent))

    assert resolved.model_profile is None
    assert resolved.requirements.coding is False
    assert resolved.requirements.tools_required == []


def test_agent_binding_beats_profile_binding_at_same_level() -> None:
    profile = _node(PROFILE, "m", _profile_content())
    agent = _node(
        AGENT,
        "a",
        _agent_content(),
        bindings=[_pin(BindingRelation.REQUIRES_MODEL_PROFILE, profile)],
    )
    agent_target = _target()
    profile_target = _target()
    resolved = resolve_agent(
        _snapshot(
            agent,
            [profile],
            [
                _candidate(RuntimeLevel.USER, PROFILE, "m", profile_target),
                _candidate(RuntimeLevel.USER, AGENT, "a", agent_target),
            ],
        )
    )

    assert resolved.runtime is not None
    assert resolved.runtime.matched_kind == AGENT
    assert resolved.runtime.target == agent_target


@pytest.mark.parametrize(
    ("levels", "expected"),
    [
        ([RuntimeLevel.STUDIO_DEFAULT], RuntimeLevel.STUDIO_DEFAULT),
        (
            [RuntimeLevel.STUDIO_DEFAULT, RuntimeLevel.PROJECT_DEFAULT],
            RuntimeLevel.PROJECT_DEFAULT,
        ),
        (
            [RuntimeLevel.PROJECT_DEFAULT, RuntimeLevel.USER],
            RuntimeLevel.USER,
        ),
        (
            [RuntimeLevel.USER, RuntimeLevel.PROJECT_OVERRIDE],
            RuntimeLevel.PROJECT_OVERRIDE,
        ),
        (
            [RuntimeLevel.PROJECT_OVERRIDE, RuntimeLevel.SESSION],
            RuntimeLevel.SESSION,
        ),
        (
            [
                RuntimeLevel.STUDIO_DEFAULT,
                RuntimeLevel.PROJECT_DEFAULT,
                RuntimeLevel.USER,
                RuntimeLevel.PROJECT_OVERRIDE,
                RuntimeLevel.SESSION,
            ],
            RuntimeLevel.SESSION,
        ),
    ],
)
def test_precedence_total_order(levels: list[RuntimeLevel], expected: RuntimeLevel) -> None:
    agent = _node(AGENT, "a", _agent_content())
    candidates = [_candidate(level, AGENT, "a") for level in levels]
    resolved = resolve_agent(_snapshot(agent, [], candidates))

    assert resolved.runtime is not None
    assert resolved.runtime.level == expected
    assert resolved.runtime.provenance is not None
    assert resolved.runtime.provenance.binding_level == expected


def test_precedence_falls_to_next_when_higher_absent() -> None:
    agent = _node(AGENT, "a", _agent_content())
    resolved = resolve_agent(
        _snapshot(agent, [], [_candidate(RuntimeLevel.STUDIO_DEFAULT, AGENT, "a")])
    )

    assert resolved.runtime is not None
    assert resolved.runtime.level == RuntimeLevel.STUDIO_DEFAULT


def test_non_live_candidate_is_skipped_not_error() -> None:
    winner = select_runtime(
        [
            _candidate(RuntimeLevel.USER, AGENT, "a", live=False),
            _candidate(RuntimeLevel.STUDIO_DEFAULT, AGENT, "a"),
        ],
        (AGENT, "a"),
    )

    assert winner is not None
    assert winner.level == RuntimeLevel.STUDIO_DEFAULT


def test_incompatible_winner_is_structured_error_without_fallback() -> None:
    profile = _node(PROFILE, "m", _profile_content(coding=True))
    agent = _node(
        AGENT,
        "a",
        _agent_content(),
        bindings=[_pin(BindingRelation.REQUIRES_MODEL_PROFILE, profile)],
    )
    bad = _target(coding=False)
    good = _target(coding=True)
    with pytest.raises(ResolutionFailure) as exc_info:
        resolve_agent(
            _snapshot(
                agent,
                [profile],
                [
                    _candidate(RuntimeLevel.PROJECT_OVERRIDE, AGENT, "a", bad),
                    _candidate(RuntimeLevel.STUDIO_DEFAULT, AGENT, "a", good),
                ],
            )
        )

    error = exc_info.value.error
    assert error.error_code == ResolutionErrorCode.RUNTIME_INCOMPATIBLE
    assert error.details["level"] == RuntimeLevel.PROJECT_OVERRIDE.value
    assert error.details["unsatisfied"] == ["coding: required"]


def test_unknown_capability_is_not_compatible() -> None:
    profile = _node(PROFILE, "m", _profile_content(reasoning="deep"))
    agent = _node(
        AGENT,
        "a",
        _agent_content(),
        bindings=[_pin(BindingRelation.REQUIRES_MODEL_PROFILE, profile)],
    )
    unknown = RuntimeTarget(provider_ref="provider_a")
    with pytest.raises(ResolutionFailure) as exc_info:
        resolve_agent(
            _snapshot(agent, [profile], [_candidate(RuntimeLevel.USER, AGENT, "a", unknown)])
        )

    assert exc_info.value.error.error_code == ResolutionErrorCode.RUNTIME_INCOMPATIBLE


def test_no_runtime_is_valid_with_null_target() -> None:
    profile = _node(PROFILE, "m", _profile_content(coding=True))
    agent = _node(
        AGENT,
        "a",
        _agent_content(),
        bindings=[_pin(BindingRelation.REQUIRES_MODEL_PROFILE, profile)],
    )
    resolved = resolve_agent(_snapshot(agent, [profile]))

    assert resolved.runtime is None
    assert resolved.requirements.coding is True


def test_missing_dependency_node_is_unresolvable() -> None:
    ghost = _node(RULE, "ghost", _rule_content())
    agent = _node(
        AGENT, "a", _agent_content(), bindings=[_pin(BindingRelation.APPLIES_RULE, ghost)]
    )
    with pytest.raises(ResolutionFailure) as exc_info:
        resolve_agent(_snapshot(agent, []))

    assert exc_info.value.error.error_code == ResolutionErrorCode.UNRESOLVABLE_DEPENDENCY


def test_root_not_agent_definition_is_invalid_input() -> None:
    rule = _node(RULE, "r1", _rule_content(), origin=VersionOrigin.ACTIVE)
    with pytest.raises(ResolutionFailure) as exc_info:
        resolve_agent(_snapshot(rule))

    assert exc_info.value.error.error_code == ResolutionErrorCode.INVALID_RESOLUTION_INPUT


def test_two_model_profiles_is_invalid_input() -> None:
    first = _node(PROFILE, "m1", _profile_content())
    second = _node(PROFILE, "m2", _profile_content())
    agent = _node(
        AGENT,
        "a",
        _agent_content(),
        bindings=[
            _pin(BindingRelation.REQUIRES_MODEL_PROFILE, first),
            _pin(BindingRelation.REQUIRES_MODEL_PROFILE, second),
        ],
    )
    with pytest.raises(ResolutionFailure) as exc_info:
        resolve_agent(_snapshot(agent, [first, second]))

    assert exc_info.value.error.error_code == ResolutionErrorCode.INVALID_RESOLUTION_INPUT


def test_duplicate_live_candidates_are_invalid_input() -> None:
    with pytest.raises(ResolutionFailure) as exc_info:
        select_runtime(
            [
                _candidate(RuntimeLevel.USER, AGENT, "a"),
                _candidate(RuntimeLevel.USER, AGENT, "a"),
            ],
            (AGENT, "a"),
        )

    assert exc_info.value.error.error_code == ResolutionErrorCode.INVALID_RESOLUTION_INPUT


def test_composed_agents_and_workflows_preserved_not_expanded() -> None:
    other = _node(AGENT, "other", _agent_content(), origin=VersionOrigin.ACTIVE)
    flow = _node(WORKFLOW, "flow", {"note": "free-form until P11"}, origin=VersionOrigin.ACTIVE)
    agent = _node(
        AGENT,
        "a",
        _agent_content(),
        bindings=[
            _pin(BindingRelation.COMPOSES_AGENT, other),
            _pin(BindingRelation.REFERENCES_WORKFLOW, flow),
        ],
    )
    resolved = resolve_agent(_snapshot(agent, [other, flow]))

    assert [r.stable_key for r in resolved.composed_agents] == ["other"]
    assert [r.stable_key for r in resolved.workflows] == ["flow"]
    assert resolved.rules == []
    assert resolved.skills == []
    assert resolved.composed_agents[0].relation == BindingRelation.COMPOSES_AGENT
    assert resolved.workflows[0].relation == BindingRelation.REFERENCES_WORKFLOW


def test_deterministic_same_snapshot_same_result() -> None:
    rule = _node(RULE, "r1", _rule_content())
    skill = _node(SKILL, "s1", _skill_content())
    profile = _node(PROFILE, "m", _profile_content(coding=True))
    agent = _node(
        AGENT,
        "a",
        _agent_content(),
        bindings=[
            _pin(BindingRelation.APPLIES_RULE, rule),
            _pin(BindingRelation.USES_SKILL, skill),
            _pin(BindingRelation.REQUIRES_MODEL_PROFILE, profile),
        ],
        origin=VersionOrigin.LOCK,
    )
    candidates = [
        _candidate(RuntimeLevel.SESSION, AGENT, "a", _target(coding=True)),
        _candidate(RuntimeLevel.STUDIO_DEFAULT, AGENT, "a", _target(coding=True)),
    ]

    first = resolve_agent(_snapshot(agent, [rule, skill, profile], candidates))
    second = resolve_agent(_snapshot(agent, [rule, skill, profile], list(reversed(candidates))))

    assert first == second
    assert first.model_dump() == second.model_dump()
    assert first.agent.provenance.locked is True


def test_result_is_harness_and_provider_neutral() -> None:
    rule = _node(RULE, "r1", _rule_content("Neutral text."))
    agent = _node(AGENT, "a", _agent_content(), bindings=[_pin(BindingRelation.APPLIES_RULE, rule)])
    target = RuntimeTarget(
        provider_ref="provider_a",
        model_ref="model_a",
        capabilities={},
    )
    resolved = resolve_agent(
        _snapshot(agent, [rule], [_candidate(RuntimeLevel.USER, AGENT, "a", target)])
    )

    dumped = resolved.model_dump_json().lower()
    for vendor in ("claude", "anthropic", "openai", "ollama", "kimi", "cursor", "continue"):
        assert vendor not in dumped
    assert resolved.runtime is not None
    assert resolved.runtime.target.provider_ref == "provider_a"
    assert resolved.runtime.target.model_ref == "model_a"


def test_pure_core_has_no_infrastructure_imports() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "studio-contracts"
        / "src"
        / "studio_contracts"
        / "resolution.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = {"__future__", "enum", "uuid", "pydantic", "studio_contracts"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= allowed, f"infrastructure imports leaked: {imported - allowed}"
