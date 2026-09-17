from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import HTTPException
from mcp.server.mcpserver import Context
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import idempotency as idempotency_service
from studio_api.services import library as library_service
from studio_api.services import resolution as resolution_service
from studio_api.services import runtime_bindings as bindings_service
from studio_api.services import runtime_registry as registry_service
from studio_api.services.authz import Principal, ensure_can_write
from studio_contracts.library import (
    DependencyPin,
    LibraryKind,
    LibraryResource,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersion,
    LibraryVersionCreate,
    RuntimeCapabilities,
)
from studio_contracts.resolution import ResolvedAgentDefinition, SessionRuntimeOverride
from studio_contracts.runtime import (
    CapabilitySource,
    RuntimeBinding,
    RuntimeBindingCreate,
    RuntimeLevel,
    RuntimeRegistration,
    RuntimeRegistrationCreate,
    RuntimeRegistrationUpdate,
    RuntimeTarget,
)

from studio_mcp.errors import McpError, run_tool
from studio_mcp.util import parse_uuid


async def _run_p8(
    ctx: Context, handler: Callable[[AsyncSession, Principal], Awaitable[Any]]
) -> Any:
    raw = await run_tool(ctx, handler)
    if isinstance(raw, dict):
        try:
            return McpError.model_validate(raw)
        except ValidationError:
            return McpError(error_code="error", message=json.dumps(raw, default=str))
    return raw


class DefinitionList(BaseModel):
    definitions: list[LibraryResource]
    total: int


class DefinitionDetail(BaseModel):
    resource: LibraryResource
    versions: list[LibraryVersion] = []


class PublishDefinitionResult(BaseModel):
    resource: LibraryResource
    version: LibraryVersion | None = None


def _from_http(exc: HTTPException) -> McpError:
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("error_code", "error"))
        message = str(detail.get("message", ""))
        extras = {k: v for k, v in detail.items() if k not in ("error_code", "message")}
        return McpError(error_code=code, message=message, **extras)
    return McpError(error_code="error", message=str(detail))


def _invalid(message: str) -> McpError:
    return McpError(error_code="invalid_argument", message=message)


def _parse_uuid(raw: str, field: str) -> UUID | McpError:
    parsed = parse_uuid(raw, field)
    if isinstance(parsed, dict):
        return McpError(error_code=str(parsed["error_code"]), message=str(parsed["message"]))
    return parsed


def _parse_optional_uuid(raw: str | None, field: str) -> UUID | None | McpError:
    if raw is None:
        return None
    return _parse_uuid(raw, field)


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:3]:
        loc = ".".join(str(p) for p in error["loc"]) or "value"
        parts.append(f"{loc}: {error['msg']}")
    return "; ".join(parts)


def _coerce_target(raw: RuntimeTarget | dict[str, Any] | None) -> RuntimeTarget | None | McpError:
    if raw is None or isinstance(raw, RuntimeTarget):
        return raw
    try:
        return RuntimeTarget.model_validate(raw)
    except ValidationError as exc:
        return _invalid(f"invalid target: {_validation_message(exc)}")


def _coerce_capabilities(
    raw: RuntimeCapabilities | dict[str, Any] | None,
) -> RuntimeCapabilities | McpError:
    if raw is None:
        return RuntimeCapabilities()
    if isinstance(raw, RuntimeCapabilities):
        return raw
    try:
        return RuntimeCapabilities.model_validate(raw)
    except ValidationError as exc:
        return _invalid(f"invalid capabilities: {_validation_message(exc)}")


def _coerce_dependencies(raw: Any) -> list[DependencyPin] | McpError:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return _invalid("invalid dependencies: expected a list")
    try:
        return [p if isinstance(p, DependencyPin) else DependencyPin.model_validate(p) for p in raw]
    except ValidationError as exc:
        return _invalid(f"invalid dependencies: {_validation_message(exc)}")


def _coerce_overrides(raw: Any) -> list[SessionRuntimeOverride] | McpError:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return _invalid("invalid session_overrides: expected a list")
    try:
        return [
            o if isinstance(o, SessionRuntimeOverride) else SessionRuntimeOverride.model_validate(o)
            for o in raw
        ]
    except ValidationError as exc:
        return _invalid(f"invalid session_overrides: {_validation_message(exc)}")


