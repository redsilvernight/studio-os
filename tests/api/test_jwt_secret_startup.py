from __future__ import annotations

import pytest
from studio_api import main

_STRONG_SECRET = "a-long-random-secret-of-32-bytes!!"


@pytest.mark.parametrize(
    "secret",
    ["change-me-in-production", "change-me-to-a-long-random-string-min-32-bytes", "short"],
)
def test_weak_secret_refuses_to_start_in_production(
    monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    monkeypatch.setenv("STUDIO_ENVIRONMENT", "production")
    monkeypatch.setenv("STUDIO_JWT_SECRET", secret)

    with pytest.raises(RuntimeError, match="refusing to start in production"):
        main.create_app()


def test_production_is_the_default_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDIO_ENVIRONMENT", raising=False)
    monkeypatch.setenv("STUDIO_JWT_SECRET", "change-me-in-production")

    with pytest.raises(RuntimeError):
        main.create_app()


def test_strong_secret_starts_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_ENVIRONMENT", "production")
    monkeypatch.setenv("STUDIO_JWT_SECRET", _STRONG_SECRET)

    assert main.create_app() is not None


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_weak_secret_only_warns_outside_production(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("STUDIO_ENVIRONMENT", environment)
    monkeypatch.setenv("STUDIO_JWT_SECRET", "change-me-in-production")
    # configure_logging() rewires handlers, so caplog cannot see the record.
    warnings: list[str] = []
    monkeypatch.setattr(main.logger, "warning", lambda msg, *a, **k: warnings.append(msg))

    assert main.create_app() is not None
    assert any("default or short value" in w for w in warnings)


def test_unknown_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_ENVIRONMENT", "prod")
    monkeypatch.setenv("STUDIO_JWT_SECRET", _STRONG_SECRET)

    with pytest.raises(ValueError):
        main.create_app()
