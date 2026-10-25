from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from studio_mcp.errors import validation_error

MAX_ARGUMENT_BYTES = 1024 * 1024


def argument_bounds(arguments: dict[str, Any]) -> dict[str, Any] | None:
    total = 0
    try:
        for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(arguments):
            total += len(chunk.encode("utf-8"))
            if total > MAX_ARGUMENT_BYTES:
                return {"error_code": "invalid_argument", "message": "arguments exceed 1 MiB"}
    except (ValueError, TypeError, RecursionError):
        return {"error_code": "invalid_argument", "message": "arguments must be finite JSON"}
    for key, minimum, maximum in (("limit", 1, 500), ("offset", 0, None), ("max_chars", 1, 50000)):
        value = arguments.get(key)
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and (value < minimum or (maximum is not None and value > maximum))
        ):
            return {"error_code": "invalid_argument", "message": f"{key} outside supported bounds"}
    return None


def valid_argument_names(tool: Any) -> list[str]:
    names: set[str] = set()
    for field_name, field in tool.fn_metadata.arg_model.model_fields.items():
        alias = field.alias
        names.add(alias or field_name)
    return sorted(names)


def accepted_argument_names(tool: Any) -> set[str]:
    accepted: set[str] = set()
    for field_name, field in tool.fn_metadata.arg_model.model_fields.items():
        accepted.add(field_name)
        if field.alias:
            accepted.add(field.alias)
    return accepted


def unknown_arguments_error(tool_name: str, unknown: list[str], valid: list[str]) -> dict[str, Any]:
    bounded = [name[:80] for name in unknown[:10]]
    names = ", ".join(bounded)
    return {
        "error_code": "invalid_argument",
        "message": f"unknown argument(s) for {tool_name}: {names}",
        "unknown_arguments": bounded,
        "valid_arguments": valid,
    }


def find_unknown(tool: Any, arguments: dict[str, Any] | None) -> list[str]:
    if not arguments:
        return []
    return sorted(set(arguments) - accepted_argument_names(tool))


def enforce_strict_arguments(server: Any) -> None:
    manager = server._tool_manager
    for tool in manager.list_tools():
        if isinstance(tool.parameters, dict):
            tool.parameters["additionalProperties"] = False
            properties = tool.parameters.get("properties", {})
            for name, minimum, maximum in (
                ("limit", 1, 500),
                ("offset", 0, None),
                ("max_chars", 1, 50000),
            ):
                schema = properties.get(name)
                if isinstance(schema, dict):
                    schema["minimum"] = max(minimum, schema.get("minimum", minimum))
                    if maximum is not None:
                        schema["maximum"] = min(maximum, schema.get("maximum", maximum))
        original_run = tool.run

        async def strict_run(
            arguments: dict[str, Any],
            context: Any,
            convert_result: bool = False,
            _tool: Any = tool,
            _original_run: Any = original_run,
        ) -> Any:
            error = argument_bounds(arguments)
            if error is not None:
                if convert_result:
                    return _tool.fn_metadata.convert_result(error)
                return error
            unknown = find_unknown(_tool, arguments)
            if unknown:
                error = unknown_arguments_error(_tool.name, unknown, valid_argument_names(_tool))
                if convert_result:
                    return _tool.fn_metadata.convert_result(error)
                return error
            try:
                validated = _tool.fn_metadata.validate_arguments(arguments)
                bounds = {
                    key: validated[key]
                    for key in ("limit", "offset", "max_chars")
                    if key in validated
                }
                error = argument_bounds(bounds)
                if error is not None:
                    if convert_result:
                        return _tool.fn_metadata.convert_result(error)
                    return error
                return await _original_run(arguments, context, convert_result=convert_result)
            except (ValidationError, ToolError) as exc:
                cause = exc if isinstance(exc, ValidationError) else exc.__cause__
                if not isinstance(cause, ValidationError):
                    raise
                error = validation_error(cause)
                if convert_result:
                    return _tool.fn_metadata.convert_result(error)
                return error

        object.__setattr__(tool, "run", strict_run)

    original_call_tool = manager.call_tool

    async def strict_call_tool(
        name: str,
        arguments: dict[str, Any],
        context: Any,
        convert_result: bool = False,
    ) -> Any:
        tool = manager.get_tool(name)
        if tool is not None:
            unknown = find_unknown(tool, arguments)
            if unknown:
                error = unknown_arguments_error(name, unknown, valid_argument_names(tool))
                if convert_result:
                    return tool.fn_metadata.convert_result(error)
                return error
        return await original_call_tool(name, arguments, context, convert_result=convert_result)

    manager.call_tool = strict_call_tool
