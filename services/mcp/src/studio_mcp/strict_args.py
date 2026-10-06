from __future__ import annotations

from typing import Any


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
    names = ", ".join(unknown)
    return {
        "error_code": "invalid_argument",
        "message": f"unknown argument(s) for {tool_name}: {names}",
        "unknown_arguments": unknown,
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
        original_run = tool.run

        async def strict_run(
            arguments: dict[str, Any],
            context: Any,
            convert_result: bool = False,
            _tool: Any = tool,
            _original_run: Any = original_run,
        ) -> Any:
            unknown = find_unknown(_tool, arguments)
            if unknown:
                error = unknown_arguments_error(_tool.name, unknown, valid_argument_names(_tool))
                if convert_result:
                    return _tool.fn_metadata.convert_result(error)
                return error
            return await _original_run(arguments, context, convert_result=convert_result)

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
