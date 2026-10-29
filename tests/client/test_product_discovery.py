from __future__ import annotations

import asyncio
import json

import pytest
from studio_client import cli
from studio_contracts.discovery import ProductDiscovery


def test_cli_uses_shared_discovery_and_exposes_detail_on_demand(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen = []

    class Client:
        async def discover_capabilities(self, **kwargs: object) -> ProductDiscovery:
            seen.append(kwargs)
            return ProductDiscovery(intent="overview", summary="Shared product catalogue")

    monkeypatch.setattr(cli, "_run", lambda _config, action: asyncio.run(action(Client())))
    args = cli._build_parser().parse_args(["capabilities", "--key", "vault", "--json"])
    args.func(args, None)
    assert seen == [{"intent": "overview", "key": "vault", "limit": 6}]
    assert json.loads(capsys.readouterr().out)["summary"] == "Shared product catalogue"
