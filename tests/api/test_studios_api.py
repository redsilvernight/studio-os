"""Studios, invitations and membership management (0050): studio creation,
single-use expiring invitations, role gates, ownership transfer and the
sign-up → studio → project journey. Needs the real PostgreSQL test database
(infra tests are skipped, with the reason, when it is absent)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.studio import StudioInvitationModel, StudioMembershipModel
from studio_api.db.models.user import UserModel
from studio_api.mailer import OutgoingEmail, get_email_sender
from studio_api.main import app
from studio_api.services import provisioning as provisioning_service
from studio_api.settings import Settings, get_settings

from tests.api.test_public_registration import PASSWORD

pytestmark = pytest.mark.isolation

_TOKEN_RE = re.compile(r"#token=([A-Za-z0-9_-]+)")


class Outbox:
    enabled = True

    def __init__(self) -> None:
        self.messages: list[OutgoingEmail] = []

    async def send(self, message: OutgoingEmail) -> None:
        self.messages.append(message)

    def to(self, email: str) -> list[OutgoingEmail]:
        return [message for message in self.messages if message.to == email]

    def last_secret(self, email: str) -> str:
        match = _TOKEN_RE.search(self.to(email)[-1].body)
        assert match is not None
        return match.group(1)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "public_registration_enabled": True,
        "email_backend": "file",
        "email_from": "studio@example.test",
        "account_email_cooldown_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def outbox() -> Iterator[Outbox]:
    box = Outbox()
    app.dependency_overrides[get_email_sender] = lambda: box
    yield box
    app.dependency_overrides.pop(get_email_sender, None)


@pytest.fixture
def open_instance(outbox: Outbox) -> Iterator[Settings]:
    settings = _settings()
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


def _email() -> str:
    return f"{uuid.uuid4()}@example.test"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _user_machine(
    db_session: AsyncSession, *, role: str = "developer"
) -> tuple[UserModel, dict[str, str]]:
    user = await provisioning_service.create_user(
        db_session, f"Member {uuid.uuid4().hex[:6]}", _email(), role
    )
    _, token = await provisioning_service.create_machine(
        db_session, user.id, f"machine-{uuid.uuid4().hex[:6]}"
    )
    return user, _bearer(token)


async def _studio(client: AsyncClient, headers: dict[str, str], name: str) -> dict[str, object]:
    response = await client.post("/api/v1/studios", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def _invite(
    client: AsyncClient,
    headers: dict[str, str],
    studio_id: str,
    email: str,
    role: str = "member",
) -> object:
    return await client.post(
        f"/api/v1/studios/{studio_id}/invitations",
        json={"email": email, "role": role},
        headers=headers,
    )


async def _role_in(client: AsyncClient, headers: dict[str, str], studio_id: str) -> str | None:
    studios = (await client.get("/api/v1/studios", headers=headers)).json()
    for studio in studios:
        if studio["id"] == studio_id:
            return str(studio["role"])
    return None


# --- Studio creation and detail ---------------------------------------------


@pytest.mark.usefixtures("outbox")
async def test_create_studio_owner_unique_slug_and_detail(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, headers = await _user_machine(db_session)
    name = f"Atelier {uuid.uuid4().hex[:8]}"
    first = await _studio(client, headers, name)
    second = await _studio(client, headers, name)

    assert first["role"] == "owner"
    assert second["role"] == "owner"
    assert first["slug"] != second["slug"]
    assert first["name"] == name

    listed = (await client.get("/api/v1/studios", headers=headers)).json()
    ids = {studio["id"] for studio in listed}
    assert {first["id"], second["id"]} <= ids

    detail = await client.get(f"/api/v1/studios/{first['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json() == {
        **first,
        "deletion_scheduled_at": None,
    }


@pytest.mark.usefixtures("outbox")
async def test_create_studio_is_idempotent(client: AsyncClient, db_session: AsyncSession) -> None:
    _, headers = await _user_machine(db_session)
    key = str(uuid.uuid4())
    body = {"name": f"Replay {uuid.uuid4().hex[:8]}"}
    payload = {**body, "Idempotency-Key": key}
    first = await client.post("/api/v1/studios", json=body, headers={**headers, **payload})
    second = await client.post("/api/v1/studios", json=body, headers={**headers, **payload})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.usefixtures("outbox")
async def test_studio_detail_of_a_foreign_studio_is_forbidden(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, owner = await _user_machine(db_session)
    _, outsider = await _user_machine(db_session)
    studio = await _studio(client, owner, "Private studio")
    response = await client.get(f"/api/v1/studios/{studio['id']}", headers=outsider)
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "forbidden"


# --- Invitations -------------------------------------------------------------


@pytest.mark.usefixtures("open_instance")
async def test_invitation_is_single_use_and_lists_members(
    client: AsyncClient, db_session: AsyncSession, outbox: Outbox
) -> None:
    _, owner = await _user_machine(db_session)
    invitee, invitee_headers = await _user_machine(db_session)
    studio = await _studio(client, owner, f"Invitations {uuid.uuid4().hex[:6]}")

    created = await _invite(client, owner, str(studio["id"]), invitee.email, "member")
    assert created.status_code == 201, created.text
    invitation = created.json()
    assert invitation["email"] == invitee.email
    assert invitation["role"] == "member"
    assert invitation["consumed_at"] is None

    listed = await client.get(f"/api/v1/studios/{studio['id']}/invitations", headers=owner)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [invitation["id"]]

    secret = outbox.last_secret(invitee.email)
    preview = await client.post("/api/v1/invitations/preview", json={"token": secret})
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["state"] == "valid"
    assert preview_body["studio_name"] == studio["name"]
    assert preview_body["role"] == "member"
    assert preview_body["inviter_display_name"] is not None

    accepted = await client.post(
        "/api/v1/invitations/accept", json={"token": secret}, headers=invitee_headers
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"studio_id": studio["id"], "role": "member"}
    assert await _role_in(client, invitee_headers, str(studio["id"])) == "member"

    replay = await client.post(
        "/api/v1/invitations/accept", json={"token": secret}, headers=invitee_headers
    )
    assert replay.status_code == 410
    assert replay.json()["detail"]["error_code"] == "invitation_used"

    used = await client.post("/api/v1/invitations/preview", json={"token": secret})
    assert used.json()["state"] == "used"

    members = await client.get(f"/api/v1/studios/{studio['id']}/members", headers=invitee_headers)
    assert members.status_code == 200
    roles = {row["user_id"]: row["role"] for row in members.json()}
    assert set(roles.values()) == {"owner", "member"}


@pytest.mark.usefixtures("open_instance")
async def test_only_owner_or_admin_invites(
    client: AsyncClient, db_session: AsyncSession, outbox: Outbox
) -> None:
    _, owner = await _user_machine(db_session)
    member, member_headers = await _user_machine(db_session)
    studio = await _studio(client, owner, "Role gates")
    assert (
        await _invite(client, owner, str(studio["id"]), member.email, "member")
    ).status_code == 201
    secret = outbox.last_secret(member.email)
    accepted = await client.post(
        "/api/v1/invitations/accept", json={"token": secret}, headers=member_headers
    )
    assert accepted.status_code == 200

    forbidden = await _invite(client, member_headers, str(studio["id"]), _email(), "member")
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["error_code"] == "forbidden"

    # An admin may invite; ownership alone may transfer.
    promoted = await client.patch(
        f"/api/v1/studios/{studio['id']}/members/{member.id}",
        json={"role": "admin"},
        headers=owner,
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "admin"
    assert (
        await _invite(client, member_headers, str(studio["id"]), _email(), "viewer")
    ).status_code == 201

    transfer = await client.post(
        f"/api/v1/studios/{studio['id']}/transfer-ownership",
        json={"user_id": str(member.id)},
        headers=member_headers,
    )
    assert transfer.status_code == 403
    assert transfer.json()["detail"]["error_code"] == "owner_required"


@pytest.mark.usefixtures("open_instance")
async def test_expired_invitation_preview_and_accept(
    client: AsyncClient, db_session: AsyncSession, outbox: Outbox
) -> None:
    _, owner = await _user_machine(db_session)
    invitee, invitee_headers = await _user_machine(db_session)
    studio = await _studio(client, owner, "Expiring")
    created = await _invite(client, owner, str(studio["id"]), invitee.email, "viewer")
    assert created.status_code == 201
    secret = outbox.last_secret(invitee.email)
    await db_session.execute(
        update(StudioInvitationModel)
        .where(StudioInvitationModel.id == created.json()["id"])
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db_session.commit()

    preview = await client.post("/api/v1/invitations/preview", json={"token": secret})
    assert preview.json()["state"] == "expired"

    accepted = await client.post(
        "/api/v1/invitations/accept", json={"token": secret}, headers=invitee_headers
    )
    assert accepted.status_code == 410
    assert accepted.json()["detail"]["error_code"] == "invitation_expired"


@pytest.mark.usefixtures("open_instance")
async def test_invitation_accept_requires_the_invited_address(
    client: AsyncClient, db_session: AsyncSession, outbox: Outbox
) -> None:
    _, owner = await _user_machine(db_session)
    invitee, invitee_headers = await _user_machine(db_session)
    _, other_headers = await _user_machine(db_session)
    studio = await _studio(client, owner, "Address bound")
    assert (
        await _invite(client, owner, str(studio["id"]), invitee.email, "member")
    ).status_code == 201
    secret = outbox.last_secret(invitee.email)

    mismatch = await client.post(
        "/api/v1/invitations/accept", json={"token": secret}, headers=other_headers
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["detail"]["error_code"] == "invitation_email_mismatch"
    # Not consumed: the right account can still use it.
    preview = await client.post("/api/v1/invitations/preview", json={"token": secret})
    assert preview.json()["state"] == "valid"
    accepted = await client.post(
        "/api/v1/invitations/accept", json={"token": secret}, headers=invitee_headers
    )
    assert accepted.status_code == 200


@pytest.mark.usefixtures("open_instance")
async def test_preview_is_public_and_unknown_is_empty(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/invitations/preview", json={"token": "unknown-secret-value"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "state": "unknown",
        "studio_name": None,
        "role": None,
        "inviter_display_name": None,
    }


@pytest.mark.usefixtures("open_instance")
async def test_delete_invitation_revokes_the_link(
    client: AsyncClient, db_session: AsyncSession, outbox: Outbox
) -> None:
    _, owner = await _user_machine(db_session)
    invitee, invitee_headers = await _user_machine(db_session)
    studio = await _studio(client, owner, "Revoked")
    created = await _invite(client, owner, str(studio["id"]), invitee.email, "member")
    secret = outbox.last_secret(invitee.email)

    deleted = await client.delete(
        f"/api/v1/studios/{studio['id']}/invitations/{created.json()['id']}",
        headers=owner,
    )
    assert deleted.status_code == 204

    preview = await client.post("/api/v1/invitations/preview", json={"token": secret})
    assert preview.json()["state"] == "unknown"
    accepted = await client.post(
        "/api/v1/invitations/accept", json={"token": secret}, headers=invitee_headers
    )
    assert accepted.status_code == 410
    assert accepted.json()["detail"]["error_code"] == "invitation_unknown"
    missing = await client.delete(
        f"/api/v1/studios/{studio['id']}/invitations/{uuid.uuid4()}", headers=owner
    )
    assert missing.status_code == 404


@pytest.mark.usefixtures("open_instance")
async def test_inviting_an_unknown_address_answers_like_a_known_one(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, owner = await _user_machine(db_session)
    known, _ = await _user_machine(db_session)
    studio = await _studio(client, owner, "No enumeration")
    for email in (known.email, _email()):
        response = await _invite(client, owner, str(studio["id"]), email, "member")
        assert response.status_code == 201
        body = response.json()
        assert set(body) == {
            "id",
            "email",
            "role",
            "expires_at",
            "consumed_at",
            "invited_by_user_id",
            "created_at",
        }


# --- Membership and ownership invariants ------------------------------------


@pytest.mark.usefixtures("open_instance")
async def test_transfer_ownership_always_leaves_one_owner(
    client: AsyncClient, db_session: AsyncSession, outbox: Outbox
) -> None:
    owner_user, owner = await _user_machine(db_session)
    successor, successor_headers = await _user_machine(db_session)
    studio = await _studio(client, owner, "Ownership")
    assert (
        await _invite(client, owner, str(studio["id"]), successor.email, "admin")
    ).status_code == 201
    secret = outbox.last_secret(successor.email)
    assert (
        await client.post(
            "/api/v1/invitations/accept", json={"token": secret}, headers=successor_headers
        )
    ).status_code == 200

    transferred = await client.post(
        f"/api/v1/studios/{studio['id']}/transfer-ownership",
        json={"user_id": str(successor.id)},
        headers=owner,
    )
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["role"] == "owner"

    members = (
        await client.get(f"/api/v1/studios/{studio['id']}/members", headers=successor_headers)
    ).json()
    roles = {row["user_id"]: row["role"] for row in members}
    assert roles[str(successor.id)] == "owner"
    assert roles[str(owner_user.id)] == "admin"
    assert list(roles.values()).count("owner") == 1

    # The former owner (now admin) cannot remove the only owner.
    refused = await client.delete(
        f"/api/v1/studios/{studio['id']}/members/{successor.id}", headers=owner
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["error_code"] == "owner_required"
    still_owner = (
        await client.get(f"/api/v1/studios/{studio['id']}/members", headers=successor_headers)
    ).json()
    assert {row["user_id"]: row["role"] for row in still_owner}[str(successor.id)] == "owner"

    # An account can never change or remove itself.
    for response in (
        await client.patch(
            f"/api/v1/studios/{studio['id']}/members/{successor.id}",
            json={"role": "admin"},
            headers=successor_headers,
        ),
        await client.delete(
            f"/api/v1/studios/{studio['id']}/members/{successor.id}",
            headers=successor_headers,
        ),
    ):
        assert response.status_code == 403
        assert response.json()["detail"]["error_code"] == "self_modification_forbidden"


@pytest.mark.usefixtures("open_instance")
async def test_owner_can_promote_and_demote_a_second_owner(
    client: AsyncClient, db_session: AsyncSession, outbox: Outbox
) -> None:
    owner_user, owner = await _user_machine(db_session)
    second, second_headers = await _user_machine(db_session)
    studio = await _studio(client, owner, "Two owners")
    assert (
        await _invite(client, owner, str(studio["id"]), second.email, "member")
    ).status_code == 201
    secret = outbox.last_secret(second.email)
    assert (
        await client.post(
            "/api/v1/invitations/accept", json={"token": secret}, headers=second_headers
        )
    ).status_code == 200
    added = await client.patch(
        f"/api/v1/studios/{studio['id']}/members/{second.id}",
        json={"role": "owner"},
        headers=owner,
    )
    assert added.status_code == 200, added.text
    assert added.json()["role"] == "owner"

    # The newcomer (now owner) removes the original admin-turned-owner? Both
    # are owners; demoting the other leaves exactly one.
    demoted = await client.patch(
        f"/api/v1/studios/{studio['id']}/members/{owner_user.id}",
        json={"role": "admin"},
        headers=second_headers,
    )
    assert demoted.status_code == 200, demoted.text
    assert demoted.json()["role"] == "admin"
    members = (
        await client.get(f"/api/v1/studios/{studio['id']}/members", headers=second_headers)
    ).json()
    assert sorted({row["role"] for row in members}) == ["admin", "owner"]


# --- Sign-up -> studio -> project -------------------------------------------


@pytest.mark.usefixtures("open_instance")
async def test_verified_signup_gets_its_own_studio_and_creates_a_project(
    client: AsyncClient, db_session: AsyncSession, outbox: Outbox
) -> None:
    email = _email()
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": email},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert registered.status_code == 202
    verified = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": outbox.last_secret(email), "password": PASSWORD, "display_name": "Ada"},
    )
    assert verified.status_code == 200, verified.text
    login = await client.post("/api/v1/auth/token", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    headers = _bearer(login.json()["access_token"])

    studios = (await client.get("/api/v1/studios", headers=headers)).json()
    owned = [studio for studio in studios if studio["role"] == "owner"]
    assert len(owned) == 1
    assert owned[0]["slug"].startswith("ada")
    assert owned[0]["name"] == "Ada"

    # The new owner may provision a project in its own studio (with the studio
    # selected explicitly, as every multi-studio client does).
    project = await client.post(
        "/api/v1/projects",
        json={"slug": f"first-{uuid.uuid4().hex[:8]}", "name": "First project"},
        headers={**headers, "X-Studio-Id": owned[0]["id"]},
    )
    assert project.status_code == 201, project.text


@pytest.mark.usefixtures("open_instance")
async def test_verified_signup_via_invitation_joins_the_inviting_studio(
    client: AsyncClient, db_session: AsyncSession, outbox: Outbox
) -> None:
    _, owner = await _user_machine(db_session)
    studio = await _studio(client, owner, "Inviting studio")
    invited_email = _email()
    assert (
        await _invite(client, owner, str(studio["id"]), invited_email, "viewer")
    ).status_code == 201

    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": invited_email},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert registered.status_code == 202
    verified = await client.post(
        "/api/v1/auth/verify-email",
        json={
            "token": outbox.last_secret(invited_email),
            "password": PASSWORD,
            "display_name": "Invitee",
        },
    )
    assert verified.status_code == 200, verified.text

    invitee = await provisioning_service.get_user_by_email(db_session, invited_email)
    assert invitee is not None
    membership = await db_session.scalar(
        select(StudioMembershipModel.role).where(
            StudioMembershipModel.studio_id == uuid.UUID(str(studio["id"])),
            StudioMembershipModel.user_id == invitee.id,
        )
    )
    assert membership == "viewer"

    login = await client.post(
        "/api/v1/auth/token", json={"email": invited_email, "password": PASSWORD}
    )
    headers = _bearer(login.json()["access_token"])
    roles = {
        studio_row["id"]: studio_row["role"]
        for studio_row in (await client.get("/api/v1/studios", headers=headers)).json()
    }
    assert roles[str(studio["id"])] == "viewer"


@pytest.mark.usefixtures("open_instance")
async def test_new_invitation_replaces_the_pending_one(
    client: AsyncClient, db_session: AsyncSession, outbox: Outbox
) -> None:
    _, owner = await _user_machine(db_session)
    invitee, invitee_headers = await _user_machine(db_session)
    studio = await _studio(client, owner, "Replacement")
    assert (
        await _invite(client, owner, str(studio["id"]), invitee.email, "viewer")
    ).status_code == 201
    first_secret = outbox.last_secret(invitee.email)
    assert (
        await _invite(client, owner, str(studio["id"]), invitee.email, "member")
    ).status_code == 201
    second_secret = outbox.last_secret(invitee.email)

    stale = await client.post("/api/v1/invitations/preview", json={"token": first_secret})
    assert stale.json()["state"] == "expired"
    accepted = await client.post(
        "/api/v1/invitations/accept", json={"token": second_secret}, headers=invitee_headers
    )
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "member"
