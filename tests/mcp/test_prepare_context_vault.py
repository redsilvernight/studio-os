"""P07 (DEC-0187 D6) — vault notes in the bounded project context.

Needs Postgres (same as the rest of `tests/mcp/`); runs in CI.
Scenario: a project accumulates notes (anchored to a task, anchored to a
declared path, one link away, one purely lexical) and an Agent asks for its
context: summary and search snippet only, never the body, and nothing at all
when the vault holds no readable note for the request.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import projects as projects_service
from studio_api.services import tasks as tasks_service
from studio_api.services import vault as vault_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.tasks import TaskCreate
from studio_contracts.vault import (
    VaultLinkKind,
    VaultNoteCreate,
    VaultNoteLink,
    VaultNoteStatus,
    VaultNoteUpdate,
    VaultScope,
)
from studio_mcp.tools.context import studio_prepare_context

from tests.mcp.conftest import FakeContext

Machine = tuple[MachineModel, str]

CLAIMS_PATH = "services/api/src/studio_api/services/claims.py"
BASE_KEYS = {
    "project",
    "query_terms",
    "task",
    "related_tasks",
    "decisions",
    "rules",
    "skills",
    "ai_work",
    "active_work",
    "returned",
    "additional_available",
    "omitted_for_budget",
    "limits",
}


def dump(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    assert isinstance(result, dict)
    return result


async def _principal(db_session: AsyncSession, machine: Machine) -> Principal:
    return await load_principal(db_session, machine[0])


async def _project(db_session) -> ProjectModel:
    return await projects_service.create_project(
        db_session, f"vault-{uuid.uuid4().hex[:8]}", "Vault Project", None, creator=None
    )


async def _task(db_session, principal, project, title="Migrate claim TTL index") -> Any:
    return await tasks_service.create_task(
        db_session,
        principal,
        TaskCreate(project_id=project.id, title=title, description="work"),
    )


async def _note(
    db_session,
    principal,
    *,
    project_id: uuid.UUID | None,
    scope: VaultScope = VaultScope.PROJECT,
    title: str,
    summary: str = "",
    body: str = "corps",
    status: VaultNoteStatus = VaultNoteStatus.PROPOSED,
    note_type: str = "note",
    anchors: list[str] | None = None,
    links: list[VaultNoteLink] | None = None,
):
    return await vault_service.create_note(
        db_session,
        principal,
        VaultNoteCreate.model_validate(
            {
                "scope": scope,
                "project_id": project_id,
                "slug": f"n-{uuid.uuid4().hex[:10]}",
                "note_type": note_type,
                "title": title,
                "summary": summary,
                "body": body,
                "status": status,
                "anchors": anchors or [],
                "links": links or [],
            }
        ),
    )


async def _set_status(db_session, principal, note, status: VaultNoteStatus):
    return await vault_service.update_note(
        db_session,
        principal,
        note.id,
        VaultNoteUpdate(expected_version=note.version, status=status),
    )


async def _prepare(auth_ctx, project, objective, **kwargs):
    return dump(
        await studio_prepare_context(str(project.id), auth_ctx, objective=objective, **kwargs)
    )


async def test_task_anchored_validated_note_is_vault_anchor(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project)
    anchored = await _note(
        db_session,
        principal,
        project_id=project.id,
        title="Index TTL sur les claims",
        summary="Un index partiel sur expires_at garde les verifications de claim rapides.",
        anchors=[f"task:{task.id}"],
    )
    await _set_status(db_session, principal, anchored, VaultNoteStatus.VALIDATED)
    unrelated = await _note(
        db_session,
        principal,
        project_id=project.id,
        title="Repeindre la banniere du dashboard",
        summary="Zephyr quokka sans rapport avec le chantier.",
    )

    result = await _prepare(auth_ctx, project, "migrer index ttl claims", task_id=str(task.id))

    assert result["returned"]["notes"] == 1
    assert result["additional_available"]["notes"] == 0
    (entry,) = result["notes"]
    assert entry["id"] == str(anchored.id)
    assert entry["why"]["reason"] == "vault_anchor"
    assert entry["scope"] == "project"
    assert entry["status"] == "validated"
    assert entry["note_type"] == "note"
    assert entry["slug"] == anchored.slug
    assert "expires_at" in entry["summary"]
    assert "corps" not in entry["summary"]
    assert "body" not in entry
    assert unrelated.id not in {hit["id"] for hit in result["notes"]}


async def test_path_anchored_project_and_studio_notes(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    project_note = await _note(
        db_session,
        principal,
        project_id=project.id,
        title="TTL des claims",
        summary="Reference du projet pour les claims.",
        anchors=[f"path:{CLAIMS_PATH}"],
    )
    studio_note = await _note(
        db_session,
        principal,
        project_id=None,
        scope="studio",
        title="Convention vault transverse",
        summary="Reference du studio pour les claims.",
        anchors=[f"path:{CLAIMS_PATH}"],
    )

    result = await _prepare(auth_ctx, project, "ttl claims", files=[CLAIMS_PATH])

    assert {entry["id"] for entry in result["notes"]} == {
        str(project_note.id),
        str(studio_note.id),
    }
    assert {entry["scope"] for entry in result["notes"]} == {"project", "studio"}
    assert all(entry["why"]["reason"] == "vault_anchor" for entry in result["notes"])
    assert result["returned"]["notes"] == 2


async def test_note_one_link_away_is_vault_link(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project)
    anchored = await _note(
        db_session,
        principal,
        project_id=project.id,
        title="Ancre vault des claims",
        summary="Point d'entree du dossier claims.",
        anchors=[f"task:{task.id}"],
    )
    neighbour = await _note(
        db_session,
        principal,
        project_id=project.id,
        title="Detail du TTL claims",
        summary="Le voisin, une seule liee plus loin.",
        note_type="lesson",
        links=[VaultNoteLink(target_note_id=anchored.id, kind=VaultLinkKind.LINKS_TO)],
    )

    result = await _prepare(auth_ctx, project, "claims ttl", task_id=str(task.id))

    reasons = {entry["title"]: entry["why"]["reason"] for entry in result["notes"]}
    assert reasons == {
        "Ancre vault des claims": "vault_anchor",
        "Detail du TTL claims": "vault_link",
    }
    assert next(e for e in result["notes"] if e["id"] == str(neighbour.id))["note_type"] == "lesson"


async def test_lexical_note_reports_matched_terms(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _note(
        db_session,
        principal,
        project_id=project.id,
        title="Convention de renommage zephyr",
        summary="Les quokka restent en minuscules.",
        body="Une longue phrase de contexte qui ne sert qu'au snippet du corps.",
    )

    result = await _prepare(auth_ctx, project, "convention renommage zephyr quokka repeindre")

    assert result["returned"]["notes"] == 1
    (entry,) = result["notes"]
    assert entry["why"]["reason"] == "lexical"
    assert "zephyr" in entry["why"]["matched_terms"]
    assert "quokka" in entry["why"]["matched_terms"]
    assert "repeindre" not in entry["why"]["matched_terms"]
    assert entry["truncated"] is False
    assert entry["snippet"]


async def test_draft_and_superseded_notes_excluded(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project)
    draft = await _note(
        db_session,
        principal,
        project_id=project.id,
        title="Brouillon vault claims",
        summary="Pas encore partage.",
        status="draft",
        anchors=[f"task:{task.id}"],
    )
    superseded = await _note(
        db_session,
        principal,
        project_id=project.id,
        title="Note vault claims remplacee",
        summary="Remplacee par une autre.",
        anchors=[f"task:{task.id}"],
    )
    await _set_status(db_session, principal, superseded, VaultNoteStatus.SUPERSEDED)

    result = await _prepare(auth_ctx, project, "vault claims", task_id=str(task.id))

    assert "notes" not in result
    assert "notes" not in result["returned"]
    assert "notes" not in result["additional_available"]
    assert "notes" not in result["omitted_for_budget"]
    assert draft.id not in {entry["id"] for entry in result.get("notes", [])}


async def test_notes_have_own_budget_slice(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project)
    for index in range(4):
        await _note(
            db_session,
            principal,
            project_id=project.id,
            title=f"Note claims {index}",
            summary="c" * 300,
            anchors=[f"task:{task.id}"],
        )

    result = await _prepare(auth_ctx, project, "claims", task_id=str(task.id), max_chars=2_000)

    assert result["limits"]["chars_used"] <= 2_000
    assert result["returned"]["notes"] == 1
    assert result["omitted_for_budget"]["notes"] == 3
    assert result["additional_available"]["notes"] == 3


async def test_no_note_keys_when_vault_exposes_nothing(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project)

    result = await _prepare(auth_ctx, project, "migrer index ttl claims", task_id=str(task.id))

    assert set(result) == BASE_KEYS
    assert "notes" not in result["returned"]
    assert "notes" not in result["additional_available"]
    assert "notes" not in result["omitted_for_budget"]


async def test_known_content_hash_returns_note_unchanged(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project)
    await _note(
        db_session,
        principal,
        project_id=project.id,
        title="Reference vault claims",
        summary="s" * 500,
        body="Un corps beaucoup plus long que le resume, pour le snippet.",
        anchors=[f"task:{task.id}"],
    )

    first = await _prepare(auth_ctx, project, "claims", task_id=str(task.id))
    (before,) = first["notes"]
    second = await _prepare(
        auth_ctx,
        project,
        "claims",
        task_id=str(task.id),
        known_ids={before["id"]: before["content_hash"]},
    )

    assert second["returned"]["notes"] == 1
    (after,) = second["notes"]
    assert after["unchanged"] is True
    assert "summary" not in after
    assert "snippet" not in after
    assert "truncated" not in after
    assert after["title"] == before["title"]
    assert after["content_hash"] == before["content_hash"]
    assert after["why"] == before["why"]
    assert second["limits"]["chars_used"] < first["limits"]["chars_used"]


async def test_unreadable_vault_is_flagged_not_fatal(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext, monkeypatch
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project)
    await _note(
        db_session,
        principal,
        project_id=project.id,
        title="Reference vault claims",
        summary="Le vault ne repond pas.",
        anchors=[f"task:{task.id}"],
    )

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("vault indisponible")

    monkeypatch.setattr(vault_service, "search_notes", _boom)

    result = await _prepare(auth_ctx, project, "claims", task_id=str(task.id))

    assert result["unavailable"] == ["vault"]
    assert "notes" not in result
    assert "notes" not in result["returned"]
    assert result["task"]["id"] == str(task.id)
