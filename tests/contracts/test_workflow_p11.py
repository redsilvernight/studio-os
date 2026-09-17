from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_contracts.library import (
    BindingRelation,
    DependencyPin,
    LibraryKind,
    WorkflowContent,
    binding_relation_for,
    content_validation_errors,
    workflow_validation_errors,
)

WORKFLOW_SCHEMA = "studio.library.workflow/v1"


def _agent_pin(key: str) -> DependencyPin:
    return DependencyPin(kind=LibraryKind.AGENT_DEFINITION, stable_key=key, version=1)


def _code_change_participants() -> list[dict[str, object]]:
    return [
        {
            "participant_id": "implementer",
            "agent_stable_key": "code-writer",
            "inputs": [{"name": "task", "source": {"name": "task"}}],
            "outputs": [{"name": "patch"}],
        },
        {
            "participant_id": "tester",
            "agent_stable_key": "code-tester",
            "depends_on": ["implementer"],
            "inputs": [
                {"name": "patch", "source": {"participant_id": "implementer", "name": "patch"}}
            ],
            "outputs": [{"name": "test_report"}],
        },
        {
            "participant_id": "reviewer",
            "agent_stable_key": "code-reviewer",
            "depends_on": ["tester"],
            "inputs": [
                {"name": "patch", "source": {"participant_id": "implementer", "name": "patch"}},
                {
                    "name": "test_report",
                    "source": {"participant_id": "tester", "name": "test_report"},
                },
            ],
            "outputs": [{"name": "review_report"}],
        },
    ]


def _code_change_content() -> dict[str, object]:
    return {
        "content_schema": WORKFLOW_SCHEMA,
        "summary": "Implement, then test, then review a code change.",
        "participants": _code_change_participants(),
        "inputs": [{"name": "task"}, {"name": "repository_context"}],
        "outputs": [
            {"name": "patch", "source": {"participant_id": "implementer", "name": "patch"}},
            {"name": "test_report", "source": {"participant_id": "tester", "name": "test_report"}},
            {
                "name": "review_report",
                "source": {"participant_id": "reviewer", "name": "review_report"},
            },
        ],
    }


def _code_change_dependencies() -> list[DependencyPin]:
    return [_agent_pin("code-writer"), _agent_pin("code-tester"), _agent_pin("code-reviewer")]


def _single_participant(**overrides: object) -> list[dict[str, object]]:
    participant: dict[str, object] = {
        "participant_id": "implementer",
        "agent_stable_key": "code-writer",
    }
    participant.update(overrides)
    return [participant]


# --- Schema: valid / invalid -----------------------------------------------------


def test_code_change_workflow_is_schema_valid() -> None:
    assert content_validation_errors(LibraryKind.WORKFLOW, _code_change_content()) == []


def test_code_change_workflow_is_structurally_valid() -> None:
    assert workflow_validation_errors(_code_change_content(), _code_change_dependencies()) == []


def test_workflow_requires_a_schema_marker_and_participants() -> None:
    assert content_validation_errors(LibraryKind.WORKFLOW, {}) != []
    assert content_validation_errors(LibraryKind.WORKFLOW, {"participants": []}) != []


def test_workflow_rejects_wrong_content_schema() -> None:
    content = {**_code_change_content(), "content_schema": "studio.library.rule/v1"}
    assert content_validation_errors(LibraryKind.WORKFLOW, content) != []


# --- No runtime / execution data in the definition (P11 §53) ---------------------


@pytest.mark.parametrize(
    "runtime_key",
    [
        "machine_id",
        "runtime_id",
        "provider_ref",
        "model_ref",
        "provider",
        "model",
        "harness",
        "status",
        "started_at",
        "finished_at",
        "max_retries",
        "retry_delay",
        "timeout_seconds",
        "deadline",
        "output_value",
        "execution_result",
    ],
)
def test_workflow_content_rejects_runtime_and_execution_fields(runtime_key: str) -> None:
    content = {**_code_change_content(), runtime_key: "x"}
    assert content_validation_errors(LibraryKind.WORKFLOW, content) != []


