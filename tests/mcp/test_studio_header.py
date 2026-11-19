"""MCP transport of the active studio (DEC-0382, lot 4): `X-Studio-Id` over
HTTP, `STUDIO_MCP_STUDIO_ID` on stdio, read exactly like the REST API. The
membership check itself is `load_principal`'s, never a tool's."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from studio_mcp.auth import STUDIO_ENV, requested_studio_id

from tests.mcp.conftest import FakeContext


def test_the_http_header_names_the_requested_studio() -> None:
    studio_id = uuid.uuid4()
    assert requested_studio_id(FakeContext({"X-Studio-Id": str(studio_id)})) == studio_id
    # HTTP header names arrive lower-cased from the transport.
    assert requested_studio_id(FakeContext({"x-studio-id": str(studio_id)})) == studio_id


def test_no_header_lets_the_default_studio_apply() -> None:
    assert requested_studio_id(FakeContext({"authorization": "Bearer x"})) is None
    assert requested_studio_id(FakeContext({"X-Studio-Id": "  "})) is None


def test_a_malformed_studio_is_refused_like_the_api() -> None:
    with pytest.raises(HTTPException) as refused:
        requested_studio_id(FakeContext({"X-Studio-Id": "not-a-uuid"}))
    assert refused.value.status_code == 403
    assert refused.value.detail == {
        "error_code": "forbidden",
        "resource": "studio",
        "action": "read",
    }


def test_stdio_reads_the_environment_instead(monkeypatch: pytest.MonkeyPatch) -> None:
    studio_id = uuid.uuid4()
    monkeypatch.setenv(STUDIO_ENV, str(studio_id))
    assert requested_studio_id(FakeContext(None)) == studio_id
    # With an HTTP request present, the environment is ignored.
    assert requested_studio_id(FakeContext({"authorization": "Bearer x"})) is None
    monkeypatch.delenv(STUDIO_ENV)
    assert requested_studio_id(FakeContext(None)) is None
