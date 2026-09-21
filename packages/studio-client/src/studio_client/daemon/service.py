from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import socket
import socketserver
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from pydantic import ValidationError
from studio_contracts.local.bridge import (
    BridgeCommand,
    BridgeErrorMessage,
    BridgeRequest,
    BridgeResponse,
    check_capability,
)
from studio_contracts.local.common import (
    MAX_MESSAGE_BYTES,
    ComponentId,
    LocalContractModel,
    LocalError,
    LocalErrorCode,
)
from studio_contracts.local.daemon_control import (
    DaemonAction,
    DaemonControlOutcome,
    DaemonControlRequest,
    DaemonControlResult,
    DaemonHealth,
    DaemonHealthRequest,
    DaemonOwnership,
    DaemonRunState,
    DaemonStatus,
    instance_lock_key,
)
from studio_contracts.local.handshake import (
    HandshakeRequest,
    HandshakeResponse,
    PeerInfo,
    negotiate,
)
from studio_contracts.local.identity import (
    IdentityView,
    ProfileRef,
    SecretKind,
    SecretReference,
    SecretReferenceStatus,
    SecretStatus,
    SecretStore,
)

from studio_client.config import ClientConfig, default_config_path
from studio_client.daemon.logging import configure_daemon_logging
from studio_client.daemon.runtime import AlreadyRunningError, DaemonRuntime, InstanceLock
from studio_client.outbox import OutboxIdentityError
from studio_client.tokens import KeyringTokenStore

DAEMON_VERSION = "0.1.0"
SERVED = frozenset(
    {
        BridgeCommand.RUNTIME_HANDSHAKE,
        BridgeCommand.DAEMON_STATUS,
        BridgeCommand.DAEMON_ATTACH,
        BridgeCommand.DAEMON_START,
        BridgeCommand.DAEMON_STOP,
        BridgeCommand.DAEMON_RESTART,
        BridgeCommand.DAEMON_HEALTH,
        BridgeCommand.IDENTITY_GET_VIEW,
    }
)
_LOGGER = logging.getLogger("studio_client.daemon.service")


def _now() -> datetime:
    return datetime.now(UTC)


def _message_id() -> str:
    return f"daemon-{uuid4().hex[:16]}"