@pytest.mark.parametrize(
    "runtime_key", ["status", "started_at", "attempt", "retry_count", "pid", "current_step"]
)
def test_participant_rejects_execution_fields(runtime_key: str) -> None:
    content = {
        "content_schema": WORKFLOW_SCHEMA,
        "participants": _single_participant(**{runtime_key: "x"}),
    }
    assert content_validation_errors(LibraryKind.WORKFLOW, content) != []


def test_workflow_content_model_declares_no_runtime_field() -> None:
    for forbidden in ("harness", "provider", "model", "runtime", "machine_id", "status"):
        assert forbidden not in WorkflowContent.model_fields


# --- Participant identity (P11 §8, §15) ------------------------------------------


def test_participant_id_rejects_empty_and_non_portable_syntax() -> None:
    for bad_id in ("", "1st", "with space", "a/b", "a.b", "é"):
        content = {
            "content_schema": WORKFLOW_SCHEMA,
            "participants": [{"participant_id": bad_id, "agent_stable_key": "code-writer"}],
        }
        assert content_validation_errors(LibraryKind.WORKFLOW, content) != []


def test_same_agent_definition_can_play_two_participant_roles() -> None:
    """§8: one `AgentDefinition` (one `composes_agent` pin) may appear under
    several participant ids — the pin is not duplicated, only the role is."""
    content = {
        "content_schema": WORKFLOW_SCHEMA,
        "participants": [
            {"participant_id": "security_review", "agent_stable_key": "generic-reviewer"},
            {"participant_id": "final_review", "agent_stable_key": "generic-reviewer"},
        ],
    }
    assert workflow_validation_errors(content, [_agent_pin("generic-reviewer")]) == []


def test_duplicate_participant_is_rejected() -> None:
    content = {
        "content_schema": WORKFLOW_SCHEMA,
        "participants": [
            {"participant_id": "tester", "agent_stable_key": "code-writer"},
            {"participant_id": "tester", "agent_stable_key": "code-tester"},
        ],
    }
    errors = workflow_validation_errors(content, _code_change_dependencies())
    assert errors == [{"reason": "duplicate_participant", "field": "participants.tester"}]


def test_unknown_participant_agent_is_rejected() -> None:
    content = {"content_schema": WORKFLOW_SCHEMA, "participants": _single_participant()}
    errors = workflow_validation_errors(content, [_agent_pin("some-other-agent")])
    assert errors == [
        {
            "reason": "unknown_participant_agent",
            "field": "participants.implementer.agent_stable_key",
        }
    ]


def test_unused_agent_dependency_is_rejected() -> None:
    content = {"content_schema": WORKFLOW_SCHEMA, "participants": _single_participant()}
    errors = workflow_validation_errors(content, _code_change_dependencies())
    assert errors[0]["reason"] == "unused_agent_dependency"


# --- Dependencies and DAG (P11 §10-14, §47-48) -----------------------------------


def test_unknown_dependency_is_rejected() -> None:
    content = {
        "content_schema": WORKFLOW_SCHEMA,
        "participants": _single_participant(depends_on=["ghost"]),
    }
    errors = workflow_validation_errors(content, [_agent_pin("code-writer")])
    assert errors == [
        {
            "reason": "unknown_dependency",
            "field": "participants.implementer.depends_on",
        }
    ]


def test_dependency_cycle_is_rejected() -> None:
    content = {
        "content_schema": WORKFLOW_SCHEMA,
        "participants": [
            {"participant_id": "a", "agent_stable_key": "a", "depends_on": ["c"]},
            {"participant_id": "b", "agent_stable_key": "b", "depends_on": ["a"]},
            {"participant_id": "c", "agent_stable_key": "c", "depends_on": ["b"]},
        ],
    }
    errors = workflow_validation_errors(content, [_agent_pin("a")])
    assert errors == [{"reason": "dependency_cycle", "field": "participants"}]


