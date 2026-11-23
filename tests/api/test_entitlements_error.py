"""The limit error is one shape, built by the single entitlements module."""

from __future__ import annotations

from studio_api.services import entitlements


def test_plan_limit_reached_carries_limit_and_upgrade_url() -> None:
    error = entitlements.plan_limit_reached(
        entitlements.STORAGE_BYTES, max_value=2048, current=2048, requested=10
    )

    assert error.status_code == 402
    assert error.detail == {
        "error_code": "plan_limit_reached",
        "limit": "storage_bytes",
        "upgrade_url": entitlements.upgrade_url(),
        "max_value": 2048,
        "current": 2048,
        "requested": 10,
    }


def test_upgrade_url_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_BILLING_UPGRADE_URL", "https://billing.example.test/upgrade")

    assert entitlements.upgrade_url() == "https://billing.example.test/upgrade"
