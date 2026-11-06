"""SIMULATED P1 traces, not live agent/LLM trials or MCP integration tests.

The assertions below are test-only trace oracles: no server, database, agent,
claim, session or durable storage is exercised. Negative traces check that the
oracles reject their named failure. Canonical instructions remain the policy;
passing these examples does not demonstrate that a model follows that policy.
Run without the repository infrastructure conftest with --noconftest.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from studio_contracts.completion import CompletionEvidence, check_completion
from studio_mcp.access_registry import MCP_ACCESS
from studio_mcp.tool_profiles import (
    normalise_tool_profile,
    resolve_tool_profile,
    tools_for_profile,
)

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "00000000-0000-0000-0000-000000000001"
AGENT = "00000000-0000-0000-0000-000000000002"
TASK = "00000000-0000-0000-0000-000000000003"
SESSION = "00000000-0000-0000-0000-000000000004"
DEFINITION = "00000000-0000-0000-0000-000000000005"
HASH = "a" * 64
START = {"project_id": PROJECT, "agent_id": AGENT, "task_id": TASK}
PREPARE = {"project_id": PROJECT, "task_id": TASK}
RULE = ".agents/rules/studio-protocol.md"
TASK_SKILL = ".agents/skills/studio-task/SKILL.md"
CONTEXT_SKILL = ".agents/skills/studio-context/SKILL.md"
HANDOFF_SKILL = ".agents/skills/studio-handoff/SKILL.md"
COMPLETION_RULES = ".agents/skills/studio-task/references/completion.md"
ROLES = ".agents/skills/studio-task/references/roles.md"


def _signature(tool: str) -> inspect.Signature:
    """Resolve the actual server registration and imported function using AST."""
    server = ast.parse((ROOT / "services/mcp/src/studio_mcp/server.py").read_text("utf-8"))
    registrations = [
        node
        for node in ast.walk(server)
        if isinstance(node, ast.Call)
        and any(
            k.arg == "name" and isinstance(k.value, ast.Constant) and k.value.value == tool
            for k in node.keywords
        )
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == tool
    ]
    assert registrations, f"{tool} is not registered in server.py"
    module = next(
        node.module
        for node in server.body
        if isinstance(node, ast.ImportFrom) and any(alias.name == tool for alias in node.names)
    )
    assert module is not None
    source = ROOT / "services/mcp/src" / (module.replace(".", "/") + ".py")
    function = next(
        node
        for node in ast.parse(source.read_text("utf-8")).body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == tool
    )
    args = function.args.args
    first_default = len(args) - len(function.args.defaults)
    return inspect.Signature(
        [
            inspect.Parameter(
                arg.arg,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=inspect.Parameter.empty if index < first_default else None,
            )
            for index, arg in enumerate(args)
        ]
    )


@dataclass(frozen=True)
class Call:
    tool: str
    args: dict[str, Any]

    def __post_init__(self) -> None:
        _signature(self.tool).bind(ctx=object(), **self.args)


def _policy(path: str, *markers: str) -> None:
    text = " ".join((ROOT / path).read_text("utf-8").split())
    for marker in markers:
        assert marker in text, f"Update scenario policy anchor: {path}: {marker}"


def _one_start_without_refetch(trace: list[Call]) -> None:
    assert [call.tool for call in trace].count("studio_start_work") == 1
    assert not any(call.tool == "studio_prepare_context" for call in trace)


@pytest.mark.parametrize("extra_fetch", [False, True], ids=["retained", "reject-double-fetch"])
def test_simulated_followup_retains_initial_context(extra_fetch: bool) -> None:
    _policy(RULE, "studio_start_work", "studio_prepare_context")
    trace = [Call("studio_start_work", START), Call("studio_sync", {"session_id": SESSION})]
    if extra_fetch:
        trace.append(Call("studio_prepare_context", PREPARE))
        with pytest.raises(AssertionError):
            _one_start_without_refetch(trace)
    else:
        _one_start_without_refetch(trace)


def test_simulated_readonly_audit_uses_prepare_without_mutations() -> None:
    _policy(CONTEXT_SKILL, "studio_prepare_context")
    trace = [Call("studio_prepare_context", {**PREPARE, "objective": "readonly audit"})]
    assert [call.tool for call in trace] == ["studio_prepare_context"]
    assert _signature("studio_prepare_context").parameters.get("idempotency_key") is None
    with pytest.raises(AssertionError):
        assert [call.tool for call in [*trace, Call("studio_start_work", START)]] == [
            "studio_prepare_context"
        ]


def _retained_hashes(known_ids: dict[str, str], retained: dict[str, dict[str, str]]) -> None:
    assert all(
        key in retained and retained[key]["content_hash"] == value
        for key, value in known_ids.items()
    )


@pytest.mark.parametrize("retained", [True, False], ids=["retained-hash", "zero-history"])
def test_simulated_known_ids_require_retained_content(retained: bool) -> None:
    retained_content = {DEFINITION: {"content_hash": HASH, "text": "canonical rule"}}
    if not retained:
        retained_content = {}
    known_ids = {key: value["content_hash"] for key, value in retained_content.items()}
    call = Call("studio_prepare_context", {**PREPARE, "known_ids": known_ids})
    _retained_hashes(call.args["known_ids"], retained_content)
    assert call.args["known_ids"] == ({DEFINITION: HASH} if retained else {})
    response = {"id": DEFINITION, "content_hash": HASH, "unchanged": retained}
    assert not response["unchanged"] or DEFINITION in retained_content
    if not retained:
        assert HASH not in call.args["known_ids"].values()
        with pytest.raises(AssertionError):
            _retained_hashes({DEFINITION: HASH}, retained_content)


def test_simulated_claim_conflict_is_warn_only_and_acknowledged_in_plan() -> None:
    _policy(TASK_SKILL, "quoted data", "studio_coordinate")
    claim = Call(
        "studio_claim_resources",
        {
            "project_id": PROJECT,
            "paths": ["src/shared.py"],
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )
    warning = {"event_type": "resource.conflict", "resource_path": "src/shared.py"}
    plan = {"warned_paths": [warning["resource_path"]], "action": "coordinate then edit"}
    assert claim.args["paths"] == plan["warned_paths"]
    assert plan["action"] == "coordinate then edit"


def _durable_before_ack(trace: list[dict[str, Any]]) -> None:
    for index, step in enumerate(trace):
        if step["action"] == "ack":
            assert any(
                previous["action"] == "persist" and previous["cursor"] == step["cursor"]
                for previous in trace[:index]
            )


def _effects_once(delivered: list[str], effects: list[str]) -> None:
    assert set(delivered) == set(effects)
    assert len(effects) == len(set(effects))


@pytest.mark.parametrize("early_ack", [False, True], ids=["durable", "reject-early-ack"])
def test_simulated_signal_redelivery_and_ack_order(early_ack: bool) -> None:
    _policy(TASK_SKILL, "next_cursor", "event_id", "durably")
    delivered = ["event-1", "event-1"]
    recorded_effects = ["event-1"]
    _effects_once(delivered, recorded_effects)
    with pytest.raises(AssertionError):
        _effects_once(delivered, ["event-1", "event-1"])
    trace = [{"action": "persist", "cursor": 7}, {"action": "ack", "cursor": 7}]
    if early_ack:
        with pytest.raises(AssertionError):
            _durable_before_ack(list(reversed(trace)))
    else:
        _durable_before_ack(trace)
        call = Call("studio_sync", {"session_id": SESSION, "ack": 7})
        assert call.args["ack"] == 7


def test_simulated_handoff_ack_is_not_an_implicit_sync_ack() -> None:
    _policy(HANDOFF_SKILL, "warnings", "NOT automatically acknowledged", "durably")
    acknowledgement = {"warnings": ["unacknowledged sync"], "handoff_cursor_seq": 7}
    trace = [Call("studio_handoff", {"project_id": PROJECT, "session_id": SESSION})]
    assert acknowledgement["warnings"]
    assert not any(call.tool == "studio_sync" for call in trace)
    assert "ack" not in _signature("studio_handoff").parameters


@pytest.mark.parametrize("kind", ["code", "audit", "diagnostic", "operation"])
def test_simulated_failed_validation_cannot_complete(kind: str) -> None:
    _policy(TASK_SKILL, "Failed or unavailable", "never false completion")
    evidence = CompletionEvidence.model_validate(
        {
            "kind": kind,
            "artifacts": ["report.txt"],
            "versioned": True,
            "revision": "abc123",
            "effect_verified": True,
            "checks": [{"name": "unit tests", "status": "failed", "exit_code": 1}],
        }
    )
    report = check_completion(evidence)
    assert not report.ready
    assert "validation_not_passed:0" in report.issues


def test_simulated_audit_finding_failure_is_distinct_from_validation() -> None:
    _policy(COMPLETION_RULES, "finding", "validation")
    evidence = CompletionEvidence.model_validate(
        {
            "kind": "audit",
            "artifacts": ["audit.json"],
            "checks": [
                {
                    "name": "observed broken build",
                    "purpose": "finding",
                    "status": "failed",
                    "exit_code": 1,
                },
                {"name": "validate audit artifact", "status": "passed", "exit_code": 0},
            ],
        }
    )
    assert check_completion(evidence).ready
    assert not check_completion(evidence.model_copy(update={"checks": evidence.checks[:1]})).ready


def test_simulated_contract_specialty_is_loaded_only_for_real_trigger() -> None:
    _policy(TASK_SKILL, "specialist expertise", "contract-change")
    _policy(ROLES, "contract")
    trace = [
        Call("studio_start_work", START),
        Call(
            "studio_resolve_agent",
            {
                "stable_key": "contract-guardian",
                "project_id": PROJECT,
            },
        ),
    ]
    trigger = "contract change"
    delegation = {
        "trigger": trigger,
        "role": "contract guardian",
        "files": ["packages/studio-contracts/src/studio_contracts/completion.py"],
    }
    assert trace[0].tool == "studio_start_work"
    assert trace[1].args["stable_key"] == "contract-guardian"
    assert delegation["trigger"] and delegation["files"]
    assert delegation["role"] == "contract guardian"


def test_simulated_simple_task_has_no_subagent() -> None:
    _policy(TASK_SKILL, "Simple work needs no artificial subagent")
    scenario = {"trigger": None, "delegations": [], "calls": [Call("studio_start_work", START)]}
    assert scenario["trigger"] is None
    assert scenario["delegations"] == []


@pytest.mark.parametrize("changed_args", [False, True], ids=["same-retry", "reject-changed-retry"])
def test_simulated_retry_preserves_key_and_payload(changed_args: bool) -> None:
    _policy(RULE, "idempotency_key")
    initial = Call("studio_start_work", {**START, "idempotency_key": "stable-key"})
    retry = Call(
        initial.tool,
        {
            **initial.args,
            **({"objective": "different"} if changed_args else {}),
        },
    )
    if changed_args:
        with pytest.raises(AssertionError):
            assert retry == initial
    else:
        assert retry == initial


def test_simulated_409_rereads_merges_then_retries_current_version() -> None:
    _policy(TASK_SKILL, "409", "reread", "merge", "expected_version")
    first = Call("studio_update_task", {"task_id": TASK, "expected_version": 2, "title": "mine"})
    error = {"error_code": "version_conflict", "server_version": 3}
    reread = Call("studio_get_task", {"task_id": TASK})
    current = {"version": 3, "description": "teammate's change"}
    retry = Call(
        "studio_update_task",
        {
            "task_id": TASK,
            "expected_version": current["version"],
            "title": "mine",
            "description": current["description"],
        },
    )
    assert reread.tool == "studio_get_task"
    assert first.args["expected_version"] < retry.args["expected_version"]
    assert retry.args["expected_version"] == error["server_version"]
    assert retry.args["description"] == current["description"]


def test_simulated_interruption_resumes_from_persisted_checkpoint() -> None:
    _policy(HANDOFF_SKILL, "NEXT", "BLOCKERS", "durable processing references")
    durable: dict[str, Any] = {
        "summary": "DONE patch\nSTATE tested\nNEXT review\nBLOCKERS none",
        "processed_event_ids": ["event-1"],
        "cursor": 7,
    }
    resumed = [Call("studio_start_work", START), Call("studio_sync", {"session_id": SESSION})]
    assert "NEXT review" in durable["summary"]
    assert resumed[0].args["task_id"] == TASK
    assert durable["processed_event_ids"] == ["event-1"]
    assert durable["cursor"] == 7


def test_real_profiles_session_default_admin_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_MCP_TOOL_PROFILE", "admin")
    assert resolve_tool_profile(None) == "admin"
    assert resolve_tool_profile({}) == "session"
    assert resolve_tool_profile({"X-Studio-Tool-Profile": "ADMIN"}) == "admin"
    assert normalise_tool_profile("unknown") == "session"
    assert "studio_start_work" in tools_for_profile("session")
    assert "studio_register_runtime" not in tools_for_profile("session")
    assert tools_for_profile("admin") == frozenset(MCP_ACCESS)
    assert tools_for_profile("session") < tools_for_profile("admin")


def test_trace_signature_oracle_rejects_invented_arguments() -> None:
    with pytest.raises(TypeError):
        Call("studio_start_work", {**START, "known_ids": {DEFINITION: HASH}})
    with pytest.raises(TypeError):
        Call("studio_update_task", {"task_id": TASK, "status": "completed"})
