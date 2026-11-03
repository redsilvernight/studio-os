from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from studio_client import cli
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.tokens import MemoryTokenStore
from studio_contracts.transfers import Transfer


def _install_client(
    monkeypatch: pytest.MonkeyPatch, status: str = "ready", error: int = 204
) -> tuple[Transfer, list[str]]:
    transfer = Transfer.model_validate(
        {
            "id": uuid4(),
            "transfer_code": "TRF-TEST",
            "sender_user_id": uuid4(),
            "category": "temporary",
            "filename": "studio archive.zip",
            "object_key": "studio/archive.zip",
            "content_type": "application/zip",
            "size_bytes": 12,
            "status": status,
            "created_at": datetime.now(UTC),
        }
    )
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json=transfer.model_dump(mode="json"))
        if error == 204:
            return httpx.Response(204)
        return httpx.Response(
            error,
            json={"detail": {"error_code": "forbidden" if error == 403 else "storage_unavailable"}},
        )

    async def with_client(
        config: ClientConfig, action: Callable[[StudioApiClient], Awaitable[Any]]
    ) -> tuple[Any, StudioApiClient]:
        store = MemoryTokenStore()
        store.set_token("http://test", "token")
        async with StudioApiClient(config, store, transport=httpx.MockTransport(handler)) as client:
            return await action(client), client

    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "http://test")
    monkeypatch.setenv("STUDIO_CLIENT_MAX_ATTEMPTS", "1")
    monkeypatch.setattr(cli, "_with_client", with_client)
    return transfer, methods


def test_delete_requires_filename_confirmation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transfer, methods = _install_client(monkeypatch)
    with pytest.raises(SystemExit, match="1"):
        cli.main(["transfers", "delete", str(transfer.id), "--json"])
    assert transfer.filename in capsys.readouterr().err
    assert methods == ["GET"]


def test_delete_confirmed_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transfer, methods = _install_client(monkeypatch)
    cli.main(["transfers", "delete", str(transfer.id), "--yes", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert result["filename"] == transfer.filename
    assert result["status"] == "deleted"
    assert result["already_deleted"] is False
    assert methods == ["GET", "DELETE"]


def test_delete_replay_still_checks_permission(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transfer, methods = _install_client(monkeypatch, status="deleted")
    cli.main(["transfers", "delete", str(transfer.id), "--json"])
    assert json.loads(capsys.readouterr().out)["already_deleted"] is True
    assert methods == ["GET", "DELETE"]


@pytest.mark.parametrize("error", [403, 503])
def test_delete_error_has_no_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error: int
) -> None:
    transfer, methods = _install_client(monkeypatch, error=error)
    with pytest.raises(SystemExit, match="1"):
        cli.main(["transfers", "delete", str(transfer.id), "--yes", "--json"])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert ("forbidden" if error == 403 else "storage_unavailable") in captured.err
    assert methods == ["GET", "DELETE"]
