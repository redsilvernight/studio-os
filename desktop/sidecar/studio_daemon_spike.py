"""P2 daemon-gate spike: a SIMULATED daemon that speaks the real `studio.local/v1`.

It is NOT the Studio OS daemon (that is P4/P10). It exists to prove, with the
same executable shape the real daemon will have, that the Desktop shell can
find a packaged Python sidecar, exchange bridge messages over stdio, observe
the process and see it end.

What is real: the P1 models (`studio_contracts.local`), the reference
`negotiate()`, envelope validation, and the Windows secure-storage round trip
through `studio_client.tokens.KeyringTokenStore` (the single vault).
What is simulated: the daemon state reported by `daemon.status` (there is no
supervisor, outbox or lock here) and the human/machine identity (none is
registered; the spike never reads a server).

Protocol: one JSON object per line on stdin, one per line on stdout. Exit on
EOF. No argument is read. No raw secret is ever written to stdout.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from studio_client.tokens import KeyringTokenStore
from studio_contracts.local.bridge import BridgeErrorMessage, BridgeRequest, BridgeResponse
from studio_contracts.local.common import (
    ComponentId,
    LocalError,
    LocalErrorCode,
)
from studio_contracts.local.daemon_control import (
    DaemonControlOutcome,
    DaemonControlRequest,
    DaemonControlResult,
    DaemonInstanceRef,
    DaemonOwnership,
    DaemonRunState,
    DaemonStatus,
    instance_lock_key,
)
from studio_contracts.local.handshake import HandshakeRequest, PeerInfo, negotiate
from studio_contracts.local.identity import (
    IdentityView,
    ProfileRef,
    SecretKind,
    SecretReference,
    SecretReferenceStatus,
    SecretStatus,
    SecretStore,
)

SPIKE_VERSION = "0.1.0"
SERVED = ("runtime.handshake", "daemon.status", "identity.get_view")
PROBE_SERVICE = "studio-os-desktop-spike"  # throwaway namespace, never the real one
REAL_SERVICE = "studio-os"  # where `studio_client` keeps the machine token
INSTANCE_ID = uuid.uuid4()
STARTED_AT = datetime.now(UTC).replace(microsecond=0)
PROFILE = ProfileRef(
    profile_id="default",
    server_origin=os.environ.get("STUDIO_SPIKE_SERVER_ORIGIN", "https://studio.example.test"),
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id() -> str:
    return f"daemon-{uuid.uuid4().hex[:16]}"


def _local_error(
    code: LocalErrorCode, message: str, cid: str | None, component: ComponentId
) -> LocalError:
    return LocalError(
        code=code, message=message, component=component, retryable=False, correlation_id=cid
    )


def _peer() -> PeerInfo:
    return PeerInfo.model_validate(
        {
            "role": "daemon",
            "protocol": {"minimum": {"major": 1, "minor": 0}, "maximum": {"major": 1, "minor": 0}},
            "component_version": SPIKE_VERSION,
            "capabilities": ["daemon.control", "identity.view"],
        }
    )


def keyring_roundtrip() -> bool:
    """Write, read back and delete a throwaway NON-secret value in the OS
    keyring. Proves the backend is usable from this (frozen) process."""
    store = KeyringTokenStore(PROBE_SERVICE)
    probe = f"probe-{uuid.uuid4().hex}"
    try:
        store.set_token("gate-probe", probe)
        ok = store.get_token("gate-probe") == probe
        store.clear_token("gate-probe")
        return ok and store.get_token("gate-probe") is None
    except Exception:  # noqa: BLE001 - any backend failure means unavailable
        return False


def _real_secret_present() -> bool:
    """Whether the machine credential exists — never its value."""
    try:
        return KeyringTokenStore(REAL_SERVICE).get_token(PROFILE.server_origin) is not None
    except Exception:  # noqa: BLE001
        return False


def identity_view(cid: str) -> IdentityView:
    reference = SecretReference(
        ref_id="sr-machine-default",
        kind=SecretKind.MACHINE_CREDENTIAL,
        store=SecretStore.OS_KEYRING,
        lookup_key="studio-os.machine.default",
        profile=PROFILE,
    )
    error: LocalError | None
    if not keyring_roundtrip():
        status = SecretStatus.KEYRING_UNAVAILABLE
        error = _local_error(
            LocalErrorCode.KEYRING_UNAVAILABLE,
            "The OS keyring is not usable.",
            cid,
            ComponentId.SECRET_STORE,
        )
    elif _real_secret_present():
        status, error = SecretStatus.PRESENT, None
    else:
        status = SecretStatus.ABSENT
        error = _local_error(
            LocalErrorCode.SECRET_ABSENT,
            "No machine credential is stored.",
            cid,
            ComponentId.SECRET_STORE,
        )
    return IdentityView(
        profile=PROFILE,
        secrets=[
            SecretReferenceStatus(
                reference=reference, status=status, checked_at=_now(), error=error
            )
        ],
    )


def daemon_status(request: DaemonControlRequest) -> DaemonControlResult:
    instance = DaemonInstanceRef(
        instance_id=INSTANCE_ID,
        profile=request.profile,
        lock_key=instance_lock_key(request.profile),
        pid=os.getpid(),
        ownership=DaemonOwnership.DESKTOP_STARTED,
        daemon_version=SPIKE_VERSION,
        started_at=STARTED_AT.isoformat().replace("+00:00", "Z"),
    )
    status = DaemonStatus(
        state=DaemonRunState.RUNNING,
        instance=instance,
        negotiated={"major": 1, "minor": 0},
    )
    return DaemonControlResult(
        action=request.action, outcome=DaemonControlOutcome.OK, status=status
    )


def answer(request: BridgeRequest) -> dict[str, Any]:
    cid = request.correlation_id
    command = request.command.value
    if command == "runtime.handshake":
        payload = negotiate(
            HandshakeRequest.model_validate(request.payload), _peer(), correlation_id=cid
        )
    elif command == "daemon.status":
        payload = daemon_status(DaemonControlRequest.model_validate(request.payload))
    elif command == "identity.get_view":
        payload = identity_view(cid)
    else:
        raise LookupError(command)
    message = BridgeResponse(
        message_id=_new_id(),
        correlation_id=cid,
        request_id=request.message_id,
        sent_at=_now(),
        command=request.command,
        payload=payload.model_dump(mode="json"),
    )
    dumped: dict[str, Any] = message.model_dump(mode="json")
    return dumped


def error(
    code: LocalErrorCode, message: str, request: BridgeRequest | None, cid: str | None
) -> dict[str, Any]:
    envelope = BridgeErrorMessage(
        message_id=_new_id(),
        correlation_id=cid or "unknown",
        request_id=request.message_id if request else None,
        sent_at=_now(),
        error=_local_error(code, message, cid, ComponentId.DAEMON),
    )
    dumped: dict[str, Any] = envelope.model_dump(mode="json")
    return dumped


def handle_line(line: str) -> dict[str, Any]:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return error(LocalErrorCode.INVALID_REQUEST, "The request is not valid JSON.", None, None)
    cid = raw.get("correlation_id") if isinstance(raw, dict) else None
    cid = cid if isinstance(cid, str) else None
    try:
        request = BridgeRequest.model_validate(raw)
    except ValidationError:
        return error(
            LocalErrorCode.INVALID_REQUEST, "The request violates studio.local/v1.", None, cid
        )
    if request.command.value not in SERVED:
        return error(
            LocalErrorCode.NOT_SUPPORTED, "Command not served by the P2 spike.", request, cid
        )
    try:
        return answer(request)
    except ValidationError:
        return error(
            LocalErrorCode.INVALID_REQUEST, "The payload violates its P1 model.", request, cid
        )
    except Exception:  # noqa: BLE001 - never leak internals over the bridge
        return error(LocalErrorCode.INTERNAL_ERROR, "The spike failed to answer.", request, cid)


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        sys.stdout.write(json.dumps(handle_line(line), separators=(",", ":")) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
