from __future__ import annotations

from uuid import UUID

import pytest
from studio_contracts.local.workspace import WorkspaceRoots, WorkspaceSaveConfigRequest
from studio_workspaces.root_confirmation import (
    ConfirmationExpired,
    ConfirmationInvalid,
    ConfirmationMismatch,
    ConfirmationMissing,
    ConfirmationReused,
    RootConfirmationService,
    StrayConfirmation,
    roots_fingerprint,
)

from .factories import make_config, make_roots

WS_ID = "11111111-1111-4111-8111-111111111111"


def _roots(path: str) -> WorkspaceRoots:
    return make_roots(path, [("game", f"{path}/game")])


def test_first_authorization_requires_confirmation() -> None:
    service = RootConfirmationService()
    config = make_config(UUID(WS_ID), "C:/Work/demo")
    with pytest.raises(ConfirmationMissing):
        service.consume(None, None, config.roots)
    with pytest.raises(ValueError, match="requires root_confirmation_id"):
        WorkspaceSaveConfigRequest(config=config, current_roots=None, root_confirmation_id=None)


def test_first_authorization_with_confirmation() -> None:
    service = RootConfirmationService()
    config = make_config(UUID(WS_ID), "C:/Work/demo")
    cid = service.issue(config.roots)
    service.consume(cid, None, config.roots)
    WorkspaceSaveConfigRequest(config=config, current_roots=None, root_confirmation_id=cid)


def test_root_change_requires_confirmation() -> None:
    service = RootConfirmationService()
    old, new = _roots("C:/Work/demo"), _roots("D:/Work/demo")
    with pytest.raises(ConfirmationMissing):
        service.consume(None, old, new)
    config = make_config(UUID(WS_ID), "D:/Work/demo")
    with pytest.raises(ValueError, match="requires root_confirmation_id"):
        WorkspaceSaveConfigRequest(config=config, current_roots=old, root_confirmation_id=None)


def test_unknown_confirmation_is_invalid() -> None:
    service = RootConfirmationService()
    with pytest.raises(ConfirmationInvalid):
        service.consume("rc-unknown", None, _roots("C:/Work/demo"))


def test_confirmation_cannot_be_reused() -> None:
    service = RootConfirmationService()
    roots = _roots("C:/Work/demo")
    cid = service.issue(roots)
    service.consume(cid, None, roots)
    with pytest.raises(ConfirmationReused):
        service.consume(cid, None, roots)


def test_confirmation_bound_to_other_roots_is_refused() -> None:
    service = RootConfirmationService()
    cid = service.issue(_roots("C:/Work/demo"))
    with pytest.raises(ConfirmationMismatch):
        service.consume(cid, _roots("C:/Work/demo"), _roots("D:/Work/demo"))


def test_expired_confirmation_is_refused() -> None:
    now = [1000.0]
    service = RootConfirmationService(ttl_seconds=10.0, clock=lambda: now[0])
    roots = _roots("C:/Work/demo")
    cid = service.issue(roots)
    now[0] += 60.0
    with pytest.raises(ConfirmationExpired):
        service.consume(cid, None, roots)


def test_stable_config_must_not_carry_confirmation() -> None:
    service = RootConfirmationService()
    roots = _roots("C:/Work/demo")
    with pytest.raises(StrayConfirmation):
        service.consume("rc-stray", roots, roots)
    config = make_config(UUID(WS_ID), "C:/Work/demo")
    with pytest.raises(ValueError, match="only valid on a root transition"):
        WorkspaceSaveConfigRequest(
            config=config, current_roots=config.roots, root_confirmation_id="rc-stray"
        )


def test_repo_order_counts_as_transition() -> None:
    service = RootConfirmationService()
    first = make_roots("C:/Work/demo", [("a", "C:/Work/demo/a"), ("b", "C:/Work/demo/b")])
    second = make_roots("C:/Work/demo", [("b", "C:/Work/demo/b"), ("a", "C:/Work/demo/a")])
    assert first != second
    assert roots_fingerprint(first) != roots_fingerprint(second)
    with pytest.raises(ConfirmationMissing):
        service.consume(None, first, second)


def test_fingerprint_is_stable() -> None:
    assert roots_fingerprint(_roots("C:/Work/demo")) == roots_fingerprint(_roots("C:/Work/demo"))
