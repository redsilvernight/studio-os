"""P11: read-only local mirror of the server vault. The server is an
`httpx.MockTransport`; the mirror is a SQLite file under `tmp_path`."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from studio_client.knowledge import KnowledgeError, ScopePolicy
from studio_client.knowledge.server_mirror import (
    ServerMirrorMemoryProvider,
    ServerVaultMirror,
)

PROJECT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER_PROJECT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
AUTHOR_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
OPEN = ScopePolicy(("global/", f"projects/{PROJECT_ID}/"))


def _note(
    slug: str,
    *,
    scope: str = "studio",
    project_id: uuid.UUID | None = None,
    body: str = "corps",
    status: str = "draft",
    version: int = 1,
) -> dict[str, Any]:
    digest = hashlib.sha256(f"{slug}:{body}:{status}:{version}".encode()).hexdigest()
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{scope}:{project_id}:{slug}")),
        "scope": scope,
        "project_id": str(project_id) if project_id else None,
        "slug": slug,
        "note_type": "note",
        "title": slug.title(),
        "summary": "",
        "status": status,
        "tags": ["t"],
        "links": [],
        "anchors": [],
        "content_hash": digest,
        "author_type": "user",
        "author_id": str(AUTHOR_ID),
        "version": version,
        "created_at": T0.isoformat(),
        "updated_at": T0.isoformat(),
        "body": body,
    }


class FakeServer:
    """Paginated `/vault/tree` plus `/vault/notes/{id}`; counts note fetches."""

    def __init__(self, notes: list[dict[str, Any]], page_size: int = 2) -> None:
        self.notes = {note["id"]: note for note in notes}
        self.page_size = page_size
        self.fetched: list[str] = []
        self.forbidden: set[str] = set()
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("offline", request=request)
        path = request.url.path
        if path == "/api/v1/vault/tree":
            ordered = sorted(self.notes.values(), key=lambda n: n["slug"])
            start = int(request.url.params.get("cursor", "0"))
            page = ordered[start : start + self.page_size]
            items = [{k: v for k, v in n.items() if k != "body"} for n in page]
            nxt = start + self.page_size
            return httpx.Response(
                200,
                json={"items": items, "next_cursor": str(nxt) if nxt < len(ordered) else None},
            )
        note_id = path.rsplit("/", 1)[-1]
        self.fetched.append(note_id)
        if note_id in self.forbidden:
            return httpx.Response(403, json={"detail": "forbidden"})
        if note_id not in self.notes:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=self.notes[note_id])

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler), base_url="http://studio.test"
        )


@pytest.fixture
def mirror(tmp_path: Path) -> ServerVaultMirror:
    return ServerVaultMirror(tmp_path / "cache" / "mirror.sqlite3", clock=lambda: T0)


async def _sync(mirror: ServerVaultMirror, server: FakeServer, scope: ScopePolicy = OPEN):
    async with server.client() as client:
        return await mirror.sync(client, scope)


async def test_incremental_sync_add_modify_delete_status(mirror: ServerVaultMirror) -> None:
    a, b, c = _note("alpha"), _note("bravo"), _note("charlie")
    server = FakeServer([a, b, c])

    first = await _sync(mirror, server)
    assert (first.added, first.updated, first.removed, first.total) == (3, 0, 0, 3)
    assert mirror.count() == 3

    server.fetched.clear()
    again = await _sync(mirror, server)
    assert (again.added, again.updated, again.unchanged, again.fetched) == (0, 0, 3, 0)
    assert server.fetched == []
    assert mirror.count() == 3

    server.notes[a["id"]] = _note("alpha", body="nouveau corps", version=2)
    server.notes[b["id"]] = _note("bravo", status="proposed", version=2)
    del server.notes[c["id"]]
    server.fetched.clear()
    delta = await _sync(mirror, server)
    assert (delta.added, delta.updated, delta.removed, delta.unchanged) == (0, 2, 1, 0)
    assert sorted(server.fetched) == sorted([a["id"], b["id"]])
    alpha = mirror.get(uuid.UUID(a["id"]))
    assert alpha is not None and alpha.body == "nouveau corps" and alpha.version == 2
    bravo = mirror.get(uuid.UUID(b["id"]))
    assert bravo is not None and bravo.status.value == "proposed"
    assert mirror.get(uuid.UUID(c["id"])) is None


async def test_offline_read_reports_freshness(mirror: ServerVaultMirror) -> None:
    server = FakeServer([_note("alpha", body="mot clef unique")])
    assert mirror.freshness().reason == "never_synced"
    await _sync(mirror, server)

    fresh = mirror.freshness(now=T0 + timedelta(minutes=5))
    assert (fresh.stale, fresh.reason, fresh.last_synced_at) == (False, "fresh", T0)
    old = mirror.freshness(now=T0 + timedelta(hours=2))
    assert (old.stale, old.reason) == (True, "older_than_threshold")

    server.down = True
    with pytest.raises(httpx.ConnectError):
        await _sync(mirror, server)
    failed = mirror.freshness()
    assert (failed.stale, failed.reason, failed.last_synced_at) == (True, "last_sync_failed", T0)
    assert failed.last_error is not None

    # Offline: reads keep working from the cache, flagged as stale.
    provider = ServerMirrorMemoryProvider(mirror, OPEN)
    result = provider.search("clef")
    assert [hit.path for hit in result.matches] == ["alpha"]
    assert result.reason == "mirror_last_sync_failed"
    assert provider.read("global/alpha").content == "mot clef unique"


async def test_closed_scope_by_default_mirrors_nothing(mirror: ServerVaultMirror) -> None:
    server = FakeServer([_note("alpha"), _note("p", scope="project", project_id=PROJECT_ID)])
    await _sync(mirror, server)
    assert mirror.count() == 2

    server.fetched.clear()
    report = await _sync(mirror, server, ScopePolicy())
    assert report.removed == 2
    assert mirror.count() == 0
    assert server.fetched == []

    provider = ServerMirrorMemoryProvider(mirror)
    assert provider.search("alpha").matches == []


async def test_mirror_holds_only_what_rights_and_scope_allow(
    mirror: ServerVaultMirror,
) -> None:
    mine = _note("mine", scope="project", project_id=PROJECT_ID)
    other = _note("other", scope="project", project_id=OTHER_PROJECT_ID)
    revoked = _note("revoked")
    server = FakeServer([_note("alpha"), mine, other, revoked])
    server.forbidden.add(revoked["id"])

    await _sync(mirror, server)
    slugs = {item.slug for item in mirror.list_notes()}
    assert slugs == {"alpha", "mine"}
    assert other["id"] not in server.fetched

    # A note dropped from the server tree (rights revoked) leaves the mirror.
    del server.notes[mine["id"]]
    await _sync(mirror, server)
    assert {item.slug for item in mirror.list_notes()} == {"alpha"}

    # Narrowing the scope purges what is no longer exposed.
    assert mirror.purge_out_of_scope(ScopePolicy((f"projects/{PROJECT_ID}/",))) == 1
    assert mirror.count() == 0


async def test_provider_is_read_only_and_scoped(mirror: ServerVaultMirror) -> None:
    server = FakeServer([_note("alpha"), _note("alpha", scope="project", project_id=PROJECT_ID)])
    await _sync(mirror, server)

    provider = ServerMirrorMemoryProvider(mirror, ScopePolicy(("global/",)))
    assert provider.read("alpha").path == "alpha"
    with pytest.raises(KnowledgeError) as exc:
        provider.read(f"projects/{PROJECT_ID}/alpha")
    assert exc.value.reason == KnowledgeError.OUT_OF_SCOPE
    with pytest.raises(KnowledgeError) as missing:
        provider.read("global/absent")
    assert missing.value.reason == KnowledgeError.NOT_FOUND
    with pytest.raises(KnowledgeError) as write:
        provider.propose({"title": "x"})  # type: ignore[arg-type]
    assert write.value.reason == KnowledgeError.WRITE_UNSUPPORTED
