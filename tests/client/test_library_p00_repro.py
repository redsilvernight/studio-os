"""P00-repro: one strict xfail per Library sync gap, plus a request-count
measurement. Each xfail states the EXPECTED behaviour and fails today; when a
later step fixes the gap the strict xfail flips to a failure and must be
removed. See docs/library/roadmap-p0/P00-repro.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.daemon import skills_bridge
from studio_client.publish import build_publish_items
from studio_client.tokens import MemoryTokenStore

from tests.client.test_daemon_library_sync import ORIGIN, _config, _patch_fetch, _projection

REPO = Path(__file__).resolve().parents[2]
BATCH = "/api/v1/library/versions/batch-get"


def _resources(count: int) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """`count` studio-scope resources spread over rule / skill / agent_definition."""
    kinds = ("rule", "skill", "agent_definition")
    rows: list[dict[str, Any]] = []
    versions: dict[str, dict[str, Any]] = {}
    for index in range(count):
        kind = kinds[index % 3]
        rid = str(uuid4())
        rows.append(
            {
                "id": rid,
                "kind": kind,
                "stable_key": f"{kind.replace('_', '-')}-{index}",
                "scope": "studio",
                "status": "active",
                "active_version": 1,
                "version": 1,
                "created_at": "2026-09-17T12:00:00+00:00",
                "updated_at": "2026-09-17T12:00:00+00:00",
            }
        )
        content: dict[str, Any] = {"content_schema": f"studio.library.{kind}/v1"}
        if kind == "agent_definition":
            content.update(summary="s", intended_use="u")
        else:
            content["text"] = "body"
        versions[rid] = {
            "id": str(uuid4()),
            "resource_id": rid,
            "version": 1,
            "title": f"{kind} {index}",
            "description": None,
            "content": content,
            "created_at": "2026-09-17T12:00:00+00:00",
        }
    return rows, versions


def _install_http(monkeypatch: pytest.MonkeyPatch, count: int) -> list[str]:
    """Route skills_bridge's API client to an in-memory server; returns the
    list of requests seen (`METHOD path`)."""
    rows, versions = _resources(count)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(f"{request.method} {path}")
        if path == "/api/v1/library":
            params = request.url.params
            page = [r for r in rows if params.get("kind") in (None, r["kind"])]
            offset, limit = int(params.get("offset", 0)), int(params.get("limit", 100))
            return httpx.Response(200, json=page[offset : offset + limit])
        if path == BATCH:
            refs = json.loads(request.content)["items"]
            items = [
                {
                    "resource_id": r["resource_id"],
                    "version": r["version"],
                    "status": "ok",
                    "detail": versions[r["resource_id"]],
                }
                for r in refs
            ]
            return httpx.Response(200, json={"items": items})
        return httpx.Response(404, json={"detail": "not found"})

    def factory(config: ClientConfig, store: MemoryTokenStore) -> StudioApiClient:
        return StudioApiClient(config, store, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(skills_bridge, "StudioApiClient", factory)
    return seen


def _http_config() -> tuple[ClientConfig, MemoryTokenStore]:
    store = MemoryTokenStore()
    store.set_token(ORIGIN, "tok")
    return ClientConfig(api_base_url=ORIGIN, profile_id="main", machine_id=uuid4()), store


# --- Measurement (passing): requests per full Library fetch -----------------


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (10, {"library": 2, "batch": 2}),
        (50, {"library": 2, "batch": 2}),
        (100, {"library": 2, "batch": 3}),
    ],
)
def test_requests_per_sync_for_n_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int, expected: dict[str, int]
) -> None:
    """Current cost of ONE auto-sync run (and of one preview): 2 listings
    (rule+skill, then agent_definition) + ceil(n_kind/50) batch reads per
    fetch. Printed with `-s` for the P00-repro table."""
    seen = _install_http(monkeypatch, count)
    config, store = _http_config()
    home = tmp_path / "home"
    home.mkdir()
    skills_bridge._AutoSyncRunner(config, store, home, tmp_path / "data")._run()
    counts = {
        "library": sum(1 for r in seen if r.endswith("/api/v1/library")),
        "batch": sum(1 for r in seen if r.endswith("batch-get")),
    }
    print(f"N={count}: total={len(seen)} {counts}")
    assert counts == expected
    seen.clear()
    skills_bridge.preview_skills(config, store, home=home)
    assert len(seen) == sum(expected.values())  # preview refetches everything


# --- Gap 1: no resync after the first run -----------------------------------


@pytest.mark.xfail(strict=True, reason="gap 1: runner never reruns after its first sync (_started)")
def test_runner_resyncs_when_a_new_version_is_activated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config, store = _config(home, tmp_path / "data")
    runner = skills_bridge._AutoSyncRunner(config, store, home, tmp_path / "data")
    _patch_fetch(monkeypatch, [_projection("coding", "rule", "Version one")])
    runner.start()
    assert runner._thread is not None
    runner._thread.join(5)
    _patch_fetch(monkeypatch, [_projection("coding", "rule", "Version two", version=2)])
    runner.start()  # only public entry point; stands for "library.version.activated"
    if runner._thread is not None:
        runner._thread.join(5)
    assert "Version two" in (home / ".agents/rules/coding.md").read_text(encoding="utf-8")


# --- Gap 2: listing is capped at 100 rows, no pagination --------------------


@pytest.mark.xfail(
    strict=True, reason="gap 2: _SKILL_LIMIT=100 truncates the listing, no offset paging"
)
def test_sync_projects_every_resource_beyond_one_listing_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_http(monkeypatch, 150)  # 50 rules, 50 skills, 50 agents
    config, store = _http_config()
    projections = skills_bridge._fetch_projections(config, store)
    assert len(projections) == 150


# --- Gap 3: one local conflict blocks the whole sync ------------------------


@pytest.mark.xfail(
    strict=True,
    reason="gap 3: a locally modified target aborts the whole run (see test_daemon_library_sync)",
)
def test_conflict_on_one_item_does_not_block_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    edited = home / ".claude" / "rules" / "coding-standard.md"
    edited.parent.mkdir(parents=True)
    edited.write_text("hand edited\n", encoding="utf-8")
    _patch_fetch(
        monkeypatch,
        [
            _projection("studio-git-flow", "skill", "Skill body"),
            _projection("coding-standard", "rule", "Rule body"),
        ],
    )
    config, store = _config(home, tmp_path / "data")
    skills_bridge._AutoSyncRunner(config, store, home, tmp_path / "data")._run()
    assert edited.read_text(encoding="utf-8") == "hand edited\n"  # override kept
    assert (home / ".agents" / "skills" / "studio-git-flow" / "SKILL.md").exists()


# --- Gap 4: agents and rules lose fields on publish --------------------------


@pytest.mark.xfail(strict=True, reason="gap 4: rule payload carries no applies_to")
def test_published_rule_keeps_applies_to() -> None:
    (item,) = build_publish_items(REPO, kinds=("rule",), keys=["contracts"])
    assert item.content.get("applies_to")


@pytest.mark.xfail(strict=True, reason="gap 4: agent payload drops instructions/edit_policy/tools")
def test_published_agent_keeps_instructions_and_edit_policy() -> None:
    (item,) = build_publish_items(REPO, kinds=("agent",), keys=["studio-tester"])
    assert item.content.get("instructions")
    assert item.content.get("edit_policy") == "deny"
    assert item.content.get("tools")
