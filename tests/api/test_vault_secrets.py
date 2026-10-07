"""P05: vault secret scan refuses writes holding secrets."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.vault import VaultNoteModel
from studio_api.services.vault_secrets import SECRET_PATTERNS, scan

_AWS = "AKIA" + "0123456789ABCDEF"
_GH = "ghp_" + "B" * 36
_GH_PAT = "github_pat_" + "C" * 22
_SLACK = "xox" + "b-" + "1" * 12
_ANTHROPIC = "sk-ant-" + "a" * 20
_OPENAI = "sk-" + "d" * 20
_OPENAI_PROJ = "sk-proj-" + "e" * 20
_GOOGLE = "AIza" + "F" * 35
_STRIPE_SK = "sk_live_" + "G" * 20
_STRIPE_RK = "rk_live_" + "H" * 20
_JWT = "eyJ" + "hbGciOi" + "." + "cGF5bG9hZA" + "." + "c2lnbmF0dXJl"
_PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"
_URL = "https://" + "user" + ":" + "pass1234" + "@example.test/x"
_ASSIGN_PW = "password=" + "hunter-Hunter-09"
_ASSIGN_TOKEN = "token: " + "s3cr3t-value-xyz"
_ASSIGN_APIKEY = "api_key=" + "Zm9vYmFyLTIwMjY"
_ASSIGN_CLIENT = "client_secret=" + "wJalrXUtnFEMI"
_ASSIGN_PASSWD = "passwd=" + "correct-horse-9"
_ASSIGN_HEX = "secret=" + "9f86d081884c7d65" + "9a2feaa0c55ad015"

POSITIVES: list[tuple[str, str]] = [
    ("aws_key", _AWS),
    ("github_token", _GH),
    ("github_token", _GH_PAT),
    ("slack_token", _SLACK),
    ("anthropic_key", _ANTHROPIC),
    ("openai_key", _OPENAI),
    ("openai_key", _OPENAI_PROJ),
    ("google_key", _GOOGLE),
    ("stripe_key", _STRIPE_SK),
    ("stripe_key", _STRIPE_RK),
    ("jwt", _JWT),
    ("pem_block", _PEM),
    ("url_credentials", _URL),
    ("secret_assignment", _ASSIGN_PW),
    ("secret_assignment", _ASSIGN_TOKEN),
    ("secret_assignment", _ASSIGN_APIKEY),
    ("secret_assignment", _ASSIGN_CLIENT),
    ("secret_assignment", _ASSIGN_PASSWD),
    ("secret_assignment", _ASSIGN_HEX),
]

NEGATIVES: list[str] = [
    "token=" + '"550e8400-e29b-41d4-a716-446655440000"',
    "secret=" + "a" * 64,
    "secret=" + "b" * 40,
    "token=" + "short",
    "token=" + "<token>",
    "password=" + "${API_KEY}",
    "secret=" + "{{secret}}",
    "token=" + "x" * 10,
    "token=" + "*" * 10,
    'token=""',
    "password=" + "os.environ[" + '"TOKEN"]',
    "le token expire demain",
    "ce secret est bien garde sous cle",
    "the api key documentation is public",
    "voir https://example.test/docs pour la suite",
]


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.mark.parametrize(
    ("pattern", "value"),
    POSITIVES,
    ids=[f"{pattern}-{index}" for index, (pattern, _) in enumerate(POSITIVES)],
)
def test_scan_detects_each_pattern(pattern: str, value: str) -> None:
    findings = scan({"body": "note " + value + " fin"})
    assert any(f.field == "body" and f.pattern == pattern for f in findings)


def test_scan_reports_field_name() -> None:
    findings = scan({"title": "note " + _AWS})
    assert [(f.field, f.pattern) for f in findings] == [("title", "aws_key")]


def test_scan_patterns_cover_every_pattern_id() -> None:
    covered = {pattern for pattern, _ in POSITIVES}
    assert covered == {pattern_id for pattern_id, _ in SECRET_PATTERNS}


@pytest.mark.parametrize("value", NEGATIVES, ids=[f"clean-{index}" for index in range(15)])
def test_scan_ignores_non_secrets(value: str) -> None:
    assert scan({"body": "note " + value + " fin"}) == []


async def _count_notes(db_session: AsyncSession, slug: str) -> int:
    return (
        await db_session.execute(
            select(func.count()).select_from(VaultNoteModel).where(VaultNoteModel.slug == slug)
        )
    ).scalar_one()


async def test_create_refused_and_nothing_persisted(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "AKIA" + "0123456789ABCDEF"
    slug = _slug("sec")
    response = await client.post(
        "/api/v1/vault/notes",
        headers=auth_headers,
        json={"scope": "studio", "slug": slug, "title": "clean", "body": "key " + secret},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["error_code"] == "secret_detected"
    assert payload["detail"]["details"] == [{"field": "body", "pattern": "aws_key"}]
    assert secret not in response.text
    assert secret not in caplog.text
    assert await _count_notes(db_session, slug) == 0


async def test_create_refused_in_tags(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    secret = "ghp_" + "b" * 36
    slug = _slug("sec")
    response = await client.post(
        "/api/v1/vault/notes",
        headers=auth_headers,
        json={"scope": "studio", "slug": slug, "title": "clean", "body": "clean", "tags": [secret]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "secret_detected"
    assert {"field": "tags", "pattern": "github_token"} in response.json()["detail"]["details"]
    assert secret not in response.text
    assert await _count_notes(db_session, slug) == 0


async def test_create_refused_before_idempotency_replay(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    key = "secret-scan-key-001"
    headers = {**auth_headers, "Idempotency-Key": key}
    slug = _slug("sec")
    first = await client.post(
        "/api/v1/vault/notes",
        headers=headers,
        json={"scope": "studio", "slug": slug, "title": "clean", "body": "clean"},
    )
    assert first.status_code == 201
    secret = "sk-ant-" + "a" * 20
    second = await client.post(
        "/api/v1/vault/notes",
        headers=headers,
        json={"scope": "studio", "slug": _slug("sec"), "title": "clean", "body": secret},
    )
    assert second.status_code == 422
    assert second.json()["detail"]["error_code"] == "secret_detected"
    assert secret not in second.text


async def test_update_refused_and_note_unchanged(
    client: AsyncClient,
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    created = await client.post(
        "/api/v1/vault/notes",
        headers=auth_headers,
        json={"scope": "studio", "slug": _slug("sec"), "title": "clean", "body": "clean body"},
    )
    assert created.status_code == 201
    note_id = created.json()["id"]
    secret = "https://" + "user" + ":" + "pass1234" + "@example.test/x"
    refused = await client.patch(
        f"/api/v1/vault/notes/{note_id}",
        headers=auth_headers,
        json={"expected_version": 1, "body": "voir " + secret},
    )
    assert refused.status_code == 422
    assert refused.json()["detail"]["error_code"] == "secret_detected"
    assert refused.json()["detail"]["details"] == [{"field": "body", "pattern": "url_credentials"}]
    assert secret not in refused.text
    assert secret not in caplog.text
    fetched = await client.get(f"/api/v1/vault/notes/{note_id}", headers=auth_headers)
    assert fetched.json()["version"] == 1
    assert fetched.json()["body"] == "clean body"
    versions = await client.get(f"/api/v1/vault/notes/{note_id}/versions", headers=auth_headers)
    assert [v["version"] for v in versions.json()["items"]] == [1]


async def test_update_refused_in_change_summary(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/vault/notes",
        headers=auth_headers,
        json={"scope": "studio", "slug": _slug("sec"), "title": "clean", "body": "clean body"},
    )
    note_id = created.json()["id"]
    secret = "password=" + "hunter-Hunter-09"
    refused = await client.patch(
        f"/api/v1/vault/notes/{note_id}",
        headers=auth_headers,
        json={"expected_version": 1, "title": "renamed", "change_summary": secret},
    )
    assert refused.status_code == 422
    assert refused.json()["detail"]["details"] == [
        {"field": "change_summary", "pattern": "secret_assignment"}
    ]
    assert secret not in refused.text
    fetched = await client.get(f"/api/v1/vault/notes/{note_id}", headers=auth_headers)
    assert fetched.json()["version"] == 1
    assert fetched.json()["title"] == "clean"
