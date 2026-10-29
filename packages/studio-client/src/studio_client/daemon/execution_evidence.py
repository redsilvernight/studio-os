from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_ENVIRONMENT_MARKERS = (
    "no module named pytest",
    "pytest: command not found",
    "pytest: not found",
    "connection to the server at",
    "could not connect to server",
    "cannot connect to the docker daemon",
    "environment_unavailable:",
)


def _environment_failure(text: str) -> bool:
    return any(marker in text for marker in _ENVIRONMENT_MARKERS) or (
        "asyncpg" in text
        and any(
            marker in text
            for marker in ("connectionrefusederror", "connection refused", "connect call failed")
        )
    )


@dataclass(frozen=True)
class ExecutionEvidence:
    observed_commands: int = 0
    failed_commands: int = 0
    failed_tools: int = 0
    run_failed: bool = False
    environment_unavailable: bool = False
    truncated: bool = False
    command_exit_codes: tuple[int | None, ...] = ()

    @property
    def failed(self) -> bool:
        return bool(self.failed_commands or self.failed_tools or self.run_failed)

    @property
    def validation(self) -> str:
        if self.environment_unavailable:
            return "environment_unavailable"
        return "failed" if self.failed else "unverified"


def _documents(output: str) -> list[dict[str, Any]]:
    text = output[-65536:]
    try:
        whole = json.loads(text)
    except (ValueError, RecursionError):
        whole = None
    values = whole if isinstance(whole, list) else [whole]
    if whole is None:
        values = []
        for line in text.splitlines()[-512:]:
            try:
                values.append(json.loads(line))
            except (ValueError, RecursionError):
                continue
    return [value for value in values[-512:] if isinstance(value, dict)]


def collect_execution_evidence(
    output: str, *, exit_code: int | None, truncated: bool = False
) -> ExecutionEvidence:
    commands: dict[str, tuple[bool, bool, int | None]] = {}
    failed_tools: set[str] = set()
    run_failed = False
    for index, document in enumerate(_documents(output)):
        kind = document.get("type")
        if kind == "turn.failed" or (kind == "result" and document.get("is_error") is True):
            run_failed = True
        item = document.get("item")
        if kind == "item.completed" and isinstance(item, dict):
            if item.get("type") == "command_execution":
                code = item.get("exit_code")
                real_code = code if isinstance(code, int) and not isinstance(code, bool) else None
                failed = (real_code is not None and real_code != 0) or item.get(
                    "status"
                ) == "failed"
                command = item.get("command")
                key = command if isinstance(command, str) and command else f"item:{index}"
                raw_output = item.get("aggregated_output")
                text = raw_output.lower() if isinstance(raw_output, str) else ""
                environment = failed and _environment_failure(text)
                commands[key] = (failed, environment, real_code)
            elif item.get("type") == "mcp_tool_call" and item.get("status") == "failed":
                failed_tools.add(f"item:{index}")
        message = document.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        if kind == "user" and isinstance(blocks, list):
            for block in blocks:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and block.get("is_error") is True
                ):
                    failed_tools.add(str(block.get("tool_use_id", f"block:{index}")))
    environment = any(value[1] for value in commands.values())
    if exit_code not in (None, 0):
        environment |= _environment_failure(output.lower())
    return ExecutionEvidence(
        observed_commands=len(commands),
        failed_commands=sum(value[0] for value in commands.values()),
        failed_tools=len(failed_tools),
        run_failed=run_failed,
        environment_unavailable=environment,
        truncated=truncated or len(output) > 65536,
        command_exit_codes=tuple(value[2] for value in list(commands.values())[:20]),
    )
