"""Sliding-window quotas behind public self-registration (S5), pure logic:
no database, no HTTP. The router wiring is covered by
`tests/api/test_registration_abuse.py`."""

from __future__ import annotations

from studio_api.registration_guard import (
    LimitVerdict,
    RegistrationGuard,
    RegistrationLimits,
    email_domain,
    is_disposable_domain,
)
from studio_api.settings import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"environment": "test"}
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_guard_sliding_window_expires() -> None:
    guard = RegistrationGuard()
    limits = RegistrationLimits(per_ip=1, per_domain=0, window_seconds=60)

    assert guard.check(limits, client_ip="203.0.113.7", domain="a.test", now=1_000.0) is None
    verdict = guard.check(limits, client_ip="203.0.113.7", domain="a.test", now=1_030.0)
    assert verdict == LimitVerdict(scope="ip", retry_after_seconds=30)
    assert guard.check(limits, client_ip="203.0.113.7", domain="a.test", now=1_061.0) is None


def test_guard_domain_scope_is_independent_of_ip() -> None:
    guard = RegistrationGuard()
    limits = RegistrationLimits(per_ip=0, per_domain=1, window_seconds=60)

    assert guard.check(limits, client_ip="203.0.113.7", domain="a.test", now=1_000.0) is None
    verdict = guard.check(limits, client_ip="203.0.113.8", domain="a.test", now=1_000.0)
    assert verdict is not None
    assert verdict.scope == "domain"
    assert guard.check(limits, client_ip="203.0.113.8", domain="b.test", now=1_000.0) is None


def test_guard_tracks_profiles_separately() -> None:
    guard = RegistrationGuard()
    strict = RegistrationLimits(per_ip=1, per_domain=0, window_seconds=60)
    lenient = RegistrationLimits(per_ip=5, per_domain=0, window_seconds=60)

    assert guard.check(strict, client_ip="203.0.113.7", domain="a.test", now=1_000.0) is None
    assert guard.check(lenient, client_ip="203.0.113.7", domain="a.test", now=1_000.0) is None


def test_disposable_domains_match_subdomains_but_not_lookalikes() -> None:
    settings = _settings(registration_disposable_email_domains="Mailinator.com, spam.test ")
    assert is_disposable_domain("mailinator.com", settings) is True
    assert is_disposable_domain("sub.mailinator.com", settings) is True
    assert is_disposable_domain("notmailinator.com", settings) is False
    assert is_disposable_domain("spam.test", settings) is True


def test_email_domain_is_normalized() -> None:
    assert email_domain("  Ada@Example.TEST ") == "example.test"