class DaemonController:
    def __init__(self, config: ClientConfig, *, data_root: Path | None = None) -> None:
        self.config = config
        self.data_root = data_root or default_config_path().parent
        self._runtime: DaemonRuntime | None = None
        self._thread: threading.Thread | None = None
        self._failure: BaseException | None = None
        self._lock = threading.RLock()

    def _run_runtime(self, runtime: DaemonRuntime) -> None:
        try:
            asyncio.run(runtime.run())
        except BaseException as exc:  # noqa: BLE001
            with self._lock:
                self._failure = exc
            _LOGGER.exception("daemon runtime stopped unexpectedly")

    def _status(self) -> DaemonStatus:
        with self._lock:
            runtime = self._runtime
            thread = self._thread
            failure = self._failure
        if runtime is None or thread is None:
            return DaemonStatus(state=DaemonRunState.STOPPED)
        health_status = runtime.health().status
        if thread.is_alive():
            if health_status.state is DaemonRunState.STOPPED:
                return DaemonStatus(state=DaemonRunState.STARTING)
            return health_status
        if isinstance(failure, AlreadyRunningError):
            return DaemonStatus(state=DaemonRunState.UNAVAILABLE)
        if failure is not None:
            from studio_contracts.local.daemon_control import CrashInfo

            return DaemonStatus(
                state=DaemonRunState.CRASHED,
                last_crash=CrashInfo(
                    crashed_at=_now(),
                    recoveries_attempted=0,
                    error=LocalError(
                        code=LocalErrorCode.INTERNAL_ERROR,
                        message="The daemon runtime stopped unexpectedly.",
                        component=ComponentId.DAEMON,
                        retryable=True,
                    ),
                ),
            )
        return DaemonStatus(state=DaemonRunState.STOPPED)

    def control(self, request: DaemonControlRequest) -> DaemonControlResult:
        if request.profile != self._profile():
            return self._result(
                request,
                DaemonControlOutcome.IDENTITY_MISMATCH,
                LocalErrorCode.IDENTITY_MISMATCH,
                "The requested profile does not match the daemon configuration.",
            )
        current = self._status()
        if request.expected_instance_id is not None and (
            current.instance is None or current.instance.instance_id != request.expected_instance_id
        ):
            return self._result(
                request,
                DaemonControlOutcome.FAILED,
                LocalErrorCode.INVALID_REQUEST,
                "The daemon instance changed; refresh status before retrying.",
            )
        if (
            request.action in {DaemonAction.STOP, DaemonAction.RESTART}
            and current.instance is not None
            and current.instance.ownership is DaemonOwnership.EXTERNAL
            and not request.confirm_external
        ):
            return self._result(
                request,
                DaemonControlOutcome.FAILED,
                LocalErrorCode.INVALID_REQUEST,
                "Stopping an externally owned daemon requires explicit confirmation.",
            )
        if request.action is DaemonAction.STATUS:
            return DaemonControlResult(
                action=request.action,
                outcome=DaemonControlOutcome.OK,
                status=self._status(),
            )
        if request.action in {DaemonAction.START, DaemonAction.ATTACH}:
            return self._start_or_attach(request)
        if request.action is DaemonAction.STOP:
            return self._stop(request)
        if request.action is DaemonAction.RESTART:
            stopped = self._stop(request)
            if stopped.outcome is DaemonControlOutcome.FAILED:
                return stopped
            return self._start_or_attach(request)
        return self._result(
            request,
            DaemonControlOutcome.FAILED,
            LocalErrorCode.INVALID_REQUEST,
            "Unsupported daemon action.",
        )

    def health(self, request: DaemonHealthRequest) -> DaemonHealth:
        if request.profile != self._profile():
            raise ValueError("profile mismatch")
        with self._lock:
            runtime = self._runtime
        if runtime is None:
            runtime = DaemonRuntime(
                self.config,
                data_root=self.data_root,
                ownership=DaemonOwnership.DESKTOP_STARTED,
            )
        health = runtime.health()
        if (
            request.expected_instance_id is not None
            and health.status.instance is not None
            and request.expected_instance_id != health.status.instance.instance_id
        ):
            raise ValueError("instance mismatch")
        return health

    def identity_view(self) -> IdentityView:
        profile = self._profile()
        reference = SecretReference(
            ref_id=f"sr-machine-{profile.profile_id}",
            kind=SecretKind.MACHINE_CREDENTIAL,
            store=SecretStore.OS_KEYRING,
            lookup_key=f"studio-os.machine.{profile.profile_id}",
            profile=profile,
        )
        try:
            present = KeyringTokenStore("studio-os").get_token(profile.server_origin) is not None
            status = SecretStatus.PRESENT if present else SecretStatus.ABSENT
            error = None
            if not present:
                error = LocalError(
                    code=LocalErrorCode.SECRET_ABSENT,
                    message="No machine credential is stored.",
                    component=ComponentId.SECRET_STORE,
                    retryable=False,
                )
        except Exception:  # noqa: BLE001
            status = SecretStatus.KEYRING_UNAVAILABLE
            error = LocalError(
                code=LocalErrorCode.KEYRING_UNAVAILABLE,
                message="The OS keyring is not usable.",
                component=ComponentId.SECRET_STORE,
                retryable=False,
            )
        return IdentityView(
            profile=profile,
            secrets=[
                SecretReferenceStatus(
                    reference=reference,
                    status=status,
                    checked_at=_now(),
                    error=error,
                )
            ],
        )

    def close(self, *, persist: bool = False) -> None:
        if persist:
            return
        request = DaemonControlRequest(action=DaemonAction.STOP, profile=self._profile())
        self._stop(request)

    def _profile(self) -> ProfileRef:
        from studio_client.daemon.runtime import server_origin

        return ProfileRef(
            profile_id=self.config.profile_id,
            server_origin=server_origin(self.config.api_base_url),
        )

    def _start_or_attach(self, request: DaemonControlRequest) -> DaemonControlResult:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                outcome = (
                    DaemonControlOutcome.ALREADY_RUNNING
                    if request.action is DaemonAction.START
                    else DaemonControlOutcome.OK
                )
                error = None
                if outcome is DaemonControlOutcome.ALREADY_RUNNING:
                    error = LocalError(
                        code=LocalErrorCode.DAEMON_ALREADY_RUNNING,
                        message="A daemon already runs for this profile; attach to it.",
                        component=ComponentId.DAEMON,
                        retryable=False,
                    )
                return DaemonControlResult(
                    action=request.action,
                    outcome=outcome,
                    status=self._status(),
                    error=error,
                )
            runtime = DaemonRuntime(
                self.config,
                data_root=self.data_root,
                ownership=DaemonOwnership.DESKTOP_STARTED,
            )
            self._runtime = runtime
            self._failure = None
            self._thread = threading.Thread(
                target=self._run_runtime,
                args=(runtime,),
                name="studio-daemon-runtime",
                daemon=False,
            )
            self._thread.start()
        return DaemonControlResult(
            action=request.action,
            outcome=DaemonControlOutcome.OK,
            status=self._status(),
        )

    def _stop(self, request: DaemonControlRequest) -> DaemonControlResult:
        with self._lock:
            runtime = self._runtime
            thread = self._thread
        if runtime is None or thread is None or not thread.is_alive():
            return DaemonControlResult(
                action=request.action,
                outcome=DaemonControlOutcome.NOT_RUNNING,
                status=DaemonStatus(state=DaemonRunState.STOPPED),
            )
        timeout_seconds = request.timeout_ms / 1000
        drain_budget = timeout_seconds / 2 if request.drain_outbox else 0
        drained = runtime.request_stop(
            drain_outbox=request.drain_outbox,
            timeout_seconds=drain_budget,
        )
        thread.join(timeout_seconds - drain_budget)
        if thread.is_alive():
            return self._result(
                request,
                DaemonControlOutcome.FAILED,
                LocalErrorCode.TIMEOUT,
                "The daemon did not stop within the requested timeout.",
            )
        with self._lock:
            self._runtime = None
            self._thread = None
        if not drained:
            return self._result(
                request,
                DaemonControlOutcome.FAILED,
                LocalErrorCode.TIMEOUT,
                "The daemon stopped, but its outbox could not be drained in time.",
            )
        return DaemonControlResult(
            action=request.action,
            outcome=DaemonControlOutcome.OK,
            status=DaemonStatus(state=DaemonRunState.STOPPED),
        )

    def _result(
        self,
        request: DaemonControlRequest,
        outcome: DaemonControlOutcome,
        code: LocalErrorCode,
        message: str,
    ) -> DaemonControlResult:
        return DaemonControlResult(
            action=request.action,
            outcome=outcome,
            status=self._status(),
            error=LocalError(
                code=code,
                message=message,
                component=ComponentId.DAEMON,
                retryable=False,
            ),
        )


