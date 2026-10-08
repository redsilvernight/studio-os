"""P10 — server decisions -> DEC_EXPORT.json -> Markdown export."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from scripts import dec_export
from scripts.adr_common import parse_adr_markdown

PROJECT = "2a836038-153c-41cf-879a-73bd794760b0"


def _decision(rid: str, title: str, status: str = "accepted", **extra):
    return {
        "id": f"d-{rid}",
        "readable_id": rid,
        "project_id": PROJECT,
        "task_id": None,
        "title": title,
        "body": f"Corps serveur {rid}",
        "status": status,
        "created_at": "2026-05-01T10:00:00Z",
        **extra,
    }


def _note(rid: str, title: str, status: str = "validated", links=(), body=None):
    return {
        "id": f"n-{rid}",
        "readable_id": rid,
        "note_type": "decision",
        "title": title,
        "status": status,
        "created_at": "2026-04-01T10:00:00Z",
        "links": list(links),
        "body": body if body is not None else f"# {rid} — {title}\n\nCorps vault {rid}",
    }


def _snapshot():
    decisions = [
        _decision("DEC-0002", "Remplace", task_id="t-1"),
        _decision("DEC-0001", "Ancienne", status="superseded"),
    ]
    notes = [
        _note("DEC-0001", "Ancienne", status="superseded"),
        _note(
            "DEC-0002", "Remplace", links=[{"target_note_id": "n-DEC-0001", "kind": "supersedes"}]
        ),
        _note("DEC-0010", "Vault seule", status="proposed"),
        {**_note("X-1", "Pas une DEC"), "note_type": "knowledge"},
    ]
    return dec_export.build_snapshot(PROJECT, decisions, notes)


def test_build_snapshot_merges_server_and_vault():
    snap = _snapshot()
    assert snap["format"] == dec_export.DEC_EXPORT_FORMAT
    by_id = {d["readable_id"]: d for d in snap["decisions"]}
    assert list(by_id) == ["DEC-0001", "DEC-0002", "DEC-0010"]
    assert by_id["DEC-0001"]["status"] == "superseded"
    assert by_id["DEC-0001"]["superseded_by"] == ["DEC-0002"]
    assert by_id["DEC-0002"]["supersedes"] == ["DEC-0001"]
    assert by_id["DEC-0002"]["task_id"] == "t-1"
    assert by_id["DEC-0002"]["date"] == "2026-05-01"
    assert by_id["DEC-0002"]["body_source"] == "vault"
    assert by_id["DEC-0010"] == {
        "readable_id": "DEC-0010",
        "title": "Vault seule",
        "status": "proposed",
        "date": "2026-04-01",
        "task_id": None,
        "supersedes": [],
        "superseded_by": [],
        "body": "# DEC-0010 — Vault seule\n\nCorps vault DEC-0010",
        "body_source": "vault",
    }


def test_build_snapshot_number_collision_keeps_the_note():
    """DEC-0192: the numbered note is the decision; the server row is a legacy variant."""
    snap = dec_export.build_snapshot(
        PROJECT,
        [_decision("DEC-0086", "Desktop P0 : Tauri 2 shell", status="superseded", task_id="t-9")],
        [_note("DEC-0086", "Roadmaps P2/P3 : domaine et persistance")],
    )
    (entry,) = snap["decisions"]
    assert entry["title"] == "Roadmaps P2/P3 : domaine et persistance"
    assert entry["status"] == "accepted"
    assert entry["task_id"] is None and entry["date"] == "2026-04-01"


def test_build_snapshot_falls_back_to_decision_body():
    snap = dec_export.build_snapshot(PROJECT, [_decision("DEC-0003", "Sans note")], [])
    (entry,) = snap["decisions"]
    assert entry["body"] == "Corps serveur DEC-0003"
    assert entry["body_source"] == "decision"


def _write_snapshot(root: Path, snap) -> None:
    (root / "docs" / "decisions").mkdir(parents=True)
    (root / dec_export.SNAPSHOT_RELPATH).write_text(
        dec_export.dump_snapshot(snap), encoding="utf-8"
    )


def test_render_apply_is_idempotent_and_check_detects_drift(tmp_path, capsys):
    _write_snapshot(tmp_path, _snapshot())
    orphan = tmp_path / "docs" / "decisions" / "DU0-A-legacy.md"
    orphan.write_text("legacy", encoding="utf-8")
    preamble = tmp_path / "docs" / "decisions" / "_preamble.md"
    preamble.write_text("Preambule.", encoding="utf-8")

    assert dec_export.main(["render", "--root", str(tmp_path), "--check"]) == 1
    assert dec_export.main(["render", "--root", str(tmp_path), "--apply"]) == 0
    assert "supprime : docs/decisions/DU0-A-legacy.md" in capsys.readouterr().out
    assert not orphan.exists() and preamble.exists()
    assert dec_export.main(["render", "--root", str(tmp_path), "--check"]) == 0

    adr = tmp_path / "docs" / "decisions" / "DEC-0002-remplace.md"
    fields, body = parse_adr_markdown(adr.read_text(encoding="utf-8"))
    assert fields["supersedes"] == ["DEC-0001"] and fields["source"] == "server-export"
    assert body.strip() == "Corps vault DEC-0002"
    index = (tmp_path / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "Preambule." in index and "| DEC-0010 | Vault seule | proposed |" in index

    adr.write_text(adr.read_text(encoding="utf-8") + "edit manuel\n", encoding="utf-8")
    assert dec_export.main(["render", "--root", str(tmp_path), "--check"]) == 1


def test_compare_flags_lost_decisions(tmp_path):
    _write_snapshot(tmp_path, _snapshot())
    decisions_dir = tmp_path / "docs" / "decisions"
    (decisions_dir / "DU0-A.md").write_text(
        "---\nid: DU0-A\ntitle: Remplace\nserver_readable_id: DEC-0002\n---\n\n"
        "# DU0-A — Remplace\n",
        encoding="utf-8",
    )
    index = tmp_path / "docs" / "DECISIONS.md"
    index.write_text(
        "| ID | Titre | Statut | ADR |\n|---|---|---|---|\n"
        "| DEC-0001 | Ancienne | accepted | x |\n",
        encoding="utf-8",
    )
    lost, extra = dec_export.compare(tmp_path, _snapshot())
    assert lost == [] and extra == ["DEC-0010"]

    index.write_text(index.read_text(encoding="utf-8").replace("Ancienne", "Tout autre sujet"))
    assert dec_export.compare(tmp_path, _snapshot())[0] == ["DEC-0001"]
    index.unlink()

    (decisions_dir / "DEC-0042-perdue.md").write_text(
        "---\nid: DEC-0042\ntitle: Perdue\n---\n\n# DEC-0042 — Perdue\n", encoding="utf-8"
    )
    assert dec_export.compare(tmp_path, _snapshot())[0] == ["DEC-0042"]
    assert dec_export.main(["compare", "--root", str(tmp_path)]) == 1


def test_compare_ignores_local_id_replaced_by_server_id(tmp_path):
    """A file renumbered by the server keeps its old local id: not a loss."""
    _write_snapshot(tmp_path, _snapshot())
    (tmp_path / "docs" / "decisions" / "DEC-0001-locale.md").write_text(
        "---\nid: DEC-0001\ntitle: Vault seule\nserver_readable_id: DEC-0010\n---\n\n"
        "# DEC-0001 — Vault seule\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "DECISIONS.md").write_text(
        "| ID | Titre | Statut | ADR |\n|---|---|---|---|\n"
        "| DEC-0001 | Vault seule | accepted | x |\n",
        encoding="utf-8",
    )
    assert dec_export.compare(tmp_path, _snapshot()) == ([], ["DEC-0001", "DEC-0002"])


def test_fetch_snapshot_pages_vault_and_reads_bodies():
    notes = {n["id"]: n for n in (_note("DEC-0001", "Ancienne"), _note("DEC-0002", "Remplace"))}
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization"))
        path = request.url.path
        if path == "/api/v1/decisions":
            assert request.url.params["project_id"] == PROJECT
            return httpx.Response(200, json=[_decision("DEC-0001", "Ancienne")])
        if path == "/api/v1/vault/tree":
            if request.url.params.get("cursor") == "p2":
                summary = {k: v for k, v in notes["n-DEC-0002"].items() if k != "body"}
                return httpx.Response(200, json={"items": [summary], "next_cursor": None})
            summary = {k: v for k, v in notes["n-DEC-0001"].items() if k != "body"}
            return httpx.Response(200, json={"items": [summary], "next_cursor": "p2"})
        note_id = path.rsplit("/", 1)[1]
        return httpx.Response(200, json=notes[note_id])

    client = httpx.Client(
        base_url="https://studio.test",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer t"},
    )
    snap = dec_export.fetch_snapshot(client, PROJECT)
    assert [d["readable_id"] for d in snap["decisions"]] == ["DEC-0001", "DEC-0002"]
    assert snap["decisions"][1]["status"] == "accepted"
    assert set(seen_auth) == {"Bearer t"}
    assert json.loads(dec_export.dump_snapshot(snap)) == snap


def test_fetch_waits_out_rate_limit():
    calls = {"n": 0}
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/decisions":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "3"})
            return httpx.Response(200, json=[_decision("DEC-0001", "Ancienne")])
        return httpx.Response(404)

    client = httpx.Client(base_url="https://studio.test", transport=httpx.MockTransport(handler))
    snap = dec_export.fetch_snapshot(client, PROJECT, sleep=waits.append)
    assert waits == [3.0]
    assert [d["readable_id"] for d in snap["decisions"]] == ["DEC-0001"]
