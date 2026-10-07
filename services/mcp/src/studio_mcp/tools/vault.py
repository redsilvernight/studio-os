from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from mcp.server.mcpserver import Context
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.vault import VaultNoteModel
from studio_api.services import idempotency as idempotency_service
from studio_api.services import vault as vault_service
from studio_api.services.authz import Principal
from studio_contracts.vault import (
    VAULT_BODY_MAX,
    VAULT_SEARCH_LIMIT_DEFAULT,
    VAULT_SEARCH_LIMIT_MAX,
    VAULT_SEARCH_MAX_CHARS_DEFAULT,
    VAULT_SEARCH_MAX_CHARS_MAX,
    VAULT_SEARCH_PATHS_MAX,
    VaultActorType,
    VaultNoteCreate,
    VaultNoteLink,
    VaultNoteStatus,
    VaultNoteType,
    VaultNoteUpdate,
    VaultScope,
)

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid

_SEARCH_Q_MAX = 1000
_SEARCH_MAX_CHARS_MIN = 500
_READ_MAX_CHARS_DEFAULT = 12_000
_STATUS_WRITTEN_BY_AN_AGENT = VaultNoteStatus.PROPOSED
"""Every note an agent writes is `proposed`: validating, superseding or
archiving one stays a human action (AI/02_AGENT_RULES.md, .claude/rules/
mcp-tools.md read/write boundary). There is deliberately no `status`
parameter to widen that."""


def _invalid_arguments(message: str) -> dict[str, Any]:
    """The repo-wide code for an argument outside the tool's contract — the
    same vocabulary `parse_uuid` and `strict_args` already answer in-band."""
    return {"error_code": "invalid_argument", "message": message}


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:3]:
        loc = ".".join(str(part) for part in error["loc"]) or "value"
        parts.append(f"{loc}: {error['msg']}")
    return "; ".join(parts)


def _bounded(value: int, low: int, high: int, field: str) -> int | dict[str, Any]:
    if not low <= value <= high:
        return _invalid_arguments(f"{field} must be between {low} and {high}")
    return value


def _enum_list[T: StrEnum](
    values: list[str] | None, enum: type[T], field: str
) -> list[T] | dict[str, Any]:
    if not values:
        return []
    try:
        return [enum(value) for value in values]
    except ValueError:
        allowed = ", ".join(member.value for member in enum)
        return _invalid_arguments(f"unknown {field}: {allowed}")


def _scope(value: str | None) -> VaultScope | None | dict[str, Any]:
    if value is None:
        return None
    try:
        return VaultScope(value)
    except ValueError:
        allowed = ", ".join(member.value for member in VaultScope)
        return _invalid_arguments(f"unknown scope: {allowed}")


def _compact_note(note: VaultNoteModel) -> dict[str, Any]:
    return {
        "id": str(note.id),
        "readable_id": note.readable_id,
        "slug": note.slug,
        "version": note.version,
        "status": note.status,
        "author_type": note.author_type,
    }


async def studio_vault_search(
    ctx: Context,
    q: str | None = None,
    scope: str | None = None,
    project_id: str | None = None,
    note_type: list[str] | None = None,
    status: list[str] | None = None,
    include_superseded: bool = False,
    path: list[str] | None = None,
    task_id: str | None = None,
    limit: int = VAULT_SEARCH_LIMIT_DEFAULT,
    max_chars: int = VAULT_SEARCH_MAX_CHARS_DEFAULT,
) -> dict[str, Any]:
    """Search the vault notes the caller may read. At least one of `q` (full
    text), `path` or `task_id` is required. `scope` (studio|project) and
    `project_id` narrow the scope; `note_type`/`status` are repeatable filters;
    superseded notes are excluded unless `include_superseded` or an explicit
    `status`. Hits carry a summary plus a short snippet, never the body."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        if q is not None and len(q) > _SEARCH_Q_MAX:
            return _invalid_arguments(f"q must be at most {_SEARCH_Q_MAX} characters")
        parsed_scope = _scope(scope)
        if isinstance(parsed_scope, dict):
            return parsed_scope
        parsed_project_id = None
        if project_id is not None:
            parsed = parse_uuid(project_id, "project_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_project_id = parsed
        parsed_task_id = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_task_id = parsed
        note_types = _enum_list(note_type, VaultNoteType, "note_type")
        if isinstance(note_types, dict):
            return note_types
        statuses = _enum_list(status, VaultNoteStatus, "status")
        if isinstance(statuses, dict):
            return statuses
        if path is not None and len(path) > VAULT_SEARCH_PATHS_MAX:
            return _invalid_arguments(f"path accepts at most {VAULT_SEARCH_PATHS_MAX} entries")
        bounded_limit = _bounded(limit, 1, VAULT_SEARCH_LIMIT_MAX, "limit")
        if isinstance(bounded_limit, dict):
            return bounded_limit
        bounded_max_chars = _bounded(
            max_chars, _SEARCH_MAX_CHARS_MIN, VAULT_SEARCH_MAX_CHARS_MAX, "max_chars"
        )
        if isinstance(bounded_max_chars, dict):
            return bounded_max_chars
        result = await vault_service.search_notes(
            session,
            principal,
            q=q,
            scope=parsed_scope,
            project_id=parsed_project_id,
            note_types=note_types,
            statuses=statuses,
            include_superseded=include_superseded,
            paths=path or [],
            task_id=parsed_task_id,
            limit=bounded_limit,
            max_chars=bounded_max_chars,
        )
        return result.model_dump(mode="json")

    return await run_tool(ctx, _handler)


async def studio_vault_read(
    note_id: str,
    ctx: Context,
    max_chars: int = _READ_MAX_CHARS_DEFAULT,
) -> dict[str, Any]:
    """Read one vault note in full (note_id UUID string), links included. The
    body is cut at `max_chars` characters and `body_truncated` then says so;
    call again with a larger budget for the rest. A project note the caller
    cannot read answers `forbidden`."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(note_id, "note_id")
        if isinstance(parsed, dict):
            return parsed
        bounded_max_chars = _bounded(max_chars, 1, VAULT_BODY_MAX, "max_chars")
        if isinstance(bounded_max_chars, dict):
            return bounded_max_chars
        note = await vault_service.serialize_note(
            session, await vault_service.read_note(session, principal, parsed)
        )
        dumped = note.model_dump(mode="json")
        body = dumped["body"]
        dumped["body"] = body[:bounded_max_chars]
        dumped["body_truncated"] = len(body) > bounded_max_chars
        return dumped

    return await run_tool(ctx, _handler)