class _MissingArgument(Exception):
    pass


class _ErrorResult(Exception):
    def __init__(self, error: McpError) -> None:
        super().__init__(error.error_code)
        self.error = error


async def studio_resolve_agent(
    stable_key: str,
    ctx: Context,
    project_id: str | None = None,
    session_overrides: list[SessionRuntimeOverride] | None = None,
) -> ResolvedAgentDefinition | McpError:
    """Resolve one agent definition to its full structured result."""

    async def _handler(
        session: AsyncSession, principal: Principal
    ) -> ResolvedAgentDefinition | McpError:
        parsed_project = _parse_optional_uuid(project_id, "project_id")
        if isinstance(parsed_project, McpError):
            return parsed_project
        coerced = _coerce_overrides(session_overrides)
        if isinstance(coerced, McpError):
            return coerced
        overrides: dict[tuple[LibraryKind, str], RuntimeTarget] = {}
        for override in coerced:
            key = (override.target_kind, override.target_stable_key)
            if key in overrides:
                return McpError(
                    error_code="invalid_resolution_input",
                    message="duplicate_session_override",
                )
            overrides[key] = override.target
        try:
            return await resolution_service.resolve_full(
                session,
                principal,
                LibraryKind.AGENT_DEFINITION,
                stable_key,
                parsed_project,
                overrides or None,
            )
        except HTTPException as exc:
            return _from_http(exc)

    return cast(ResolvedAgentDefinition | McpError, await _run_p8(ctx, _handler))


