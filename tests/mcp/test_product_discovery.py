from __future__ import annotations

from studio_mcp.tools.discovery import studio_discover_capabilities

from tests.mcp.conftest import FakeContext


async def test_product_discovery_is_compact_then_detailed(auth_ctx: FakeContext) -> None:
    first = await studio_discover_capabilities(auth_ctx)
    assert len(first["capabilities"]) == 6
    assert first["additional_available"] > 0
    assert len(str(first)) < 6000
    detail = await studio_discover_capabilities(auth_ctx, key="vault")
    assert len(detail["capabilities"]) == 1
    assert detail["capabilities"][0]["example"]
    assert detail["capabilities"][0]["prerequisites"]


async def test_discovery_readonly_and_structured_errors(readonly_auth_ctx: FakeContext) -> None:
    result = await studio_discover_capabilities(readonly_auth_ctx, key="coordination")
    assert result["capabilities"][0]["state"] == "not_authorized"
    invalid = await studio_discover_capabilities(readonly_auth_ctx, limit=1000)
    assert invalid["error_code"] == "invalid_argument"
    unknown = await studio_discover_capabilities(readonly_auth_ctx, key="not-real")
    assert unknown["error_code"] == "capability_not_found"
    too_long = await studio_discover_capabilities(readonly_auth_ctx, key="x" * 81)
    assert too_long["error_code"] == "invalid_argument"
