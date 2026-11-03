from __future__ import annotations

import json

import pytest
from studio_client.daemon.execution_evidence import collect_execution_evidence


def _command(code: int, *, output: str = "", command: str = "pytest") -> str:
    return json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": command,
                "exit_code": code,
                "status": "completed",
                "aggregated_output": output,
            },
        }
    )


def test_completed_tool_with_nonzero_real_exit_is_failure() -> None:
    result = collect_execution_evidence(_command(1), exit_code=0)
    assert result.failed
    assert result.validation == "failed"
    assert result.command_exit_codes == (1,)


def test_exact_command_retry_uses_last_observed_exit_without_rewriting_other_commands() -> None:
    result = collect_execution_evidence(
        "\n".join([_command(1), _command(0), _command(2, command="npm test")]), exit_code=0
    )
    assert (result.observed_commands, result.failed_commands) == (2, 1)
    assert result.command_exit_codes == (0, 2)


def test_missing_pytest_is_environment_failure_only_with_observed_failed_execution() -> None:
    text = "No module named pytest"
    result = collect_execution_evidence(_command(1, output=text), exit_code=0)
    assert result.validation == "environment_unavailable"
    assert collect_execution_evidence(text, exit_code=0).validation == "unverified"
    assert collect_execution_evidence(text, exit_code=1).validation == "environment_unavailable"


def test_unavailable_postgresql_is_environment_failure() -> None:
    result = collect_execution_evidence(
        _command(1, output="asyncpg.exceptions: ConnectionRefusedError: connect call failed"),
        exit_code=0,
    )
    assert result.validation == "environment_unavailable"


@pytest.mark.parametrize(
    "output",
    [
        "all tests passed",
        "completed",
        "{broken",
        "[]",
        json.dumps({"type": "result", "is_error": False, "result": "all checks pass"}),
        json.dumps(
            {"type": "item.completed", "item": {"type": "agent_message", "text": _command(1)}}
        ),
    ],
)
def test_plain_text_or_agent_claims_never_prove_validation(output: str) -> None:
    result = collect_execution_evidence(output, exit_code=0)
    assert result.validation == "unverified"
    assert not result.failed


@pytest.mark.parametrize(
    "document",
    [
        {"type": "result", "is_error": True},
        {"type": "turn.failed"},
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "is_error": True}]},
        },
        {"type": "item.completed", "item": {"type": "mcp_tool_call", "status": "failed"}},
    ],
)
def test_structured_run_and_tool_errors_are_preserved(document: dict[str, object]) -> None:
    assert collect_execution_evidence(json.dumps(document), exit_code=0).failed


def test_truncated_or_future_output_stays_unverified_and_bounded() -> None:
    result = collect_execution_evidence("future-format" * 10000, exit_code=0, truncated=True)
    assert result.truncated
    assert result.validation == "unverified"
    assert result.command_exit_codes == ()
