"""Summarize native traces without treating agent claims as server effects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from validate import TRACE, save


def decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def extract(path: Path) -> dict[str, Any]:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    calls: list[dict[str, Any]] = []
    skills = []
    usage = []
    models = set()
    by_id = {}
    native_cost = 0.0
    cost_available = False
    for line, event in enumerate(events, 1):
        if event.get("model"):
            models.add(event["model"])
        if event.get("type") == "result":
            usage.append(event.get("usage", {}))
            native_cost += event.get("total_cost_usd", 0)
            cost_available = "total_cost_usd" in event
        if event.get("type") == "turn.completed":
            usage.append(event.get("usage", {}))
        for block in event.get("message", {}).get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                if block.get("name") == "Skill":
                    skills.append(block.get("input", {}))
                if block.get("name", "").startswith("mcp__p15__studio_"):
                    call = {
                        "line": line,
                        "tool": block["name"].split("mcp__p15__")[1],
                        "arguments": block.get("input", {}),
                        "response": None,
                    }
                    calls.append(call)
                    by_id[block["id"]] = call
            if block.get("type") == "tool_result" and block.get("tool_use_id") in by_id:
                content = block.get("content")
                if isinstance(content, list):
                    content = "\n".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
                by_id[block["tool_use_id"]]["response"] = decode(content)
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "mcp_tool_call" and item.get("tool", "").startswith("studio_"):
                result = item.get("result") or {}
                response = result.get("structured_content")
                if response is None and result.get("content"):
                    response = decode(result["content"][0].get("text"))
                if isinstance(response, dict):
                    response = response.get("result", response)
                calls.append(
                    {
                        "line": line,
                        "tool": item["tool"],
                        "arguments": item.get("arguments", {}),
                        "response": response,
                        "transport_error": item.get("error"),
                        "status": item.get("status"),
                    }
                )
        if event.get("type") == "step_finish":
            usage.append(event["part"].get("tokens", {}))
            native_cost += event["part"].get("cost", 0)
            cost_available = "cost" in event["part"]
        if event.get("type") == "tool_use":
            part = event["part"]
            if part["tool"] == "skill":
                skills.append(part["state"].get("input"))
            if part["tool"].startswith("p15_studio_"):
                calls.append(
                    {
                        "line": line,
                        "tool": part["tool"][4:],
                        "arguments": part["state"].get("input", {}),
                        "response": decode(part["state"].get("output")),
                    }
                )
    write_names = {
        "studio_start_work",
        "studio_handoff",
        "studio_update_task",
        "studio_claim_resources",
        "studio_create_task",
        "studio_coordinate",
        "studio_log_ai_work",
        "studio_add_decision",
    }
    errors = []
    for call in calls:
        value = call["response"]
        if isinstance(value, dict):
            value = value.get("result", value)
            call["response"] = value
            if "error_code" in value:
                errors.append(
                    {"line": call["line"], "tool": call["tool"], "error_code": value["error_code"]}
                )
    duration_file = path.with_name("run-" + path.stem + ".json")
    if path.stem.startswith("initial-"):
        duration_file = path.with_name("initial-run-" + path.stem[8:] + ".json")
    duration = json.loads(duration_file.read_text()) if duration_file.exists() else None
    return {
        "trace": path.name,
        "models": sorted(models),
        "skills": skills,
        "native_run": duration,
        "mcp_calls": len(calls),
        "server_responses": sum(c["response"] is not None for c in calls),
        "blocked_before_server": [c for c in calls if c.get("transport_error")],
        "tools": [c["tool"] for c in calls],
        "calls": calls,
        "errors": errors,
        "write_requests": [
            c["tool"]
            for c in calls
            if c["tool"] in write_names
            or c["tool"] == "studio_sync"
            and c["arguments"].get("ack") is not None
        ],
        "handoffs": [c for c in calls if c["tool"] == "studio_handoff"],
        "usage_raw": usage,
        "reported_cost_usd": native_cost if cost_available else None,
    }


if __name__ == "__main__":
    runs = [extract(path) for path in sorted(TRACE.glob("*.jsonl"))]
    save("analysis.json", runs)
    for run in runs:
        print(
            run["trace"],
            "calls",
            run["mcp_calls"],
            "writes",
            ",".join(run["write_requests"]),
            "errors",
            run["errors"],
        )
