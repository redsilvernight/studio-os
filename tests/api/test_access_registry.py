"""Fail-closed access registry and generated outsider matrix (DEC-0103 §12).

1. Every mounted HTTP operation is classified in `HTTP_ACCESS`; no entry is
   stale.
2. Every `project` operation has at least one outsider probe here, and every
   probe targets a `project` operation — the matrix is generated from the
   registry, so a new project route cannot ship without one.
3. An active User without membership (member of another project) sends each
   probe against a world built by a member: the answer is the canonical
   `403 forbidden` on `project`, or a collection that leaks none of the
   world's ids. SSE is covered by `GET /events/stream` (403 before opening).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.access_registry import HTTP_ACCESS, Operation, iter_operations
from studio_api.db.models.build import BuildModel
from studio_api.db.models.machine import MachineModel
from studio_api.main import app
from studio_api.middleware import RateLimitMiddleware

from tests.e2e.test_roadmaps_p10_e2e import _plan

pytestmark = pytest.mark.isolation


# --- 1. Inventory -----------------------------------------------------------


def test_every_route_is_classified_and_no_entry_is_stale() -> None:
    mounted = set(iter_operations(app))
    assert not mounted - HTTP_ACCESS.keys(), "unclassified routes (add them to HTTP_ACCESS)"
    assert not HTTP_ACCESS.keys() - mounted, "stale HTTP_ACCESS entries"


# --- 2. Probes ----------------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    """One outsider request. `path` and string leaves of `body` are formatted
    with the world (`{pid}`, `{task}`, ...).

    - `forbidden`: canonical `403` on `project`.
    - `filtered`: `200` leaking none of the world's ids.
    - `role`: `403 forbidden` raised by a role guard *before* any lookup, so
      the answer is the same for the world's resource and an unknown id.
    - `slug`: initialization by slug. The preview must not reveal the project
      (it plans a `create`); apply may only hit the global slug uniqueness
      (`409 {"detail": {"error_code": "conflict"}}`), the same answer
      `POST /projects` gives — never a write. Slugs are non-secret
      (accepted oracle): provisioning roles learn that a slug exists, nothing
      more (no id leaks)."""

    path: str
    body: dict[str, Any] | None = None
    expect: Literal["forbidden", "filtered", "role", "slug"] = "forbidden"
    headers: dict[str, str] = field(default_factory=dict)


_UNKNOWN = "00000000-0000-4000-8000-000000000000"
_V1 = {"If-Match-Version": "1"}
_RM = "/api/v1/roadmaps/{roadmap}"
_TR = "/api/v1/transfers/{transfer}"
_LIB = "/api/v1/library/{lib}"
_RULE = {"content_schema": "studio.library.rule/v1", "text": "Outsider rule."}

PROBES: dict[Operation, tuple[Probe, ...]] = {
    ("GET", "/api/v1/projects"): (Probe("/api/v1/projects", expect="filtered"),),
    ("GET", "/api/v1/projects/{project_id}"): (Probe("/api/v1/projects/{pid}"),),
    ("GET", "/api/v1/projects/{project_id}/state"): (Probe("/api/v1/projects/{pid}/state"),),
    ("GET", "/api/v1/projects/{project_id}/members"): (
        Probe("/api/v1/projects/{pid}/members", expect="role"),
        Probe(f"/api/v1/projects/{_UNKNOWN}/members", expect="role"),
    ),
    ("PUT", "/api/v1/projects/{project_id}/members/{user_id}"): (
        Probe("/api/v1/projects/{pid}/members/{outsider_user}", expect="role"),
        Probe(f"/api/v1/projects/{_UNKNOWN}/members/{{outsider_user}}", expect="role"),
    ),
    ("DELETE", "/api/v1/projects/{project_id}/members/{user_id}"): (
        Probe("/api/v1/projects/{pid}/members/{outsider_user}", expect="role"),
    ),
    ("POST", "/api/v1/projects/initialization/preview"): (
        Probe("/api/v1/projects/initialization/preview", {"$plan": True}, expect="slug"),
    ),
    ("POST", "/api/v1/projects/initialization/apply"): (
        Probe("/api/v1/projects/initialization/apply", {"plan": {"$plan": True}}, expect="slug"),
    ),
    ("GET", "/api/v1/tasks"): (
        Probe("/api/v1/tasks?project_id={pid}"),
        Probe("/api/v1/tasks", expect="filtered"),
    ),
    ("POST", "/api/v1/tasks"): (Probe("/api/v1/tasks", {"project_id": "{pid}", "title": "x"}),),
    ("GET", "/api/v1/tasks/{task_id}"): (Probe("/api/v1/tasks/{task}"),),
    ("PATCH", "/api/v1/tasks/{task_id}"): (
        Probe("/api/v1/tasks/{task}", {"title": "x"}, headers=_V1),
    ),
    ("POST", "/api/v1/tasks/{task_id}/claim"): (Probe("/api/v1/tasks/{task}/claim"),),
    ("POST", "/api/v1/tasks/{task_id}/release"): (Probe("/api/v1/tasks/{task}/release"),),
    ("GET", "/api/v1/sessions"): (Probe("/api/v1/sessions?task_id={task}"),),
    ("POST", "/api/v1/sessions"): (
        Probe("/api/v1/sessions", {"task_id": "{task}", "machine_id": "{outsider_machine}"}),
    ),
    ("PATCH", "/api/v1/sessions/{session_id}/end"): (Probe("/api/v1/sessions/{session}/end"),),
    ("GET", "/api/v1/claims"): (
        Probe("/api/v1/claims?project_id={pid}"),
        Probe("/api/v1/claims", expect="filtered"),
    ),
    ("POST", "/api/v1/claims"): (
        Probe(
            "/api/v1/claims",
            {
                "project_id": "{pid}",
                "resource_path": "src/x.py",
                "resource_type": "file",
                "ttl_seconds": 60,
            },
        ),
    ),
    ("POST", "/api/v1/claims/{claim_id}/renew"): (Probe("/api/v1/claims/{claim}/renew"),),
    ("DELETE", "/api/v1/claims/{claim_id}"): (Probe("/api/v1/claims/{claim}"),),
    ("GET", "/api/v1/decisions"): (
        Probe("/api/v1/decisions?project_id={pid}"),
        Probe("/api/v1/decisions", expect="filtered"),
    ),
    ("POST", "/api/v1/decisions"): (
        Probe(
            "/api/v1/decisions",
            {
                "project_id": "{pid}",
                "title": "x",
                "body": "x",
                "proposed_by_type": "user",
                "proposed_by_id": "{outsider_user}",
            },
        ),
    ),
    ("POST", "/api/v1/decisions/{decision_id}/accept"): (
        Probe("/api/v1/decisions/{decision}/accept", {}, expect="role"),
        Probe(f"/api/v1/decisions/{_UNKNOWN}/accept", {}, expect="role"),
    ),
    ("POST", "/api/v1/decisions/{decision_id}/supersede"): (
        Probe("/api/v1/decisions/{decision}/supersede", {}, expect="role"),
        Probe(f"/api/v1/decisions/{_UNKNOWN}/supersede", {}, expect="role"),
    ),
    ("GET", "/api/v1/library"): (
        Probe("/api/v1/library?project_id={pid}"),
        Probe("/api/v1/library", expect="filtered"),
    ),
    ("POST", "/api/v1/library"): (
        Probe(
            "/api/v1/library",
            {
                "kind": "rule",
                "stable_key": "outsider-rule",
                "scope": "project",
                "project_id": "{pid}",
                "title": "x",
                "content": _RULE,
            },
        ),
    ),
    ("GET", "/api/v1/library/{resource_id}"): (Probe(_LIB),),
    ("GET", "/api/v1/library/{resource_id}/versions"): (Probe(_LIB + "/versions"),),
    ("POST", "/api/v1/library/{resource_id}/versions"): (
        Probe(_LIB + "/versions", {"title": "x", "content": _RULE}),
    ),
    ("POST", "/api/v1/library/{resource_id}/activate"): (
        Probe(_LIB + "/activate", {"version": 1, "expected_resource_version": 1}),
    ),
    ("POST", "/api/v1/library/{resource_id}/deprecate"): (
        Probe(_LIB + "/deprecate", {"expected_resource_version": 1}),
    ),
    ("GET", "/api/v1/library-locks"): (Probe("/api/v1/library-locks?project_id={pid}"),),
    ("POST", "/api/v1/library-locks"): (
        Probe(
            "/api/v1/library-locks",
            {"project_id": "{pid}", "resource_id": "{lib}", "locked_version": 1},
        ),
    ),
    ("DELETE", "/api/v1/library-locks/{lock_id}"): (Probe("/api/v1/library-locks/{lock}"),),
    ("GET", "/api/v1/runtime-bindings"): (
        Probe("/api/v1/runtime-bindings?level=project_default&project_id={pid}"),
        Probe("/api/v1/runtime-bindings", expect="filtered"),
    ),
    ("POST", "/api/v1/runtime-bindings"): (
        Probe(
            "/api/v1/runtime-bindings",
            {
                "level": "project_default",
                "project_id": "{pid}",
                "target_kind": "agent_definition",
                "target_stable_key": "outsider-agent",
                "target": {"harness_ref": "x"},
            },
        ),
    ),
    ("GET", "/api/v1/runtime-bindings/{binding_id}"): (
        Probe("/api/v1/runtime-bindings/{binding}"),
    ),
    ("DELETE", "/api/v1/runtime-bindings/{binding_id}"): (
        Probe("/api/v1/runtime-bindings/{binding}"),
    ),
    ("POST", "/api/v1/resolutions"): (
        Probe("/api/v1/resolutions", {"stable_key": "some-agent", "project_id": "{pid}"}),
    ),
    ("GET", "/api/v1/ai-work"): (
        Probe("/api/v1/ai-work?project_id={pid}"),
        Probe("/api/v1/ai-work", expect="filtered"),
    ),
    ("POST", "/api/v1/ai-work"): (
        Probe(
            "/api/v1/ai-work",
            {"project_id": "{pid}", "agent_id": "{outsider_agent}", "summary": "x"},
        ),
    ),
    ("PATCH", "/api/v1/ai-work/{work_id}"): (Probe("/api/v1/ai-work/{work}", {"summary": "x"}),),
    ("GET", "/api/v1/review-queue"): (
        Probe("/api/v1/review-queue?project_id={pid}"),
        Probe("/api/v1/review-queue", expect="filtered"),
    ),
    ("GET", "/api/v1/timeline"): (Probe("/api/v1/timeline?project_id={pid}"),),
    ("POST", "/api/v1/projects/{project_id}/github-integration"): (
        Probe(
            "/api/v1/projects/{pid}/github-integration",
            {"project_id": "{pid}", "repo_full_name": "outsider/repo"},
        ),
    ),
    ("GET", "/api/v1/projects/{project_id}/github-integration"): (
        Probe("/api/v1/projects/{pid}/github-integration"),
    ),
    ("PATCH", "/api/v1/projects/{project_id}/github-integration"): (
        Probe("/api/v1/projects/{pid}/github-integration", {"enabled": False}),
    ),
    ("GET", "/api/v1/builds"): (
        Probe("/api/v1/builds?project_id={pid}"),
        Probe("/api/v1/builds", expect="filtered"),
    ),
    ("GET", "/api/v1/builds/{build_id}"): (Probe("/api/v1/builds/{build}"),),
    ("POST", "/api/v1/producer-jobs"): (
        Probe("/api/v1/producer-jobs", {"project_id": "{pid}", "kind": "priority_analysis"}),
    ),
    ("GET", "/api/v1/producer-jobs"): (
        Probe("/api/v1/producer-jobs?project_id={pid}"),
        Probe("/api/v1/producer-jobs", expect="filtered"),
    ),
    ("GET", "/api/v1/producer-jobs/{job_id}"): (Probe("/api/v1/producer-jobs/{job}"),),
    ("POST", "/api/v1/events"): (
        Probe(
            "/api/v1/events",
            {
                "event_id": "{new_uuid}",
                "event_type": "task.updated",
                "project_id": "{pid}",
                "actor_type": "user",
                "actor_id": "{outsider_user}",
                "client_timestamp": "{now}",
                "payload": {},
            },
        ),
    ),
    ("GET", "/api/v1/events"): (
        Probe("/api/v1/events?project={pid}"),
        Probe("/api/v1/events", expect="filtered"),
    ),
    ("GET", "/api/v1/events/stream"): (Probe("/api/v1/events/stream?project={pid}"),),
    ("GET", "/api/v1/transfers"): (
        Probe("/api/v1/transfers?project_id={pid}"),
        Probe("/api/v1/transfers", expect="filtered"),
    ),
    ("POST", "/api/v1/transfers"): (
        Probe(
            "/api/v1/transfers",
            {
                "project_id": "{pid}",
                "category": "asset",
                "filename": "x.bin",
                "content_type": "application/octet-stream",
                "size_bytes": 1,
            },
        ),
    ),
    ("GET", "/api/v1/transfers/consumption"): (
        Probe("/api/v1/transfers/consumption?project_id={pid}"),
    ),
    ("GET", "/api/v1/transfers/{transfer_id}"): (Probe(_TR),),
    ("DELETE", "/api/v1/transfers/{transfer_id}"): (Probe(_TR),),
    ("POST", "/api/v1/transfers/{transfer_id}/upload/initiate"): (
        Probe(_TR + "/upload/initiate", {}),
    ),
    ("POST", "/api/v1/transfers/{transfer_id}/upload/refresh-parts"): (
        Probe(_TR + "/upload/refresh-parts", {"upload_id": "x"}),
    ),
    ("POST", "/api/v1/transfers/{transfer_id}/upload/complete"): (
        Probe(_TR + "/upload/complete", {"size_bytes": 1, "sha256": "0" * 64}),
    ),
    ("POST", "/api/v1/transfers/{transfer_id}/download-url"): (Probe(_TR + "/download-url"),),
    ("GET", "/api/v1/projects/{project_id}/roadmaps"): (Probe("/api/v1/projects/{pid}/roadmaps"),),
    ("POST", "/api/v1/roadmaps"): (
        Probe("/api/v1/roadmaps", {"project_id": "{pid}", "title": "x"}),
    ),
    ("POST", "/api/v1/roadmaps/import"): (
        Probe("/api/v1/roadmaps/import", {"project_id": "{pid}", "document": {"title": "x"}}),
    ),
    ("GET", "/api/v1/roadmaps/{roadmap_id}"): (Probe(_RM),),
    ("PATCH", "/api/v1/roadmaps/{roadmap_id}"): (Probe(_RM, {"title": "x"}, headers=_V1),),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/transitions"): (
        Probe(_RM + "/transitions", {"transition": "submit", "expected_version": 1}),
    ),
    ("GET", "/api/v1/roadmaps/{roadmap_id}/export"): (Probe(_RM + "/export"),),
    ("GET", "/api/v1/roadmaps/{roadmap_id}/revisions"): (Probe(_RM + "/revisions"),),
    ("GET", "/api/v1/roadmaps/{roadmap_id}/revisions/{revision_no}"): (
        Probe(_RM + "/revisions/1"),
    ),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/proposals"): (
        Probe(_RM + "/proposals", {"base_revision_no": 1, "document": {"title": "x"}}),
    ),
    ("GET", "/api/v1/roadmaps/{roadmap_id}/proposals/{revision_no}/diff"): (
        Probe(_RM + "/proposals/1/diff"),
    ),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/proposals/{revision_no}/review"): (
        Probe(_RM + "/proposals/1/review", {"decision": "approve", "expected_version": 1}),
    ),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/phases"): (
        Probe(_RM + "/phases", {"key": "P9", "title": "x", "expected_roadmap_version": 1}),
    ),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/phases/reorder"): (
        Probe(_RM + "/phases/reorder", {"ordered_keys": ["P1"], "expected_roadmap_version": 1}),
    ),
    ("PATCH", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}"): (
        Probe(_RM + "/phases/P1", {"title": "x"}, headers=_V1),
    ),
    ("DELETE", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}"): (
        Probe(_RM + "/phases/P1", headers=_V1),
    ),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}/steps/reorder"): (
        Probe(
            _RM + "/phases/P1/steps/reorder",
            {"ordered_keys": ["S1"], "expected_roadmap_version": 1},
        ),
    ),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}/steps"): (
        Probe(
            _RM + "/phases/P1/steps",
            {"content": {"key": "S9", "title": "x"}, "expected_roadmap_version": 1},
        ),
    ),
    ("PATCH", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}"): (
        Probe(_RM + "/steps/S1", {"title": "x"}, headers=_V1),
    ),
    ("DELETE", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}"): (
        Probe(_RM + "/steps/S1", headers=_V1),
    ),
    ("PATCH", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}/progress"): (
        Probe(_RM + "/steps/S1/progress", {"notes": "x"}, headers=_V1),
    ),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/dependencies"): (
        Probe(
            _RM + "/dependencies",
            {"step_key": "S1", "depends_on_key": "S2", "expected_roadmap_version": 1},
        ),
    ),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/dependencies/remove"): (
        Probe(
            _RM + "/dependencies/remove",
            {"step_key": "S1", "depends_on_key": "S2", "expected_roadmap_version": 1},
        ),
    ),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}/links"): (
        Probe(_RM + "/steps/S1/links", {"task_id": "{task}"}),
    ),
    ("DELETE", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}/links/{task_id}"): (
        Probe(_RM + "/steps/S1/links/{task}"),
    ),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/hydration/preview"): (
        Probe(_RM + "/hydration/preview", {}),
    ),
    ("POST", "/api/v1/roadmaps/{roadmap_id}/hydration/apply"): (
        Probe(_RM + "/hydration/apply", {"expected_version": 1}),
    ),
}


def test_probes_cover_exactly_the_project_operations() -> None:
    project_ops = {op for op, access in HTTP_ACCESS.items() if access == "project"}
    assert not project_ops - PROBES.keys(), "project operations without an outsider probe"
    assert not PROBES.keys() - project_ops, "probes for non-project operations"


# --- 3. Outsider matrix -------------------------------------------------------


async def _post(
    client: AsyncClient, headers: dict[str, str], path: str, body: dict[str, Any]
) -> Any:
    response = await client.post(
        path, json=body, headers={**headers, "Idempotency-Key": str(uuid.uuid4())}
    )
    assert response.status_code in (200, 201), (path, response.text)
    return response.json()


async def _build_world(
    db_session: AsyncSession,
    client: AsyncClient,
    member: dict[str, str],
    admin: dict[str, str],
    outsider: dict[str, str],
    outsider_machine: MachineModel,
) -> dict[str, str]:
    """Every project-scoped object a probe can target, created by a member."""
    slug = f"world-{uuid.uuid4().hex[:8]}"
    pid = (await _post(client, member, "/api/v1/projects", {"slug": slug, "name": "W"}))["id"]
    await _post(  # the outsider is a member elsewhere, never of `pid`
        client, outsider, "/api/v1/projects", {"slug": f"else-{slug}", "name": "E"}
    )
    me = (await client.get("/api/v1/machines/me", headers=member)).json()
    task = (await _post(client, member, "/api/v1/tasks", {"project_id": pid, "title": "t"}))["id"]
    session = await _post(
        client, member, "/api/v1/sessions", {"task_id": task, "machine_id": me["id"]}
    )
    claim = await _post(
        client,
        member,
        "/api/v1/claims",
        {"project_id": pid, "resource_path": "a.py", "resource_type": "file", "ttl_seconds": 600},
    )
    decision = await _post(
        client,
        member,
        "/api/v1/decisions",
        {
            "project_id": pid,
            "title": "d",
            "body": "d",
            "proposed_by_type": "user",
            "proposed_by_id": me["owner_user_id"],
        },
    )
    lib = await _post(
        client,
        member,
        "/api/v1/library",
        {
            "kind": "rule",
            "stable_key": "world-rule",
            "scope": "project",
            "project_id": pid,
            "title": "r",
            "content": _RULE,
        },
    )
    lock = await _post(
        client,
        member,
        "/api/v1/library-locks",
        {"project_id": pid, "resource_id": lib["id"], "locked_version": 1},
    )
    binding = await _post(
        client,
        member,
        "/api/v1/runtime-bindings",
        {
            "level": "project_default",
            "project_id": pid,
            "target_kind": "agent_definition",
            "target_stable_key": "world-agent",
            "target": {"harness_ref": "h"},
        },
    )
    agent = await _post(client, member, "/api/v1/agents", {"display_name": "member-agent"})
    work = await _post(
        client,
        member,
        "/api/v1/ai-work",
        {"project_id": pid, "agent_id": agent["id"], "summary": "w"},
    )
    outsider_agent = await _post(client, outsider, "/api/v1/agents", {"display_name": "o"})
    await _post(
        client,
        admin,
        f"/api/v1/projects/{pid}/github-integration",
        {"project_id": pid, "repo_full_name": f"studio/{slug}"},
    )
    build = BuildModel(
        project_id=uuid.UUID(pid),
        workflow_run_id=1,
        workflow_name="ci",
        run_number=1,
        branch="main",
        commit_sha="0" * 40,
        html_url="https://example.test/run/1",
        actor_login="ci",
    )
    db_session.add(build)
    await db_session.flush()
    job = await _post(
        client, member, "/api/v1/producer-jobs", {"project_id": pid, "kind": "priority_analysis"}
    )
    transfer = await _post(
        client,
        member,
        "/api/v1/transfers",
        {
            "project_id": pid,
            "category": "asset",
            "filename": "a.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 1,
        },
    )
    roadmap = await _post(client, member, "/api/v1/roadmaps", {"project_id": pid, "title": "R"})
    rid = roadmap["id"]
    await _post(
        client,
        member,
        f"/api/v1/roadmaps/{rid}/phases",
        {"key": "P1", "title": "P", "expected_roadmap_version": roadmap["version"]},
    )
    current = (await client.get(f"/api/v1/roadmaps/{rid}", headers=member)).json()
    await _post(
        client,
        member,
        f"/api/v1/roadmaps/{rid}/phases/P1/steps",
        {"content": {"key": "S1", "title": "S"}, "expected_roadmap_version": current["version"]},
    )
    return {
        "pid": pid,
        "slug": slug,
        "task": task,
        "session": session["id"],
        "claim": claim["id"],
        "decision": decision["id"],
        "lib": lib["id"],
        "lock": lock["id"],
        "binding": binding["id"],
        "work": work["id"],
        "build": str(build.id),
        "job": job["id"],
        "transfer": transfer["id"],
        "roadmap": rid,
        "outsider_machine": str(outsider_machine.id),
        "outsider_user": str(outsider_machine.owner_user_id),
        "outsider_agent": outsider_agent["id"],
    }


_LEAK_KEYS: tuple[str, ...] = (
    "pid",
    "task",
    "session",
    "claim",
    "decision",
    "lib",
    "lock",
    "binding",
    "work",
)
_LEAK_KEYS += ("build", "job", "transfer", "roadmap")


def _render(value: Any, world: dict[str, str]) -> Any:
    if isinstance(value, dict):
        if value.get("$plan"):
            return _plan(world["slug"])  # re-initialize the member's project by slug
        return {k: _render(v, world) for k, v in value.items()}
    if isinstance(value, str):
        return value.format(**world, new_uuid=uuid.uuid4(), now=datetime.now(UTC).isoformat())
    return value


def _is_project_refusal(response: Any) -> bool:
    if response.status_code != 403:
        return False
    detail = response.json().get("detail")
    return (
        isinstance(detail, dict)
        and detail.get("error_code") == "forbidden"
        and detail.get("resource") == "project"
    )


async def test_outsider_matrix(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ~110 requests from one token: the per-token bucket is not under test here.
    monkeypatch.setattr(
        RateLimitMiddleware,
        "_dispatch_with_bucket",
        lambda _self, call_next, request, *_args, **_kwargs: call_next(request),
    )
    world = await _build_world(
        db_session, client, auth_headers, admin_auth_headers, other_auth_headers, other_machine[0]
    )
    failures: list[str] = []
    for (method, _template), probes in PROBES.items():
        for probe in probes:
            path = _render(probe.path, world)
            body = _render(probe.body, world) if probe.body is not None else None
            headers = {**other_auth_headers, **probe.headers}
            if method != "GET":
                headers["Idempotency-Key"] = str(uuid.uuid4())
            response = await client.request(method, path, json=body, headers=headers)
            leaks = any(world[key] in response.text for key in _LEAK_KEYS)
            if probe.expect == "forbidden":
                ok = _is_project_refusal(response)
            elif probe.expect == "filtered":
                ok = response.status_code == 200 and not leaks
            elif probe.expect == "role":
                ok = response.status_code == 403 and (
                    response.json()["detail"].get("error_code") == "forbidden"
                )
            else:  # slug
                if method == "POST" and path.endswith("/apply"):
                    detail = response.json().get("detail", {})
                    ok = (
                        not leaks
                        and response.status_code == 409
                        and isinstance(detail, dict)
                        and detail.get("error_code") == "conflict"
                    )
                else:
                    ok = (
                        not leaks
                        and response.status_code == 200
                        and all(
                            a["action"] == "create"
                            for a in response.json()["actions"]
                            if a["section"] == "project"
                        )
                    )
            if not ok:
                failures.append(f"{method} {path} -> {response.status_code} {response.text[:200]}")
    assert not failures, "outsider matrix:\n" + "\n".join(failures)
