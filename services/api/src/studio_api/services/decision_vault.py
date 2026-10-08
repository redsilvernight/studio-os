from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.decisions import DecisionStatus
from studio_contracts.vault import (
    VAULT_BODY_MAX,
    VAULT_TITLE_MAX,
    VaultActorType,
    VaultLinkKind,
    VaultNoteLink,
    VaultNoteStatus,
    VaultNoteType,
    VaultScope,
)

from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.vault import VaultNoteLinkModel, VaultNoteModel
from studio_api.services.vault import _append_version, _compute_hash, _reject_secrets, load_links
from studio_api.services.vault_decision_import import _slug, _summary, clean_title

_NOTE_STATUS: dict[str, VaultNoteStatus] = {
    DecisionStatus.PROPOSED.value: VaultNoteStatus.PROPOSED,
    DecisionStatus.ACCEPTED.value: VaultNoteStatus.VALIDATED,
    DecisionStatus.SUPERSEDED.value: VaultNoteStatus.SUPERSEDED,
}


def invalid_supersede_link(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error_code": "invalid_decision_link", "message": detail},
    )


def reject_secrets(title: str, body: str) -> None:
    _reject_secrets({"title": title, "body": body})


def _scope(decision: DecisionModel) -> VaultScope:
    return VaultScope.PROJECT if decision.project_id is not None else VaultScope.STUDIO


def _author_type(decision: DecisionModel) -> VaultActorType:
    return VaultActorType.AGENT if decision.proposed_by_type == "agent" else VaultActorType.USER


async def _note_for(session: AsyncSession, readable_id: str) -> VaultNoteModel | None:
    return (
        await session.execute(
            select(VaultNoteModel)
            .where(VaultNoteModel.readable_id == readable_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def stage_note(
    session: AsyncSession, decision: DecisionModel, author_id: uuid.UUID
) -> VaultNoteModel:
    """Add the vault mirror of `decision` to the session (no commit)."""
    title = clean_title(decision.title)[:VAULT_TITLE_MAX] or decision.readable_id
    body = (decision.body or title)[:VAULT_BODY_MAX]
    summary = _summary(body)
    note_status = _NOTE_STATUS[decision.status].value
    anchors = [f"task:{decision.task_id}"] if decision.task_id is not None else []
    note = VaultNoteModel(
        scope=_scope(decision).value,
        project_id=decision.project_id,
        slug=_slug("decisions", decision.readable_id, decision.title),
        readable_id=decision.readable_id,
        note_type=VaultNoteType.DECISION.value,
        title=title,
        summary=summary,
        body=body,
        status=note_status,
        tags=[],
        anchors=anchors,
        content_hash=_compute_hash(title, summary, body, note_status, [], [], anchors),
        author_type=_author_type(decision).value,
        author_id=author_id,
    )
    session.add(note)
    await session.flush()
    await _append_version(session, note, [], None)
    return note


async def sync_status(
    session: AsyncSession, decision: DecisionModel, author_id: uuid.UUID
) -> VaultNoteModel:
    """Bring the decision's note to the decision's status, creating the note
    when the decision predates the vault (no commit)."""
    note = await _note_for(session, decision.readable_id)
    if note is None:
        return await stage_note(session, decision, author_id)
    target = _NOTE_STATUS[decision.status].value
    if note.status == target:
        return note
    links = await load_links(session, note.id)
    note.status = target
    note.version += 1
    note.author_type = VaultActorType.USER.value
    note.author_id = author_id
    note.content_hash = _compute_hash(
        note.title, note.summary, note.body, note.status, list(note.tags), links, list(note.anchors)
    )
    await _append_version(session, note, links, f"decision {decision.status}")
    return note


async def link_supersedes(
    session: AsyncSession,
    old_note: VaultNoteModel,
    replacement: DecisionModel,
    author_id: uuid.UUID,
) -> None:
    """Add a `supersedes` link from the replacement's note to `old_note`
    (no commit). A studio note cannot point at a project note."""
    if old_note.scope == VaultScope.PROJECT.value and replacement.project_id != old_note.project_id:
        raise invalid_supersede_link("replacement decision is outside the superseded one's project")
    new_note = await _note_for(session, replacement.readable_id)
    if new_note is None:
        new_note = await stage_note(session, replacement, author_id)
    links = await load_links(session, new_note.id)
    if any(
        link.target_note_id == old_note.id and link.kind is VaultLinkKind.SUPERSEDES
        for link in links
    ):
        return
    links.append(VaultNoteLink(target_note_id=old_note.id, kind=VaultLinkKind.SUPERSEDES))
    session.add(
        VaultNoteLinkModel(
            source_note_id=new_note.id,
            target_note_id=old_note.id,
            kind=VaultLinkKind.SUPERSEDES.value,
        )
    )
    new_note.version += 1
    new_note.author_type = VaultActorType.USER.value
    new_note.author_id = author_id
    new_note.content_hash = _compute_hash(
        new_note.title,
        new_note.summary,
        new_note.body,
        new_note.status,
        list(new_note.tags),
        links,
        list(new_note.anchors),
    )
    await _append_version(session, new_note, links, f"supersedes {old_note.readable_id}")
