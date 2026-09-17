from __future__ import annotations

from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import library as library_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.library import LibraryKind, LibraryScope, VersionOrigin

WORKFLOW_SCHEMA = "studio.library.workflow/v1"


async def _principal(db_session: AsyncSession, machine: tuple[MachineModel, str]) -> Principal:
    model, _ = machine
    return await load_principal(db_session, model)


async def _create(
    client: AsyncClient, headers: dict[str, str], payload: dict[str, object]
) -> dict[str, object]:
    response = await client.post("/api/v1/library", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def _seed_definitions(client: AsyncClient, headers: dict[str, str]) -> None:
    await _create(
        client,
        headers,
        {
            "kind": "rule",
            "stable_key": "wf-coding-standard",
            "scope": "studio",
            "title": "Coding standard",
            "content": {
                "content_schema": "studio.library.rule/v1",
                "text": "Follow the standard.",
            },
        },
    )
    await _create(
        client,
        headers,
        {
            "kind": "skill",
            "stable_key": "wf-godot-development",
            "scope": "studio",
            "title": "Godot development",
            "content": {
                "content_schema": "studio.library.skill/v1",
                "text": "Build with Godot.",
            },
        },
    )
    for key in ("wf-writer", "wf-tester", "wf-reviewer"):
        await _create(
            client,
            headers,
            {
                "kind": "agent_definition",
                "stable_key": key,
                "scope": "studio",
                "title": key,
                "content": {"content_schema": "studio.library.agent_definition/v1"},
            },
        )


def _dependencies(with_reviewer: bool = True) -> list[dict[str, object]]:
    dependencies: list[dict[str, object]] = [
        {"kind": "rule", "stable_key": "wf-coding-standard", "version": 1},
        {"kind": "skill", "stable_key": "wf-godot-development", "version": 1},
        {"kind": "agent_definition", "stable_key": "wf-writer", "version": 1},
        {"kind": "agent_definition", "stable_key": "wf-tester", "version": 1},
    ]
    if with_reviewer:
        dependencies.append({"kind": "agent_definition", "stable_key": "wf-reviewer", "version": 1})
    return dependencies


def _participants(with_reviewer: bool = True) -> list[dict[str, object]]:
    participants: list[dict[str, object]] = [
        {
            "participant_id": "implementer",
            "description": "Implements the change.",
            "agent_stable_key": "wf-writer",
            "inputs": [{"name": "task", "source": {"name": "task"}}],
            "outputs": [{"name": "patch"}],
        },
        {
            "participant_id": "tester",
            "agent_stable_key": "wf-tester",
            "depends_on": ["implementer"],
            "inputs": [
                {"name": "patch", "source": {"participant_id": "implementer", "name": "patch"}}
            ],
            "outputs": [{"name": "test_report"}],
        },
    ]
    if with_reviewer:
        participants.append(
            {
                "participant_id": "reviewer",
                "agent_stable_key": "wf-reviewer",
                "depends_on": ["tester"],
                "inputs": [
                    {
                        "name": "patch",
                        "source": {"participant_id": "implementer", "name": "patch"},
                    },
                    {
                        "name": "test_report",
                        "source": {"participant_id": "tester", "name": "test_report"},
                    },
                ],
                "outputs": [{"name": "review_report"}],
            }
        )
    return participants


def _outputs(with_reviewer: bool = True) -> list[dict[str, object]]:
    outputs: list[dict[str, object]] = [
        {"name": "patch", "source": {"participant_id": "implementer", "name": "patch"}},
        {"name": "test_report", "source": {"participant_id": "tester", "name": "test_report"}},
    ]
    if with_reviewer:
        outputs.append(
            {
                "name": "review_report",
                "source": {"participant_id": "reviewer", "name": "review_report"},
            }
        )
    return outputs


def _workflow_content(
    *,
    with_reviewer: bool = True,
    participants: list[dict[str, object]] | None = None,
    outputs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "content_schema": WORKFLOW_SCHEMA,
        "summary": "Implement, test and review a code change.",
        "participants": _participants(with_reviewer) if participants is None else participants,
        "inputs": [{"name": "task"}, {"name": "repository_context"}],
        "outputs": _outputs(with_reviewer) if outputs is None else outputs,
    }


def _workflow_payload(
    stable_key: str,
    *,
    with_reviewer: bool = True,
    content: dict[str, object] | None = None,
    dependencies: list[dict[str, object]] | None = None,
    scope: str = "studio",
    project_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "workflow",
        "stable_key": stable_key,
        "scope": scope,
        "title": "Code change",
        "content": content
        if content is not None
        else _workflow_content(with_reviewer=with_reviewer),
        "dependencies": dependencies if dependencies is not None else _dependencies(with_reviewer),
    }
    if project_id is not None:
        payload["project_id"] = project_id
    return payload


async def _versions(
    client: AsyncClient, headers: dict[str, str], resource_id: object
) -> list[dict[str, object]]:
    response = await client.get(f"/api/v1/library/{resource_id}/versions", headers=headers)
    assert response.status_code == 200, response.text
    body: list[dict[str, object]] = response.json()
    return body


# --- Create + shape --------------------------------------------------------------


async def test_create_workflow_with_participants_dag_and_pinned_links(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    created = await _create(client, auth_headers, _workflow_payload("code-change"))
    assert created["kind"] == "workflow"

    versions = await _versions(client, auth_headers, created["id"])
    assert len(versions) == 1
    version = versions[0]
    content = version["content"]
    assert content["content_schema"] == WORKFLOW_SCHEMA
    assert [p["participant_id"] for p in content["participants"]] == [
        "implementer",
        "tester",
        "reviewer",
    ]
    assert content["participants"][1]["depends_on"] == ["implementer"]
    relations = {dep["stable_key"]: dep["relation"] for dep in version["dependencies"]}
    assert relations["wf-coding-standard"] == "applies_rule"
    assert relations["wf-godot-development"] == "uses_skill"
    assert relations["wf-writer"] == relations["wf-tester"] == "composes_agent"
    assert all(dep["version"] == 1 for dep in version["dependencies"])


async def test_workflow_rejects_duplicate_participant(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    payload = _workflow_payload(
        "dup-participant",
        content=_workflow_content(
            participants=[
                {"participant_id": "tester", "agent_stable_key": "wf-writer"},
                {"participant_id": "tester", "agent_stable_key": "wf-tester"},
            ]
        ),
    )
    response = await client.post("/api/v1/library", headers=auth_headers, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_workflow"
    assert response.json()["detail"]["reason"] == "duplicate_participant"


async def test_workflow_rejects_unknown_dependency(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    participants = _participants()
    participants[1]["depends_on"] = ["ghost"]
    payload = _workflow_payload("unknown-dep", content=_workflow_content(participants=participants))
    response = await client.post("/api/v1/library", headers=auth_headers, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unknown_dependency"


async def test_workflow_rejects_dependency_cycle_without_partial_write(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    created = await _create(client, auth_headers, _workflow_payload("cycle-guard"))

    cyclic = [
        {"participant_id": "a", "agent_stable_key": "wf-writer", "depends_on": ["c"]},
        {"participant_id": "b", "agent_stable_key": "wf-tester", "depends_on": ["a"]},
        {"participant_id": "c", "agent_stable_key": "wf-reviewer", "depends_on": ["b"]},
    ]
    response = await client.post(
        f"/api/v1/library/{created['id']}/versions",
        headers=auth_headers,
        json={
            "title": "Cyclic v2",
            "content": _workflow_content(participants=cyclic, outputs=[]),
            "dependencies": _dependencies(with_reviewer=True),
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "dependency_cycle"
    assert len(await _versions(client, auth_headers, created["id"])) == 1


async def test_workflow_rejects_unknown_participant_agent(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    participants = _participants()
    participants[0]["agent_stable_key"] = "ghost"
    payload = _workflow_payload(
        "unknown-agent", content=_workflow_content(participants=participants)
    )
    response = await client.post("/api/v1/library", headers=auth_headers, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unknown_participant_agent"


async def test_workflow_rejects_unused_agent_dependency(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    payload = _workflow_payload(
        "unused-agent",
        with_reviewer=False,
        content=_workflow_content(
            participants=[
                {"participant_id": "implementer", "agent_stable_key": "wf-writer"},
            ],
            outputs=[],
        ),
    )
    response = await client.post("/api/v1/library", headers=auth_headers, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unused_agent_dependency"


async def test_workflow_rejects_invalid_io_reference(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    outputs = _outputs()
    outputs[0]["source"] = {"participant_id": "implementer", "name": "ghost"}
    payload = _workflow_payload("invalid-io", content=_workflow_content(outputs=outputs))
    response = await client.post("/api/v1/library", headers=auth_headers, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "invalid_io_reference"


async def test_workflow_rejects_runtime_fields_in_content(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    content = _workflow_content()
    content["machine_id"] = "machine-a"
    payload = _workflow_payload("runtime-fields", content=content)
    response = await client.post("/api/v1/library", headers=auth_headers, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_content"


async def test_workflow_is_discoverable_by_kind(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    await _create(client, auth_headers, _workflow_payload("discoverable"))
    listing = await client.get("/api/v1/library", headers=auth_headers, params={"kind": "workflow"})
    assert listing.status_code == 200
    assert [item["stable_key"] for item in listing.json()] == ["discoverable"]


# --- Sharing and isolation (P11 §54) --------------------------------------------


async def test_workflow_is_shared_identically_between_authorized_callers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    await _seed_definitions(client, auth_headers)
    created = await _create(client, auth_headers, _workflow_payload("shared-change"))

    mine = (await _versions(client, auth_headers, created["id"]))[0]
    theirs = (await _versions(client, other_auth_headers, created["id"]))[0]
    assert mine == theirs
    serialized = str(mine["content"]) + str(mine["dependencies"])
    for leaked in ("machine_id", "runtime_id", "provider_ref", "model_ref", "started_at"):
        assert leaked not in serialized


async def test_user_scoped_workflow_stays_private(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    await _seed_definitions(client, auth_headers)
    created = await _create(client, auth_headers, _workflow_payload("private-change", scope="user"))
    mine = await client.get(f"/api/v1/library/{created['id']}", headers=auth_headers)
    assert mine.status_code == 200
    theirs = await client.get(f"/api/v1/library/{created['id']}", headers=other_auth_headers)
    assert theirs.status_code == 404


async def test_workflow_shadowing_reuses_library_scope_resolution(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    await _seed_definitions(client, auth_headers)
    principal = await _principal(db_session, machine)
    created: dict[str, dict[str, object]] = {}
    for scope, project_id in (
        ("studio", None),
        ("project", str(project.id)),
        ("user", None),
    ):
        resource = await _create(
            client,
            auth_headers,
            _workflow_payload("layered-change", scope=scope, project_id=project_id),
        )
        created[scope] = resource
        activated = await client.post(
            f"/api/v1/library/{resource['id']}/activate",
            headers=auth_headers,
            json={"version": 1, "expected_resource_version": resource["version"]},
        )
        assert activated.status_code == 200, activated.text

    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.WORKFLOW, "layered-change", project.id
    )
    assert resolved.resource_id == UUID(str(created["user"]["id"]))
    assert resolved.scope == LibraryScope.USER
    assert resolved.version_origin == VersionOrigin.ACTIVE


# --- Versioning and pinning (P11 §55, §57) --------------------------------------


async def test_workflow_versioning_keeps_links_bound_to_each_version(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    created = await _create(
        client, auth_headers, _workflow_payload("evolving", with_reviewer=False)
    )

    v2 = await client.post(
        f"/api/v1/library/{created['id']}/versions",
        headers=auth_headers,
        json={
            "title": "Code change v2",
            "content": _workflow_content(with_reviewer=True),
            "dependencies": _dependencies(with_reviewer=True),
        },
    )
    assert v2.status_code == 201, v2.text
    assert v2.json()["version"] == 2

    versions = await _versions(client, auth_headers, created["id"])
    assert len(versions) == 2
    v1_content = versions[0]["content"]
    assert [p["participant_id"] for p in v1_content["participants"]] == ["implementer", "tester"]
    assert len(versions[0]["dependencies"]) == 4
    assert [p["participant_id"] for p in versions[1]["content"]["participants"]] == [
        "implementer",
        "tester",
        "reviewer",
    ]
    assert len(versions[1]["dependencies"]) == 5


async def test_workflow_pin_does_not_drift_when_skill_evolves(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    skills = await client.get("/api/v1/library", headers=auth_headers, params={"kind": "skill"})
    skill_id = skills.json()[0]["id"]
    created = await _create(client, auth_headers, _workflow_payload("pinned-skill"))

    new_version = await client.post(
        f"/api/v1/library/{skill_id}/versions",
        headers=auth_headers,
        json={
            "title": "Godot v2",
            "content": {"content_schema": "studio.library.skill/v1", "text": "Build again."},
        },
    )
    assert new_version.status_code == 201
    refreshed = await client.get(f"/api/v1/library/{skill_id}", headers=auth_headers)
    activated = await client.post(
        f"/api/v1/library/{skill_id}/activate",
        headers=auth_headers,
        json={"version": 2, "expected_resource_version": refreshed.json()["version"]},
    )
    assert activated.status_code == 200, activated.text

    versions = await _versions(client, auth_headers, created["id"])
    skill_pin = next(
        dep for dep in versions[0]["dependencies"] if dep["stable_key"] == "wf-godot-development"
    )
    assert skill_pin["version"] == 1


async def test_workflow_is_harness_neutral_through_http(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _seed_definitions(client, auth_headers)
    created = await _create(client, auth_headers, _workflow_payload("neutral-change"))
    versions = await _versions(client, auth_headers, created["id"])
    serialized = (str(versions[0]["content"]) + str(versions[0]["dependencies"])).lower()
    for token in ("claude", "opencode", "anthropic", "openai", "ollama"):
        assert token not in serialized
