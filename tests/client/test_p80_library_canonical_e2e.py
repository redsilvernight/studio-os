"""P80 — Library canonique de bout en bout, sur la vraie app et PostgreSQL.

Publication et activation d'un commun, mise à jour en attente puis appliquée
après confirmation, projection locale, override privé de A, alerte quand le
commun avance, fusion, retour au commun et restauration locale. B ne reçoit
jamais l'override de A et un hook commun reste soumis à consentement.

Seul le saut réseau du daemon est remplacé : les projections sont lues par le
vrai `StudioApiClient` sur l'app réelle, puis passent par le vrai chemin
daemon (aperçu, apply confirmé, auto-sync journalisé).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import provisioning as provisioning_service
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.daemon import skills_bridge
from studio_client.hook_sync import apply_hook_sync, fetch_hook_projections, plan_hook_sync
from studio_client.projection_backups import restore_projection_backup
from studio_client.tokens import MemoryTokenStore
from studio_contracts.library import HookOs
from studio_contracts.local.skills import (
    SkillLibraryKind,
    SkillResolution,
    SkillsApplyRequest,
    SkillSyncStatusState,
)

ORIGIN = "http://test"
KEY = "p80-shared-rule"
RULE = "studio.library.rule/v1"


@dataclass
class _Machine:
    name: str
    token: str
    home: Path
    data_root: Path

    @property
    def store(self) -> MemoryTokenStore:
        store = MemoryTokenStore()
        store.set_token(ORIGIN, self.token)
        return store

    @property
    def rule_file(self) -> Path:
        return self.home / ".claude" / "rules" / f"{KEY}.md"

    def rule_text(self) -> str | None:
        return self.rule_file.read_text(encoding="utf-8") if self.rule_file.is_file() else None


async def _machine(db_session: AsyncSession, tmp_path: Path, name: str, role: str) -> _Machine:
    user = await provisioning_service.create_user(
        db_session, name, f"{uuid.uuid4()}@example.test", role
    )
    _, token = await provisioning_service.create_machine(db_session, user.id, f"{name}-machine")
    home = tmp_path / name / "home"
    home.mkdir(parents=True)
    return _Machine(name, token, home, tmp_path / name / "data")


def _http(transport: ASGITransport, machine: _Machine) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=transport,
        base_url=ORIGIN,
        headers={"Authorization": f"Bearer {machine.token}"},
    )


async def _call(
    transport: ASGITransport, machine: _Machine, method: str, path: str, **kwargs: Any
) -> httpx.Response:
    async with _http(transport, machine) as http:
        return await http.request(method, f"/api/v1/library{path}", **kwargs)


async def _publish(
    transport: ASGITransport,
    machine: _Machine,
    text: str,
    *,
    resource_id: str | None = None,
    scope: str = "studio",
    derived_from: dict[str, object] | None = None,
) -> dict[str, Any]:
    content = {"content_schema": RULE, "text": text}
    if resource_id is None:
        body: dict[str, object] = {
            "kind": "rule",
            "stable_key": KEY,
            "scope": scope,
            "title": "Règle partagée",
            "content": content,
        }
        if derived_from is not None:
            body["derived_from"] = derived_from
        created = await _call(transport, machine, "POST", "", json=body)
        assert created.status_code == 201, created.text
        resource = created.json()
        version = 1
    else:
        added = await _call(
            transport,
            machine,
            "POST",
            f"/{resource_id}/versions",
            json={"title": "Règle partagée", "content": content},
        )
        assert added.status_code == 201, added.text
        version = added.json()["version"]
        resource = (await _call(transport, machine, "GET", f"/{resource_id}")).json()
    activated = await _call(
        transport,
        machine,
        "POST",
        f"/{resource['id']}/activate",
        json={"version": version, "expected_resource_version": resource["version"]},
    )
    assert activated.status_code == 200, activated.text
    return activated.json()


async def _projections(
    transport: ASGITransport, config: ClientConfig, machine: _Machine
) -> tuple[Any, ...]:
    async with StudioApiClient(config, machine.store, transport=transport) as api:
        return await skills_bridge.fetch_library_projections(api, None, limit=500)


async def _auto_sync(
    transport: ASGITransport,
    config: ClientConfig,
    machine: _Machine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projections = await _projections(transport, config, machine)
    monkeypatch.setattr(skills_bridge, "_fetch_projections", lambda *_a, **_k: projections)
    skills_bridge._AutoSyncRunner(config, machine.store, machine.home, machine.data_root)._run()


async def test_library_canonical_end_to_end(
    db_session: AsyncSession,
    app_transport: ASGITransport,
    client_config: ClientConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = await _machine(db_session, tmp_path, "admin", "admin")
    alice = await _machine(db_session, tmp_path, "alice", "developer")
    bob = await _machine(db_session, tmp_path, "bob", "developer")
    seen_by_bob: list[str | None] = []

    # Publication et activation du commun.
    common = await _publish(app_transport, admin, "Commun v1\n")

    # Confirmation : la mise à jour est signalée, rien n'est écrit avant l'accord.
    for machine in (alice, bob):
        projections = await _projections(app_transport, client_config, machine)
        monkeypatch.setattr(skills_bridge, "_fetch_projections", lambda *_a, p=projections, **_k: p)
        assert skills_bridge.mark_update_pending(
            client_config, machine.store, machine.home, machine.data_root
        )
        status = skills_bridge._load_status(machine.data_root)
        assert status is not None and status.state is SkillSyncStatusState.UPDATE_PENDING
        assert machine.rule_text() is None
        with pytest.raises(skills_bridge.LocalFeatureError):
            skills_bridge.apply_skills(
                client_config, machine.store, SkillsApplyRequest(), home=machine.home
            )
        assert machine.rule_text() is None
        preview = skills_bridge.preview_skills(
            client_config, machine.store, home=machine.home, selection={"rule": [KEY]}
        )
        entry = next(item for item in preview.skills if item.stable_key == KEY)
        skills_bridge.apply_skills(
            client_config,
            machine.store,
            SkillsApplyRequest(
                confirm=True,
                resolutions=[
                    SkillResolution(
                        kind=SkillLibraryKind.RULE,
                        stable_key=KEY,
                        choice="library",
                        preview_hash=entry.preview_hash,
                    )
                ],
            ),
            home=machine.home,
            data_root=machine.data_root,
        )
        # Projection locale du commun.
        assert "Commun v1" in (machine.rule_text() or "")
    seen_by_bob.append(bob.rule_text())

    # Un hook commun reste soumis à consentement.
    hook = await _call(
        app_transport,
        admin,
        "POST",
        "",
        json={
            "kind": "hook",
            "stable_key": "p80-guard",
            "scope": "studio",
            "title": "Garde P80",
            "content": {
                "content_schema": "studio.library.hook/v1",
                "event": "pre_tool",
                "matcher": "Bash",
                "mode": "blocking",
                "timeout_seconds": 15,
                "scripts": [{"os": "any", "shell": "bash", "body": "echo guard\n"}],
            },
        },
    )
    assert hook.status_code == 201, hook.text
    hook_activated = await _call(
        app_transport,
        admin,
        "POST",
        f"/{hook.json()['id']}/activate",
        json={"version": 1, "expected_resource_version": hook.json()["version"]},
    )
    assert hook_activated.status_code == 200, hook_activated.text
    async with StudioApiClient(client_config, alice.store, transport=app_transport) as api:
        hooks = await fetch_hook_projections(api, None)
    plan = plan_hook_sync(alice.home, hooks, os_name=HookOs.LINUX)
    assert [entry.status for entry in plan.entries] == ["needs_consent"]
    apply_hook_sync(plan)
    assert not (alice.home / ".claude" / "studio-hooks" / "p80-guard.sh").exists()

    # Override privé de A, projeté chez A seulement.
    override = await _publish(
        app_transport,
        alice,
        "Override d'Alice\n",
        scope="user",
        derived_from={"resource_id": common["id"], "version": 1},
    )
    for machine in (alice, bob):
        await _auto_sync(app_transport, client_config, machine, monkeypatch)
    assert "Override d'Alice" in (alice.rule_text() or "")
    seen_by_bob.append(bob.rule_text())
    assert (await _call(app_transport, bob, "GET", f"/{override['id']}")).status_code == 404
    listed = (await _call(app_transport, bob, "GET", "", params={"kind": "rule"})).json()
    assert all(item["id"] != override["id"] for item in listed)

    # Le commun avance : A est alerté, B reçoit le nouveau commun.
    common = await _publish(app_transport, admin, "Commun v2\n", resource_id=common["id"])
    detail = (await _call(app_transport, alice, "GET", f"/{override['id']}")).json()
    assert detail["base_update_available"] is True
    preview = (await _call(app_transport, alice, "GET", f"/{override['id']}/merge-preview")).json()
    assert len(preview["result"]["conflicts"]) == 1
    await _auto_sync(app_transport, client_config, bob, monkeypatch)
    seen_by_bob.append(bob.rule_text())
    assert "Commun v2" in (bob.rule_text() or "")

    # Fusion résolue par A, projetée chez A.
    merged = await _call(
        app_transport,
        alice,
        "POST",
        f"/{override['id']}/merge-apply",
        json={
            "choice": "merge",
            "content": "Override d'Alice\nCommun v2\n",
            "expected_resource_version": detail["version"],
            "base_active_version": detail["base_active_version"],
        },
    )
    assert merged.status_code == 200, merged.text
    await _auto_sync(app_transport, client_config, alice, monkeypatch)
    merged_projection = alice.rule_text()
    assert merged_projection is not None and "Commun v2" in merged_projection
    assert "Override d'Alice" in merged_projection

    # Retour au commun quand il avance de nouveau, puis restauration locale.
    await _publish(app_transport, admin, "Commun v3\n", resource_id=common["id"])
    detail = (await _call(app_transport, alice, "GET", f"/{override['id']}")).json()
    reverted = await _call(
        app_transport,
        alice,
        "POST",
        f"/{override['id']}/merge-apply",
        json={
            "choice": "revert_to_common",
            "expected_resource_version": detail["version"],
            "base_active_version": detail["base_active_version"],
        },
    )
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["status"] == "deprecated"
    await _auto_sync(app_transport, client_config, alice, monkeypatch)
    assert "Commun v3" in (alice.rule_text() or "")
    restore_projection_backup(alice.home)
    assert alice.rule_text() == merged_projection

    await _auto_sync(app_transport, client_config, bob, monkeypatch)
    seen_by_bob.append(bob.rule_text())
    assert "Commun v3" in (bob.rule_text() or "")
    assert all(text is not None and "Alice" not in text for text in seen_by_bob)