def test_self_dependency_is_a_cycle() -> None:
    content = {
        "content_schema": WORKFLOW_SCHEMA,
        "participants": _single_participant(depends_on=["implementer"]),
    }
    errors = workflow_validation_errors(content, [_agent_pin("code-writer")])
    assert errors == [{"reason": "dependency_cycle", "field": "participants"}]


def test_parallel_branches_are_accepted() -> None:
    """§47: two independent branches converging on a reviewer stay a valid DAG."""
    content = {
        "content_schema": WORKFLOW_SCHEMA,
        "participants": [
            {"participant_id": "implementer", "agent_stable_key": "writer"},
            {
                "participant_id": "tester",
                "agent_stable_key": "tester",
                "depends_on": ["implementer"],
            },
            {
                "participant_id": "documenter",
                "agent_stable_key": "writer-doc",
                "depends_on": ["implementer"],
            },
            {
                "participant_id": "reviewer",
                "agent_stable_key": "reviewer",
                "depends_on": ["tester", "documenter"],
            },
        ],
    }
    dependencies = [_agent_pin(key) for key in ("writer", "tester", "writer-doc", "reviewer")]
    assert workflow_validation_errors(content, dependencies) == []


def test_dependency_verdict_is_deterministic_and_order_independent() -> None:
    forward = _code_change_content()
    reversed_participants = list(reversed(_code_change_participants()))
    shuffled = {**forward, "participants": reversed_participants}
    expected = workflow_validation_errors(forward, _code_change_dependencies())
    assert expected == workflow_validation_errors(forward, _code_change_dependencies())
    assert workflow_validation_errors(shuffled, _code_change_dependencies()) == expected


# --- Inputs / outputs static coherence (P11 §21-24, §51) -------------------------


def test_workflow_output_without_source_is_rejected() -> None:
    content = {**_code_change_content(), "outputs": [{"name": "review_report"}]}
    errors = workflow_validation_errors(content, _code_change_dependencies())
    assert errors == [
        {
            "reason": "invalid_io_reference",
            "field": "workflow.outputs.review_report.source",
        }
    ]


def test_workflow_input_cannot_declare_a_source() -> None:
    content = {
        **_code_change_content(),
        "inputs": [{"name": "task", "source": {"name": "task"}}],
    }
    errors = workflow_validation_errors(content, _code_change_dependencies())
    assert errors[0]["reason"] == "invalid_io_reference"


def test_participant_input_referencing_unknown_workflow_input_is_rejected() -> None:
    participants = _code_change_participants()
    participants[0]["inputs"] = [{"name": "task", "source": {"name": "ghost"}}]
    content = {**_code_change_content(), "participants": participants}
    errors = workflow_validation_errors(content, _code_change_dependencies())
    assert errors[0]["reason"] == "invalid_io_reference"


def test_participant_input_referencing_unknown_output_is_rejected() -> None:
    participants = _code_change_participants()
    participants[2]["inputs"] = [
        {"name": "patch", "source": {"participant_id": "implementer", "name": "ghost"}}
    ]
    content = {**_code_change_content(), "participants": participants}
    errors = workflow_validation_errors(content, _code_change_dependencies())
    assert errors[0]["reason"] == "invalid_io_reference"


def test_participant_cannot_consume_its_own_output() -> None:
    participants = _code_change_participants()
    participants[0]["inputs"] = [
        {"name": "patch", "source": {"participant_id": "implementer", "name": "patch"}}
    ]
    content = {**_code_change_content(), "participants": participants}
    errors = workflow_validation_errors(content, _code_change_dependencies())
    assert errors[0]["reason"] == "invalid_io_reference"