async def studio_discover_definitions(
    ctx: Context,
    kind: str | None = None,
    scope: str | None = None,
    project_id: str | None = None,
    resource_id: str | None = None,
    stable_key: str | None = None,
    include_versions: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> DefinitionList | DefinitionDetail | McpError:
    """Discover and read library definitions, with or without UUIDs."""

    async def _handler(
        session: AsyncSession, principal: Principal
    ) -> DefinitionList | DefinitionDetail | McpError:
        parsed_project = _parse_optional_uuid(project_id, "project_id")
        if isinstance(parsed_project, McpError):
            return parsed_project
        if limit < 1 or limit > 500 or offset < 0:
            return _invalid("limit must be within 1..500 and offset must be >= 0")

        async def _detail_for(resource_uuid: UUID) -> DefinitionDetail | McpError:
            resource = await library_service.get_resource(session, principal, resource_uuid)
            if resource is None:
                return McpError(
                    error_code="definition_not_found",
                    message=f"library resource {resource_uuid} not found",
                )
            versions: list[LibraryVersion] = []
            if include_versions:
                rows = await library_service.list_versions(session, resource.id)
                versions = [await library_service.version_detail(session, row) for row in rows]
            return DefinitionDetail(
                resource=LibraryResource.model_validate(resource), versions=versions
            )

        if resource_id is not None:
            parsed = _parse_uuid(resource_id, "resource_id")
            if isinstance(parsed, McpError):
                return parsed
            return await _detail_for(parsed)
        if stable_key is not None:
            if kind is None:
                return _invalid("kind is required with stable_key")
            try:
                parsed_kind = LibraryKind(kind)
            except ValueError:
                return _invalid(f"unknown kind: {kind!r}")
            try:
                resolved = await library_service.resolve_definition(
                    session, principal, parsed_kind, stable_key, parsed_project
                )
            except HTTPException as exc:
                return _from_http(exc)
            return await _detail_for(resolved.resource_id)
        resources = await library_service.list_resources(
            session,
            principal,
            kind=kind,
            scope=scope,
            project_id=parsed_project,
            limit=limit,
            offset=offset,
        )
        return DefinitionList(
            definitions=[LibraryResource.model_validate(r) for r in resources],
            total=len(resources),
        )

    return cast(DefinitionList | DefinitionDetail | McpError, await _run_p8(ctx, _handler))


async def studio_publish_definition(
    action: Literal["create", "create_version", "activate", "deprecate"],
    ctx: Context,
    resource_id: str | None = None,
    kind: str | None = None,
    stable_key: str | None = None,
    scope: str | None = None,
    title: str | None = None,
    description: str | None = None,
    content: dict[str, Any] | None = None,
    dependencies: list[DependencyPin] | None = None,
    project_id: str | None = None,
    version: int | None = None,
    expected_resource_version: int | None = None,
    idempotency_key: str | None = None,
) -> PublishDefinitionResult | McpError:
    """Publish a library change: create, version, activate or deprecate."""

    async def _handler(
        session: AsyncSession, principal: Principal
    ) -> PublishDefinitionResult | McpError:
        parsed_project = _parse_optional_uuid(project_id, "project_id")
        if isinstance(parsed_project, McpError):
            return parsed_project
        pins = _coerce_dependencies(dependencies)
        if isinstance(pins, McpError):
            return pins

        async def _load_resource(raw: str | None) -> Any:
            if raw is None:
                return _invalid(f"resource_id is required for action {action!r}")
            parsed = _parse_uuid(raw, "resource_id")
            if isinstance(parsed, McpError):
                return parsed
            resource = await library_service.get_resource(session, principal, parsed)
            if resource is None:
                return McpError(
                    error_code="definition_not_found",
                    message=f"library resource {raw} not found",
                )
            return resource

        try:
            ensure_can_write(principal, "library")
        except HTTPException as exc:
            return _from_http(exc)

        payload_args = {
            "action": action,
            "resource_id": resource_id,
            "kind": kind,
            "stable_key": stable_key,
            "scope": scope,
            "title": title,
            "description": description,
            "content": content,
            "dependencies": [
                p.model_dump(mode="json") if isinstance(p, DependencyPin) else p
                for p in (dependencies or [])
            ],
            "project_id": project_id,
            "version": version,
            "expected_resource_version": expected_resource_version,
        }

        async def _create() -> dict[str, Any]:
            if action == "create":
                if kind is None or stable_key is None or scope is None or title is None:
                    raise _MissingArgument("kind, stable_key, scope and title are required")
                try:
                    parsed_kind = LibraryKind(kind)
                    parsed_scope = LibraryScope(scope)
                except ValueError:
                    raise _MissingArgument(f"unknown kind or scope: {kind!r}/{scope!r}") from None
                try:
                    data = LibraryResourceCreate(
                        kind=parsed_kind,
                        stable_key=stable_key,
                        scope=parsed_scope,
                        project_id=parsed_project,
                        title=title,
                        description=description,
                        content=content if content is not None else {},
                        dependencies=pins if isinstance(pins, list) else [],
                    )
                except ValidationError as exc:
                    raise _MissingArgument(_validation_message(exc)) from exc
                resource, version_row = await library_service.create_resource(
                    session, principal, data
                )
                result = PublishDefinitionResult(
                    resource=LibraryResource.model_validate(resource),
                    version=await library_service.version_detail(session, version_row),
                )
            else:
                resource = await _load_resource(resource_id)
                if isinstance(resource, McpError):
                    raise _ErrorResult(resource)
                if action == "create_version":
                    if title is None:
                        raise _MissingArgument("title is required")
                    version_in = LibraryVersionCreate(
                        title=title,
                        description=description,
                        content=content if content is not None else {},
                        dependencies=pins if isinstance(pins, list) else [],
                    )
                    version_row = await library_service.create_resource_version(
                        session, principal, resource, version_in
                    )
                    refreshed = await library_service.get_resource(session, principal, resource.id)
                    await session.refresh(refreshed)
                    result = PublishDefinitionResult(
                        resource=LibraryResource.model_validate(refreshed),
                        version=await library_service.version_detail(session, version_row),
                    )
                elif action == "activate":
                    if version is None or expected_resource_version is None:
                        raise _MissingArgument("version and expected_resource_version are required")
                    updated = await library_service.activate_resource_version(
                        session, principal, resource, version, expected_resource_version
                    )
                    result = PublishDefinitionResult(
                        resource=LibraryResource.model_validate(updated)
                    )
                else:
                    if expected_resource_version is None:
                        raise _MissingArgument("expected_resource_version is required")
                    updated = await library_service.deprecate_resource(
                        session, principal, resource, expected_resource_version
                    )
                    result = PublishDefinitionResult(
                        resource=LibraryResource.model_validate(updated)
                    )
            return result.model_dump(mode="json")

        request_hash = idempotency_service.hash_request(
            json.dumps(payload_args, sort_keys=True, default=str).encode()
        )
        try:
            payload = await idempotency_service.run_idempotent_dict(
                session, idempotency_key, "MCP studio_publish_definition", request_hash, _create
            )
        except _MissingArgument as exc:
            return _invalid(str(exc))
        except _ErrorResult as exc:
            return exc.error
        except HTTPException as exc:
            return _from_http(exc)
        return PublishDefinitionResult.model_validate(payload)

    return cast(PublishDefinitionResult | McpError, await _run_p8(ctx, _handler))


async def studio_configure_runtime(
    action: Literal["set", "clear"],
    ctx: Context,
    level: str | None = None,
    target_kind: str | None = None,
    target_stable_key: str | None = None,
    target: RuntimeTarget | dict[str, Any] | None = None,
    project_id: str | None = None,
    idempotency_key: str | None = None,
) -> RuntimeBinding | McpError:
    """Set or clear the runtime choice for one logical definition key."""

    async def _handler(session: AsyncSession, principal: Principal) -> RuntimeBinding | McpError:
        if level is None or target_kind is None or target_stable_key is None:
            return _invalid("level, target_kind and target_stable_key are required")
        try:
            parsed_level = RuntimeLevel(level)
        except ValueError:
            return _invalid(f"unknown level: {level!r}")
        try:
            parsed_kind = LibraryKind(target_kind)
        except ValueError:
            return _invalid(f"unknown kind: {target_kind!r}")
        parsed_project = _parse_optional_uuid(project_id, "project_id")
        if isinstance(parsed_project, McpError):
            return parsed_project
        try:
            ensure_can_write(principal, "runtime_binding")
        except HTTPException as exc:
            return _from_http(exc)

        if action == "clear":
            try:
                candidates = await bindings_service.list_bindings(
                    session,
                    principal,
                    parsed_level,
                    parsed_project,
                    parsed_kind,
                    target_stable_key,
                )
            except HTTPException as exc:
                return _from_http(exc)
            match = next(
                (
                    b
                    for b in candidates
                    if b.project_id == parsed_project and b.target_stable_key == target_stable_key
                ),
                None,
            )
            if match is None:
                return McpError(
                    error_code="not_found",
                    message="no such runtime binding",
                )
            try:
                deleted = await bindings_service.delete_binding(session, principal, match)
            except HTTPException as exc:
                return _from_http(exc)
            return deleted

        coerced = _coerce_target(target)
        if isinstance(coerced, McpError):
            return coerced
        if coerced is None:
            return _invalid("target is required for action 'set'")

        async def _create() -> dict[str, Any]:
            binding = await bindings_service.create_binding(
                session,
                principal,
                RuntimeBindingCreate(
                    level=parsed_level,
                    project_id=parsed_project,
                    target_kind=parsed_kind,
                    target_stable_key=target_stable_key,
                    target=coerced,
                ),
            )
            return bindings_service.to_contract(binding).model_dump(mode="json")

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {
                    "action": action,
                    "level": level,
                    "target_kind": target_kind,
                    "target_stable_key": target_stable_key,
                    "target": (
                        coerced.model_dump(mode="json")
                        if isinstance(coerced, RuntimeTarget)
                        else None
                    ),
                    "project_id": project_id,
                },
                sort_keys=True,
                default=str,
            ).encode()
        )
        try:
            payload = await idempotency_service.run_idempotent_dict(
                session, idempotency_key, "MCP studio_configure_runtime", request_hash, _create
            )
        except HTTPException as exc:
            return _from_http(exc)
        return RuntimeBinding.model_validate(payload)

    return cast(RuntimeBinding | McpError, await _run_p8(ctx, _handler))