class BridgeService:
    def __init__(self, controller: DaemonController) -> None:
        self.controller = controller
        self._granted_capabilities: set[str] = set()

    def handle_line(self, line: str) -> dict[str, Any]:
        if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
            return self._error(None, None, LocalErrorCode.INVALID_REQUEST, "Request too large.")
        try:
            request = BridgeRequest.model_validate_json(line)
        except ValidationError:
            return self._error(None, None, LocalErrorCode.INVALID_REQUEST, "Invalid request.")
        if request.command not in SERVED:
            return self._error(
                request,
                request.correlation_id,
                LocalErrorCode.NOT_SUPPORTED,
                "Command is not served by the daemon.",
            )
        capability_error = check_capability(request.command, self._granted_capabilities)
        if capability_error is not None:
            return self._local_error(request, capability_error)
        try:
            payload = self._answer(request)
        except (ValidationError, ValueError):
            return self._error(
                request,
                request.correlation_id,
                LocalErrorCode.INVALID_REQUEST,
                "The request payload is invalid.",
            )
        except OutboxIdentityError:
            return self._error(
                request,
                request.correlation_id,
                LocalErrorCode.IDENTITY_MISMATCH,
                "Queued work belongs to another identity.",
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("bridge request failed")
            return self._error(
                request,
                request.correlation_id,
                LocalErrorCode.INTERNAL_ERROR,
                "The daemon could not complete the request.",
            )
        if isinstance(payload, HandshakeResponse):
            self._granted_capabilities = set(payload.granted_capabilities)
        response = BridgeResponse(
            message_id=_message_id(),
            correlation_id=request.correlation_id,
            request_id=request.message_id,
            sent_at=_now(),
            command=request.command,
            payload=payload.model_dump(mode="json"),
        )
        return response.model_dump(mode="json")

    @staticmethod
    def _local_error(request: BridgeRequest, error: LocalError) -> dict[str, Any]:
        response = BridgeErrorMessage(
            message_id=_message_id(),
            correlation_id=request.correlation_id,
            request_id=request.message_id,
            sent_at=_now(),
            error=error.model_copy(update={"correlation_id": request.correlation_id}),
        )
        return response.model_dump(mode="json")

    def _answer(self, request: BridgeRequest) -> LocalContractModel:
        if request.command is BridgeCommand.RUNTIME_HANDSHAKE:
            return negotiate(
                HandshakeRequest.model_validate(request.payload),
                PeerInfo.model_validate(
                    {
                        "role": "daemon",
                        "protocol": {
                            "minimum": {"major": 1, "minor": 0},
                            "maximum": {"major": 1, "minor": 0},
                        },
                        "component_version": DAEMON_VERSION,
                        "capabilities": ["daemon.control", "daemon.health", "identity.view"],
                    }
                ),
                correlation_id=request.correlation_id,
            )
        if request.command is BridgeCommand.DAEMON_HEALTH:
            return self.controller.health(DaemonHealthRequest.model_validate(request.payload))
        if request.command is BridgeCommand.IDENTITY_GET_VIEW:
            return self.controller.identity_view()
        return self.controller.control(DaemonControlRequest.model_validate(request.payload))

    @staticmethod
    def _error(
        request: BridgeRequest | None,
        correlation_id: str | None,
        code: LocalErrorCode,
        message: str,
    ) -> dict[str, Any]:
        response = BridgeErrorMessage(
            message_id=_message_id(),
            correlation_id=correlation_id or "unknown",
            request_id=request.message_id if request else None,
            sent_at=_now(),
            error=LocalError(
                code=code,
                message=message,
                component=ComponentId.DAEMON,
                retryable=False,
                correlation_id=correlation_id,
            ),
        )
        return response.model_dump(mode="json")


class SharedBridgeService:
    def __init__(self, controller: DaemonController) -> None:
        self.controller = controller
        self.local = BridgeService(controller)
        key = instance_lock_key(controller._profile())
        control_root = controller.data_root / "control"
        control_root.mkdir(parents=True, exist_ok=True)
        self.registry_path = control_root / f"{key}.json"
        self._instance_lock = InstanceLock(control_root / f"{key}.lock")
        self._owner = self._instance_lock.acquire()
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None
        self._token: str | None = None
        self._sessions: dict[str, BridgeService] = {}
        self._sessions_lock = threading.Lock()
        self._session_id = secrets.token_urlsafe(24)
        if self._owner:
            self._start_server()

    def handle_line(self, line: str) -> dict[str, Any]:
        if self._owner:
            return self.local.handle_line(line)
        return self._proxy(line)

    def close(self, *, persist: bool) -> None:
        if not self._owner:
            return
        if persist:
            while self.controller._status().state not in {
                DaemonRunState.STOPPED,
                DaemonRunState.CRASHED,
                DaemonRunState.UNAVAILABLE,
            }:
                time.sleep(0.2)
        self.controller.close(persist=False)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.registry_path.unlink(missing_ok=True)
        self._instance_lock.release()

    def _start_server(self) -> None:
        self._token = secrets.token_urlsafe(32)
        sessions = self._sessions
        sessions_lock = self._sessions_lock
        controller = self.controller
        token = self._token

        class Handler(socketserver.StreamRequestHandler):
            def handle(handler_self) -> None:
                raw = handler_self.rfile.readline(MAX_MESSAGE_BYTES + 1024)
                try:
                    envelope = json.loads(raw)
                    if not secrets.compare_digest(envelope.get("token", ""), token):
                        return
                    line = envelope["line"]
                    session_id = envelope["session_id"]
                    if not isinstance(line, str) or not isinstance(session_id, str):
                        return
                    with sessions_lock:
                        session_service = sessions.setdefault(session_id, BridgeService(controller))
                    answer = session_service.handle_line(line)
                    handler_self.wfile.write(
                        json.dumps(answer, separators=(",", ":")).encode() + b"\n"
                    )
                except (json.JSONDecodeError, KeyError, TypeError):
                    return

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = False
            daemon_threads = True

        server = Server(("127.0.0.1", 0), Handler)
        self._server = server
        registry = {
            "pid": os.getpid(),
            "port": server.server_address[1],
            "token": token,
        }
        temporary = self.registry_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(registry), encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(self.registry_path)
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="studio-daemon-control",
            daemon=True,
        )
        self._thread.start()

    def _proxy(self, line: str) -> dict[str, Any]:
        deadline = time.monotonic() + 2
        while True:
            try:
                registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
                with socket.create_connection(
                    ("127.0.0.1", int(registry["port"])), timeout=2
                ) as connection:
                    envelope = json.dumps(
                        {
                            "token": registry["token"],
                            "session_id": self._session_id,
                            "line": line,
                        },
                        separators=(",", ":"),
                    ).encode()
                    connection.sendall(envelope + b"\n")
                    response = connection.makefile("rb").readline(MAX_MESSAGE_BYTES + 1)
                if not response or len(response) > MAX_MESSAGE_BYTES:
                    raise OSError("invalid daemon control response")
                parsed = json.loads(response)
                if not isinstance(parsed, dict):
                    raise OSError("invalid daemon control response")
                return parsed
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                if time.monotonic() >= deadline:
                    return BridgeService._error(
                        None,
                        None,
                        LocalErrorCode.DAEMON_UNAVAILABLE,
                        "The existing daemon control endpoint is unavailable.",
                    )
                time.sleep(0.05)


def serve_streams(
    service: BridgeService | SharedBridgeService,
    source: TextIO,
    destination: TextIO,
) -> None:
    for line in source:
        if not line.strip():
            continue
        answer = service.handle_line(line)
        destination.write(json.dumps(answer, separators=(",", ":")) + "\n")
        destination.flush()


def main() -> int:
    config = ClientConfig()  # type: ignore[call-arg]
    data_root = default_config_path().parent
    configure_daemon_logging(data_root)
    controller = DaemonController(config, data_root=data_root)
    service = SharedBridgeService(controller)
    persist = os.environ.get("STUDIO_DAEMON_PERSIST") == "1"
    if service._owner and os.environ.get("STUDIO_DAEMON_AUTOSTART") == "1":
        controller.control(
            DaemonControlRequest(action=DaemonAction.START, profile=controller._profile())
        )
    try:
        serve_streams(service, sys.stdin, sys.stdout)
    finally:
        service.close(persist=persist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