def test_participant_output_cannot_declare_a_source() -> None:
    participants = _code_change_participants()
    participants[1]["outputs"] = [{"name": "test_report", "source": {"name": "x"}}]
    content = {**_code_change_content(), "participants": participants}
    errors = workflow_validation_errors(content, _code_change_dependencies())
    assert errors[0]["reason"] == "invalid_io_reference"


def test_duplicate_io_names_are_rejected() -> None:
    participants = _code_change_participants()
    participants[0]["inputs"] = [{"name": "task"}, {"name": "task"}]
    content = {**_code_change_content(), "participants": participants}
    errors = workflow_validation_errors(content, _code_change_dependencies())
    assert errors[0]["reason"] == "duplicate_io_declaration"


# --- Library bindings reused, never duplicated (P11 §16-17) ----------------------


def test_workflow_binding_matrix_covers_rules_skills_and_agents() -> None:
    assert binding_relation_for(LibraryKind.WORKFLOW, LibraryKind.RULE) == (
        BindingRelation.APPLIES_RULE
    )
    assert binding_relation_for(LibraryKind.WORKFLOW, LibraryKind.SKILL) == (
        BindingRelation.USES_SKILL
    )
    assert binding_relation_for(LibraryKind.WORKFLOW, LibraryKind.AGENT_DEFINITION) == (
        BindingRelation.COMPOSES_AGENT
    )
    assert binding_relation_for(LibraryKind.WORKFLOW, LibraryKind.MODEL_PROFILE) is None


# --- Harness neutrality (P11 §58) ------------------------------------------------


@pytest.mark.parametrize("token", ["claude", "opencode", "anthropic", "openai", "ollama"])
def test_workflow_schema_knows_no_harness_or_vendor(token: str) -> None:
    schema = json.dumps(WorkflowContent.model_json_schema()).lower()
    assert token not in schema


# --- Generic consumer (P11 §59): definition is readable outside Studi'OS ---------


def _topological_order(workflow: WorkflowContent) -> list[str]:
    remaining = {p.participant_id: set(p.depends_on) for p in workflow.participants}
    order: list[str] = []
    while remaining:
        ready = sorted(name for name, deps in remaining.items() if not deps)
        assert ready, "a valid workflow definition must stay acyclic"
        for name in ready:
            del remaining[name]
        for deps in remaining.values():
            deps.difference_update(ready)
        order.extend(ready)
    return order


def test_a_generic_consumer_can_read_the_canonical_definition() -> None:
    """No server service, no harness SDK, no I/O: a plain consumer of the
    canonical contract can derive a static order from the definition alone."""
    workflow = WorkflowContent.model_validate(_code_change_content())
    order = _topological_order(workflow)
    assert order == ["implementer", "tester", "reviewer"]
    assert order.index("implementer") < order.index("tester") < order.index("reviewer")
    assert [p.participant_id for p in workflow.participants] == [
        "implementer",
        "tester",
        "reviewer",
    ]


# --- VPS boundary guard (P11 §52) ------------------------------------------------


def test_no_server_side_workflow_execution_concepts_exist() -> None:
    """P11 stores definitions only. `scheduler`/`worker`/`queue` are *not*
    scanned: the Studio Producer already owns legitimate build workers
    (DEC-0059), and GitHub's own `workflow_runs` field appears in the producer
    integration — none of that is workflow orchestration. The tokens below
    are execution concepts specific to running a workflow definition."""
    repo_root = Path(__file__).resolve().parents[2]
    roots = [
        repo_root / "services" / "api" / "src",
        repo_root / "services" / "mcp" / "src",
        repo_root / "packages" / "studio-contracts" / "src",
        repo_root / "packages" / "studio-client" / "src",
    ]
    forbidden = (
        "WorkflowRun",
        "WorkflowExecution",
        "WorkflowStepRun",
        "RunStatus",
        "ExecutionStatus",
        "run_workflow",
        "execute_workflow",
        "execute_step",
        "next_step",
        "schedule_workflow",
    )
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    offenders.append(f"{path.relative_to(repo_root)}:{token}")
    assert offenders == []