async def studio_register_runtime(
    action: Literal["register", "update", "revoke"],
    ctx: Context,
    runtime_id: str | None = None,
    machine_id: str | None = None,
    harness_ref: str | None = None,
    provider_ref: str | None = None,
    model_ref: str | None = None,
    capabilities: RuntimeCapabilities | dict[str, Any] | None = None,
    capability_source: str = "declared",
    runtime_metadata: dict[str, Any] | None = None,
    detach_machine: bool = False,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> RuntimeRegistration | McpError:
    """Register or maintain a runtime description (any provider/harness)."""

    async def _handler(
        session: AsyncSession, principal: Principal
    ) -> RuntimeRegistration | McpError:
        parsed_machine = _parse_optional_uuid(machine_id, "machine_id")
        if isinstance(parsed_machine, McpError):
            return parsed_machine
        caps = _coerce_capabilities(capabilities)
        if isinstance(caps, McpError):
            return caps
        try:
            source = CapabilitySource(capability_source)
        except ValueError:
            return _invalid(f"unknown capability_source: {capability_source!r}")
        try:
            ensure_can_write(principal, "runtime")
        except HTTPException as exc:
            return _from_http(exc)

        async def _load_runtime(raw: str | None) -> Any:
            if raw is None:
                return _invalid(f"runtime_id is required for action {action!r}")
            parsed = _parse_uuid(raw, "runtime_id")
            if isinstance(parsed, McpError):
                return parsed
            runtime = await registry_service.get_runtime(session, principal, parsed)
            if runtime is None:
                return McpError(
                    error_code="runtime_not_found",
                    message=f"runtime {raw} not found",
                )
            return runtime

        if action == "revoke":
            loaded = await _load_runtime(runtime_id)
            if isinstance(loaded, McpError):
                return loaded
            try:
                revoked = await registry_service.revoke_runtime(session, principal, loaded)
            except HTTPException as exc:
                return _from_http(exc)
            return registry_service.to_contract(revoked)

        payload_args: dict[str, Any] = {
            "action": action,
            "runtime_id": runtime_id,
            "machine_id": machine_id,
            "harness_ref": harness_ref,
            "provider_ref": provider_ref,
            "model_ref": model_ref,
            "capabilities": caps.model_dump(mode="json"),
            "capability_source": capability_source,
            "runtime_metadata": runtime_metadata,
            "detach_machine": detach_machine,
            "expected_version": expected_version,
        }

        async def _create() -> dict[str, Any]:
            if action == "register":
                try:
                    data = RuntimeRegistrationCreate(
                        machine_id=parsed_machine,
                        harness_ref=harness_ref,
                        provider_ref=provider_ref,
                        model_ref=model_ref,
                        capabilities=(
                            caps if isinstance(caps, RuntimeCapabilities) else RuntimeCapabilities()
                        ),
                        capability_source=source,
                        runtime_metadata=runtime_metadata if runtime_metadata is not None else {},
                    )
                except ValidationError as exc:
                    raise _MissingArgument(_validation_message(exc)) from exc
                created = await registry_service.register_runtime(session, principal, data)
                return registry_service.to_contract(created).model_dump(mode="json")
            loaded = await _load_runtime(runtime_id)
            if isinstance(loaded, McpError):
                raise _ErrorResult(loaded)
            if expected_version is None:
                raise _MissingArgument("expected_version is required")
            try:
                patch = RuntimeRegistrationUpdate(
                    machine_id=parsed_machine,
                    detach_machine=detach_machine,
                    harness_ref=harness_ref,
                    provider_ref=provider_ref,
                    model_ref=model_ref,
                    capabilities=caps if capabilities is not None else None,
                    runtime_metadata=runtime_metadata,
                )
            except ValidationError as exc:
                raise _MissingArgument(_validation_message(exc)) from exc
            updated = await registry_service.update_runtime(
                session, principal, loaded, patch, expected_version
            )
            return registry_service.to_contract(updated).model_dump(mode="json")

        request_hash = idempotency_service.hash_request(
            json.dumps(payload_args, sort_keys=True, default=str).encode()
        )
        try:
            payload = await idempotency_service.run_idempotent_dict(
                session, idempotency_key, "MCP studio_register_runtime", request_hash, _create
            )
        except _MissingArgument as exc:
            return _invalid(str(exc))
        except _ErrorResult as exc:
            return exc.error
        except HTTPException as exc:
            return _from_http(exc)
        return RuntimeRegistration.model_validate(payload)

    return cast(RuntimeRegistration | McpError, await _run_p8(ctx, _handler))
