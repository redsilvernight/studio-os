"""A5 self-service enrollment of this machine (DEC-0130, amends DEC-0093).

The renderer hands over the signed-in human's session once, through
`identity.enroll`. This module is its only consumer: it checks that the
session targets this daemon's own server origin before any network call,
makes exactly one `POST /api/v1/machines` (never retried: a replay would mint
a second credential), stores the returned credential in the OS keyring under
the same key every client reads (`KeyringTokenStore`, DEC-0024) and drops the
session. Neither the session nor the credential is logged, returned or kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import httpx
from studio_contracts.auth import MachineCreate, MachineCreated
from studio_contracts.local.common import ComponentId, LocalError, LocalErrorCode
from studio_contracts.local.identity import IdentityEnrollRequest, ProfileRef

from studio_client.config import ClientConfig
from studio_client.tokens import TokenStore


class EnrollmentError(Exception):
    """A refusal with a fixed message: never the server's text, never a secret."""

    def __init__(self, error: LocalError) -> None:
        super().__init__(error.message)
        self.error = error


def _refuse(
    code: LocalErrorCode,
    message: str,
    *,
    component: ComponentId = ComponentId.DAEMON,
    retryable: bool = False,
    reason: str | None = None,
) -> EnrollmentError:
    return EnrollmentError(
        LocalError(
            code=code,
            message=message,
            component=component,
            retryable=retryable,
            details={} if reason is None else {"reason": reason},
        )
    )


@dataclass(frozen=True)
class EnrollmentOutcome:
    machine_id: UUID | None
    """None when a credential was already stored and replacement not asked."""


def enroll_machine(
    config: ClientConfig,
    profile: ProfileRef,
    request: IdentityEnrollRequest,
    store: TokenStore,
    *,
    transport: httpx.BaseTransport | None = None,
) -> EnrollmentOutcome:
    if request.profile != profile:
        # Checked first: the session never leaves for another server.
        raise _refuse(
            LocalErrorCode.WRONG_PROFILE,
            "The session belongs to another server than this daemon's.",
        )
    origin = profile.server_origin
    try:
        existing = store.get_token(origin)
    except Exception as exc:  # noqa: BLE001
        raise _refuse(
            LocalErrorCode.KEYRING_UNAVAILABLE,
            "The OS keyring is not usable.",
            component=ComponentId.SECRET_STORE,
        ) from exc
    if existing is not None and not request.replace_existing:
        return EnrollmentOutcome(machine_id=None)

    created = _create_machine(config, request, transport)
    try:
        store.set_token(origin, created.credential)
    except Exception as exc:  # noqa: BLE001
        raise _refuse(
            LocalErrorCode.KEYRING_UNAVAILABLE,
            "The machine was created but its credential could not be stored; "
            "revoke it from the dashboard and try again.",
            component=ComponentId.SECRET_STORE,
            reason="credential_not_stored",
        ) from exc
    return EnrollmentOutcome(machine_id=created.id)


def _create_machine(
    config: ClientConfig,
    request: IdentityEnrollRequest,
    transport: httpx.BaseTransport | None,
) -> MachineCreated:
    body = MachineCreate(display_name=request.machine_name).model_dump(
        mode="json", exclude_none=True
    )
    headers = {"Authorization": f"Bearer {request.human_session.get_secret_value()}"}
    try:
        with httpx.Client(
            base_url=config.api_base_url,
            timeout=httpx.Timeout(config.read_timeout, connect=config.connect_timeout),
            verify=config.verify_tls,
            transport=transport,
        ) as client:
            response = client.post("/api/v1/machines", json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise _refuse(
            LocalErrorCode.INTERNAL_ERROR,
            "The server could not be reached.",
            retryable=True,
            reason="server_unreachable",
        ) from exc
    finally:
        headers.clear()
    if response.status_code == 401:
        raise _refuse(
            LocalErrorCode.PERMISSION_DENIED,
            "The session has expired; sign in again.",
            reason="session_expired",
        )
    if response.status_code == 403:
        raise _refuse(
            LocalErrorCode.PERMISSION_DENIED,
            "This account may not enroll a machine.",
            reason="forbidden",
        )
    if response.status_code != 201:
        raise _refuse(
            LocalErrorCode.INTERNAL_ERROR,
            "The server refused to enroll this machine.",
            retryable=response.status_code >= 500,
            reason="server_refused",
        )
    try:
        return MachineCreated.model_validate(response.json())
    except ValueError as exc:
        raise _refuse(
            LocalErrorCode.INTERNAL_ERROR,
            "The server answered with an unexpected shape.",
            reason="server_refused",
        ) from exc