async def studio_vault_write(
    scope: str,
    slug: str,
    title: str,
    body: str,
    ctx: Context,
    project_id: str | None = None,
    note_id: str | None = None,
    expected_version: int | None = None,
    summary: str | None = None,
    note_type: str | None = None,
    tags: list[str] | None = None,
    links: list[VaultNoteLink] | None = None,
    anchors: list[str] | None = None,
    change_summary: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create or rewrite a vault note. Without `note_id`: a new note
    (`scope` studio|project, `project_id` required for a project note, `slug`
    unique in its scope). With `note_id`: a full rewrite of title and body —
    `expected_version` is then required and a stale value fails with
    `version_conflict` carrying the live server version. `note_type` only
    applies to a creation. The note is always written `proposed`: validating or
    archiving one stays a human action. A slug already taken answers
    `vault_slug_conflict`, and a body/summary/title carrying a credential is
    refused with `secret_detected`. `idempotency_key` only applies to a
    creation — replaying the same key returns the original note instead of a
    duplicate."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_project_id = None
        if project_id is not None:
            parsed = parse_uuid(project_id, "project_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_project_id = parsed
        # Shared payload: `extra="forbid"` means a key that does not belong to
        # the branch taken below is a caller error, not something to drop.
        content: dict[str, Any] = {"title": title, "body": body}
        for key, value in (
            ("summary", summary),
            ("tags", tags),
            ("links", links),
            ("anchors", anchors),
        ):
            if value is not None:
                content[key] = value

        if note_id is None:
            create_payload: dict[str, Any] = {"scope": scope, "slug": slug, **content}
            create_payload["status"] = _STATUS_WRITTEN_BY_AN_AGENT
            if parsed_project_id is not None:
                create_payload["project_id"] = parsed_project_id
            if note_type is not None:
                create_payload["note_type"] = note_type
            try:
                note_in = VaultNoteCreate.model_validate(create_payload)
            except ValidationError as exc:
                return _invalid_arguments(_validation_message(exc))
            # Ahead of `run_idempotent_dict`'s replay short-circuit — see
            # `routers/vault.py::create_note` for why (DEC-0036).
            vault_service.authorize_create(principal, note_in)

            async def _create() -> dict[str, Any]:
                note = await vault_service.create_note(
                    session, principal, note_in, VaultActorType.AGENT
                )
                return _compact_note(note)

            request_hash = idempotency_service.hash_request(
                json.dumps(note_in.model_dump(mode="json"), sort_keys=True).encode()
            )
            return await idempotency_service.run_idempotent_dict(
                session, idempotency_key, "MCP studio_vault_write", request_hash, _create
            )

        parsed_note_id = parse_uuid(note_id, "note_id")
        if isinstance(parsed_note_id, dict):
            return parsed_note_id
        if expected_version is None:
            return _invalid_arguments("expected_version is required to update a note")
        update_payload: dict[str, Any] = {"expected_version": expected_version, **content}
        update_payload["status"] = _STATUS_WRITTEN_BY_AN_AGENT
        if change_summary is not None:
            update_payload["change_summary"] = change_summary
        try:
            update_in = VaultNoteUpdate.model_validate(update_payload)
        except ValidationError as exc:
            return _invalid_arguments(_validation_message(exc))
        note = await vault_service.update_note(
            session, principal, parsed_note_id, update_in, VaultActorType.AGENT
        )
        return _compact_note(note)

    return await run_tool(ctx, _handler)
