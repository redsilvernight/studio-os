"""Detect, preview, apply and roll back harness configuration.

The bridge-facing service. It speaks only the `harness.*` contract models and
the vendor-neutral adapter interface; it knows no file name, format or CLI.
Preview never writes. Apply is bound to a previewed plan, backs up first,
writes atomically, verifies, and restores on failure. Rollback refuses to
overwrite anything the user changed after the apply.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from studio_contracts.local.common import ComponentId, LocalError, LocalErrorCode
from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessApplyResult,
    HarnessChange,
    HarnessDetectResult,
    HarnessPlan,
    HarnessPreviewRequest,
    HarnessRollbackRequest,
    HarnessRollbackResult,
    HarnessState,
    HarnessStatus,
    HarnessStatusRequest,
    HarnessVerifyRequest,
    HarnessVerifyResult,
    VerifyState,
)
from studio_contracts.local.workspace import WorkspaceScope

from studio_client.harness.backup import (
    BackupError,
    BackupRecord,
    BackupStore,
)
from studio_client.harness.base import (
    AdapterRefusal,
    Detection,
    DetectionState,
    HarnessAdapter,
    HarnessContext,
    PlannedEdit,
    system_env,
)
from studio_client.harness.fsafe import (
    FsError,
    atomic_write,
    read_document,
    remove_file,
    resolve_target,
)
from studio_client.harness.registry import HarnessRegistry

PLAN_TTL_SECONDS = 600
MAX_STORED_PLANS = 64
_LATEST_PREFIX = "latest:"


@dataclass(frozen=True)
class WorkspaceInfo:
    """What the service needs to know about a workspace, supplied by the daemon
    from its own registry."""

    workspace_id: UUID
    root: Path
    mcp_url: str
    harness_enabled: bool


WorkspaceLookup = Callable[[UUID], WorkspaceInfo | None]


class HarnessServiceError(Exception):
    """A refusal with the structured error the bridge returns. `reason` is a
    stable token in `error.details`; the message never carries a path."""

    def __init__(self, error: LocalError) -> None:
        super().__init__(error.message)
        self.error = error


def _error(
    code: LocalErrorCode, message: str, reason: str, *, retryable: bool = False
) -> HarnessServiceError:
    return HarnessServiceError(
        LocalError(
            code=code,
            message=message,
            component=ComponentId.HARNESS,
            retryable=retryable,
            details={"reason": reason},
        )
    )


_REFUSAL_CODES: dict[str, LocalErrorCode] = {
    "executable_not_found": LocalErrorCode.PROVIDER_NOT_INSTALLED,
    "unsupported_version": LocalErrorCode.PROVIDER_INCOMPATIBLE,
    "permission_denied": LocalErrorCode.PERMISSION_DENIED,
    "read_only": LocalErrorCode.PERMISSION_DENIED,
    "timeout": LocalErrorCode.TIMEOUT,
    "probe_failed": LocalErrorCode.INTERNAL_ERROR,
    "unexpected_output": LocalErrorCode.INTERNAL_ERROR,
    "not_executable": LocalErrorCode.INTERNAL_ERROR,
    "workspace_inaccessible": LocalErrorCode.WORKSPACE_INACCESSIBLE,
    "io_error": LocalErrorCode.INTERNAL_ERROR,
    "backup_failed": LocalErrorCode.INTERNAL_ERROR,
}
_MESSAGES: dict[LocalErrorCode, str] = {
    LocalErrorCode.PROVIDER_NOT_INSTALLED: "This harness is not installed on this machine.",
    LocalErrorCode.PROVIDER_INCOMPATIBLE: "This harness version is not supported.",
    LocalErrorCode.PERMISSION_DENIED: "The harness configuration cannot be written here.",
    LocalErrorCode.TIMEOUT: "The harness did not answer in time.",
    LocalErrorCode.INTERNAL_ERROR: "The harness could not be inspected or changed.",
    LocalErrorCode.WORKSPACE_INACCESSIBLE: "The workspace is not accessible.",
    LocalErrorCode.WORKSPACE_CONFIG_INVALID: "The harness configuration is not valid.",
}


def _refusal_error(reason: str) -> HarnessServiceError:
    code = _REFUSAL_CODES.get(reason, LocalErrorCode.WORKSPACE_CONFIG_INVALID)
    return _error(code, _MESSAGES[code], reason)


def _local_error(code: LocalErrorCode, reason: str) -> LocalError:
    return LocalError(
        code=code,
        message=_MESSAGES[code],
        component=ComponentId.HARNESS,
        retryable=False,
        details={"reason": reason},
    )


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _StoredPlan:
    plan: HarnessPlan
    edits: list[PlannedEdit]
    ctx: HarnessContext


class HarnessService:
    def __init__(
        self,
        registry: HarnessRegistry,
        backups: BackupStore,
        workspaces: WorkspaceLookup,
        *,
        env: Callable[[], Mapping[str, str]] = system_env,
        probe_cwd: Path | None = None,
        clock: Callable[[], datetime] = _now,
        plan_ttl_seconds: int = PLAN_TTL_SECONDS,
    ) -> None:
        self._registry = registry
        self._backups = backups
        self._workspaces = workspaces
        self._env = env
        self._probe_cwd = probe_cwd or Path(_neutral_cwd())
        self._clock = clock
        self._ttl = timedelta(seconds=plan_ttl_seconds)
        self._plans: dict[str, _StoredPlan] = {}
        self._lock = threading.Lock()
        self._write_locks: dict[tuple[UUID, str], threading.Lock] = {}

    def _workspace(self, workspace_id: UUID, *, needs_feature: bool) -> WorkspaceInfo:
        info = self._workspaces(workspace_id)
        if info is None:
            raise _error(
                LocalErrorCode.WORKSPACE_CONFIG_MISSING,
                "This workspace is not configured on this machine.",
                "workspace_unknown",
            )
        if needs_feature and not info.harness_enabled:
            raise _error(
                LocalErrorCode.FEATURE_DISABLED,
                "Harness integrations are not enabled for this workspace.",
                "feature_disabled",
            )
        return info

    def _context(self, info: WorkspaceInfo) -> HarnessContext:
        return HarnessContext(
            workspace_root=info.root,
            mcp_url=info.mcp_url,
            env=self._env(),
            probe_cwd=self._probe_cwd,
        )

    def _adapter(self, adapter_id: str) -> HarnessAdapter:
        adapter = self._registry.get(adapter_id)
        if adapter is None:
            raise _error(
                LocalErrorCode.INVALID_REQUEST, "Unknown harness adapter.", "adapter_unknown"
            )
        return adapter

    def _status(self, adapter: HarnessAdapter, detection: Detection) -> HarnessStatus:
        state, error = _map_state(detection)
        usable = state not in (HarnessState.NOT_DETECTED, HarnessState.INCOMPATIBLE)
        return HarnessStatus(
            adapter_id=adapter.adapter_id,
            harness_id=adapter.harness_id,
            display_name=adapter.display_name,
            state=state,
            detected_version=detection.version if state is not HarnessState.NOT_DETECTED else None,
            capabilities=list(adapter.capabilities) if usable else [],
            managed_files=list(detection.managed_files),
            error=error,
        )

    def detect(self, request: WorkspaceScope) -> HarnessDetectResult:
        info = self._workspace(request.workspace_id, needs_feature=False)
        detections = self._registry.detect_all(self._context(info))
        return HarnessDetectResult(
            harnesses=[self._status(adapter, detection) for adapter, detection in detections]
        )

    def status(self, request: HarnessStatusRequest) -> HarnessStatus:
        info = self._workspace(request.workspace_id, needs_feature=False)
        adapter = self._adapter(request.adapter_id)
        return self._status(adapter, adapter.detect(self._context(info)))

    def preview(self, request: HarnessPreviewRequest) -> HarnessPlan:
        info = self._workspace(request.workspace_id, needs_feature=True)
        adapter = self._adapter(request.adapter_id)
        ctx = self._context(info)
        try:
            edits = adapter.plan(ctx)
        except AdapterRefusal as refusal:
            raise _refusal_error(refusal.reason) from refusal
        changes = [_change(edit) for edit in edits]
        created = self._clock()
        plan = HarnessPlan(
            plan_id=f"plan-{uuid4().hex}",
            adapter_id=adapter.adapter_id,
            workspace_id=info.workspace_id,
            changes=changes,
            plan_hash=_plan_hash(info.workspace_id, adapter.adapter_id, changes),
            created_at=created,
            expires_at=created + self._ttl,
        )
        with self._lock:
            self._forget_expired()
            if len(self._plans) >= MAX_STORED_PLANS:
                oldest = min(self._plans, key=lambda key: self._plans[key].plan.created_at)
                del self._plans[oldest]
            self._plans[plan.plan_id] = _StoredPlan(plan, edits, ctx)
        return plan

    def _forget_expired(self) -> None:
        now = self._clock()
        for plan_id in [k for k, v in self._plans.items() if v.plan.expires_at <= now]:
            del self._plans[plan_id]

    def _write_lock(self, workspace_id: UUID, adapter_id: str) -> threading.Lock:
        with self._lock:
            return self._write_locks.setdefault((workspace_id, adapter_id), threading.Lock())

    def apply(self, request: HarnessApplyRequest) -> HarnessApplyResult:
        with self._lock:
            stored = self._plans.get(request.plan_id)
        if stored is None:
            raise _error(
                LocalErrorCode.PLAN_EXPIRED,
                "The plan is unknown or has expired; preview again.",
                "plan_unknown",
            )
        plan = stored.plan
        if plan.expires_at <= self._clock():
            with self._lock:
                self._plans.pop(plan.plan_id, None)
            raise _error(
                LocalErrorCode.PLAN_EXPIRED, "The plan has expired; preview again.", "plan_expired"
            )
        if request.plan_hash != plan.plan_hash:
            raise _error(
                LocalErrorCode.INVALID_REQUEST,
                "The confirmation does not match the previewed plan.",
                "plan_hash_mismatch",
            )
        info = self._workspace(plan.workspace_id, needs_feature=True)
        adapter = self._adapter(plan.adapter_id)
        ctx = self._context(info)
        with self._write_lock(plan.workspace_id, plan.adapter_id):
            with self._lock:
                self._plans.pop(plan.plan_id, None)
            if not stored.edits:
                return HarnessApplyResult(
                    plan_id=plan.plan_id,
                    state=_map_state(adapter.detect(ctx))[0],
                )
            return self._apply_edits(plan, stored, adapter, ctx)

    def _apply_edits(
        self,
        plan: HarnessPlan,
        stored: _StoredPlan,
        adapter: HarnessAdapter,
        ctx: HarnessContext,
    ) -> HarnessApplyResult:
        root = ctx.workspace_root
        paths: list[Path] = []
        try:
            for edit, change in zip(stored.edits, plan.changes, strict=True):
                path = resolve_target(root, edit.target)
                current = read_document(path)
                if (None if current is None else current.sha256) != change.before_hash:
                    raise _error(
                        LocalErrorCode.INVALID_REQUEST,
                        "The file changed after the preview; preview again.",
                        "changed_since_preview",
                    )
                paths.append(path)
        except FsError as error:
            raise _refusal_error(error.reason) from error
        rollback_id = f"rb-{uuid4().hex}"
        try:
            record = self._backups.begin(
                rollback_id,
                plan.workspace_id,
                plan.adapter_id,
                [
                    (
                        change.change_id,
                        edit.target,
                        edit.kind.value,
                        None if edit.before is None else edit.before.raw,
                        change.after_hash,
                    )
                    for edit, change in zip(stored.edits, plan.changes, strict=True)
                ],
            )
        except BackupError as error:
            raise _refusal_error("backup_failed") from error
        written: list[int] = []
        try:
            for index, (edit, path) in enumerate(zip(stored.edits, paths, strict=True)):
                atomic_write(path, edit.after)
                written.append(index)
                landed = read_document(path)
                if landed is None or landed.sha256 != edit.after_hash:
                    raise FsError("verify_failed", "the written file does not match the plan")
            state = _map_state(adapter.detect(ctx))[0]
            if state is not HarnessState.CONFIGURED:
                raise FsError("verify_failed", "the harness does not see the configuration")
        except FsError as error:
            if not self._restore(record, paths, written):
                self._backups.mark_applied(record)
                raise _error(
                    LocalErrorCode.INTERNAL_ERROR,
                    "The change could not be verified and the original could not be restored.",
                    "restore_failed",
                ) from error
            self._backups.mark_failed(record)
            raise _refusal_error(error.reason) from error
        self._backups.mark_applied(record)
        return HarnessApplyResult(
            plan_id=plan.plan_id,
            applied=[change.change_id for change in plan.changes],
            rollback_id=rollback_id,
            state=state,
        )

    def _restore(self, record: BackupRecord, paths: list[Path], written: list[int]) -> bool:
        restored = True
        for index in reversed(written):
            entry = record.entries[index]
            try:
                if entry.backup_file is None:
                    remove_file(paths[index])
                else:
                    atomic_write(paths[index], self._backups.read_backup(record, entry))
            except (FsError, BackupError):
                restored = False
        return restored

    def rollback(self, request: HarnessRollbackRequest) -> HarnessRollbackResult:
        record = self._find_record(request.rollback_id)
        info = self._workspace(record.workspace_id, needs_feature=True)
        adapter = self._adapter(record.adapter_id)
        ctx = self._context(info)
        with self._write_lock(record.workspace_id, record.adapter_id):
            if self._backups.is_rolled_back(record):
                raise _error(
                    LocalErrorCode.INVALID_REQUEST,
                    "This change was already rolled back.",
                    "already_rolled_back",
                )
            if not self._backups.is_applied(record):
                raise _error(
                    LocalErrorCode.INVALID_REQUEST,
                    "This change was never applied.",
                    "not_applied",
                )
            actions: list[tuple[Path, bytes | None, str, bool]] = []
            try:
                for entry in record.entries:
                    path = resolve_target(info.root, entry.target)
                    current = read_document(path)
                    current_hash = None if current is None else current.sha256
                    if current_hash == entry.after_hash:
                        original = (
                            None
                            if entry.backup_file is None
                            else self._backups.read_backup(record, entry)
                        )
                        actions.append((path, original, entry.change_id, True))
                    elif current_hash == entry.before_hash:
                        actions.append((path, None, entry.change_id, False))
                    else:
                        raise _error(
                            LocalErrorCode.INVALID_REQUEST,
                            "The file changed after the apply; nothing was restored.",
                            "rollback_conflict",
                        )
            except FsError as error:
                raise _refusal_error(error.reason) from error
            except BackupError as error:
                raise _refusal_error(error.reason) from error
            restored: list[str] = []
            try:
                for path, original, change_id, needs_write in actions:
                    if needs_write:
                        if original is None:
                            remove_file(path)
                        else:
                            atomic_write(path, original)
                    restored.append(change_id)
            except FsError as error:
                raise _refusal_error(error.reason) from error
            self._backups.mark_rolled_back(record)
        return HarnessRollbackResult(
            rollback_id=record.rollback_id,
            restored=restored,
            state=_map_state(adapter.detect(ctx))[0],
        )

    def verify(self, request: HarnessVerifyRequest) -> HarnessVerifyResult:
        info = self._workspace(request.workspace_id, needs_feature=True)
        adapter = self._adapter(request.adapter_id)
        ctx = self._context(info)
        detection = adapter.detect(ctx)
        if detection.state is not DetectionState.CONFIGURED:
            return HarnessVerifyResult(
                adapter_id=adapter.adapter_id,
                state=VerifyState.UNCONFIGURED
                if detection.state is DetectionState.CONFIGURATION_MISSING
                else VerifyState.FAILED,
                mcp_url=None,
                error=None,
                details={"detection_state": detection.state.value},
            )
        # The harness is CONFIGURED - now test the actual MCP connection
        # We need to verify that the MCP server can be reached and authenticated
        # This requires the STUDIO_MCP_MACHINE_TOKEN to be available in the environment
        token = ctx.env_value("STUDIO_MCP_MACHINE_TOKEN")
        if not token:
            return HarnessVerifyResult(
                adapter_id=adapter.adapter_id,
                state=VerifyState.CONFIGURED,
                mcp_url=info.mcp_url,
                error=None,
                details={"reason": "token_missing"},
            )
        # Try to make a real MCP call to verify the connection
        # Use streamable-http transport: initialize -> get session -> tools/call
        # This proves the full chain: harness config -> MCP URL -> auth -> Studi'OS
        try:
            import asyncio

            import httpx
            
            async def test_mcp_call() -> tuple[bool, str | None]:
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                }
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        # Step 1: Initialize to get session ID
                        init_payload = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2024-11-05",
                                "capabilities": {},
                                "clientInfo": {"name": "studio-verify", "version": "1.0"}
                            }
                        }
                        init_response = await client.post(info.mcp_url, json=init_payload, headers=headers)
                        if init_response.status_code != 200:
                            return False, f"Initialize failed: HTTP {init_response.status_code}: {init_response.text[:200]}"
                        
                        # Extract session ID from response header
                        session_id = init_response.headers.get("mcp-session-id")
                        if not session_id:
                            # Try to parse from event stream
                            for line in init_response.text.splitlines():
                                if line.startswith("data: "):
                                    import json
                                    try:
                                        data = json.loads(line[6:])
                                        if "result" in data and "sessionId" in data.get("result", {}):
                                            session_id = data["result"]["sessionId"]
                                            break
                                    except Exception:
                                        pass
                        
                        if not session_id:
                            return False, "No session ID returned from initialize"
                        
                        # Step 2: Call a tool with the session ID
                        headers["Mcp-Session-Id"] = session_id
                        tool_payload = {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/call",
                            "params": {
                                "name": "studio_get_projects",
                                "arguments": {}
                            }
                        }
                        tool_response = await client.post(info.mcp_url, json=tool_payload, headers=headers)
                        if tool_response.status_code != 200:
                            return False, f"Tool call failed: HTTP {tool_response.status_code}: {tool_response.text[:200]}"
                        
                        # Parse event stream response - check for actual success
                        # The MCP server may return 200 with a result that contains an error in the content
                        success = False
                        error_msg = None
                        for line in tool_response.text.splitlines():
                            if line.startswith("data: "):
                                import json
                                try:
                                    data = json.loads(line[6:])
                                    if "error" in data and data["error"]:
                                        # JSON-RPC error returned
                                        err = data["error"]
                                        return False, (
                                            f"MCP error: {err.get('message', 'unknown')} "
                                            f"(code: {err.get('code', 'unknown')})"
                                        )
                                    if "result" in data:
                                        result = data["result"]
                                        # Check if result indicates an error
                                        # (isError=true or error_code in structuredContent)
                                        if result.get("isError") is True:
                                            error_msg = result.get("content", [{}])[0].get(
                                                "text", "Unknown error"
                                            )
                                            break
                                        structured = result.get("structuredContent", {})
                                        if isinstance(structured, dict) and "error_code" in structured:
                                            error_msg = structured.get(
                                                "message", structured.get("error_code", "Unknown error")
                                            )
                                            break
                                        success = True
                                except Exception:
                                    pass
                        if error_msg:
                            return False, f"Tool returned error: {error_msg}"
                        if success:
                            return True, None
                        return False, f"Tool call returned no result: {tool_response.text[:200]}"
                except Exception as e:
                    return False, str(e)
            
            success, error_msg = asyncio.run(test_mcp_call())
            if success:
                return HarnessVerifyResult(
                    adapter_id=adapter.adapter_id,
                    state=VerifyState.VERIFIED,
                    mcp_url=info.mcp_url,
                    error=None,
                    details={"method": "studio_get_projects"},
                )
            else:
                return HarnessVerifyResult(
                    adapter_id=adapter.adapter_id,
                    state=VerifyState.FAILED,
                    mcp_url=info.mcp_url,
                    error=LocalError(
                        code=LocalErrorCode.INTERNAL_ERROR,
                        message=f"MCP verification failed: {error_msg}",
                        component=ComponentId.HARNESS,
                        retryable=True,
                    ),
                    details={"reason": "mcp_call_failed"},
                )
        except Exception as e:
            return HarnessVerifyResult(
                adapter_id=adapter.adapter_id,
                state=VerifyState.FAILED,
                mcp_url=info.mcp_url,
                error=LocalError(
                    code=LocalErrorCode.INTERNAL_ERROR,
                    message=f"Verification error: {str(e)[:200]}",
                    component=ComponentId.HARNESS,
                    retryable=True,
                ),
                details={"reason": "verification_exception"},
            )

    def _find_record(self, rollback_id: str) -> BackupRecord:
        record: BackupRecord | None = None
        if rollback_id.startswith(_LATEST_PREFIX):
            parts = rollback_id.split(":", 2)
            try:
                workspace_id = UUID(parts[1])
                adapter_id = parts[2]
                self._adapter(adapter_id)
                record = self._backups.latest_applied(workspace_id, adapter_id)
            except (ValueError, IndexError, BackupError):
                record = None
        else:
            record = self._backups.find(rollback_id)
        if record is None:
            raise _error(
                LocalErrorCode.INVALID_REQUEST,
                "There is no change to roll back.",
                "rollback_unknown",
            )
        return record


def latest_rollback_id(workspace_id: UUID, adapter_id: str) -> str:
    return f"{_LATEST_PREFIX}{workspace_id}:{adapter_id}"


def _neutral_cwd() -> str:
    import tempfile

    return tempfile.gettempdir()


def _change(edit: PlannedEdit) -> HarnessChange:
    digest = hashlib.sha256(f"{edit.target}:{edit.after_hash}".encode()).hexdigest()[:16]
    return HarnessChange(
        change_id=f"chg-{digest}",
        kind=edit.kind,
        target=edit.target,
        summary=edit.summary,
        before_hash=edit.before_hash,
        after_hash=edit.after_hash,
    )


def _plan_hash(workspace_id: UUID, adapter_id: str, changes: list[HarnessChange]) -> str:
    body = json.dumps(
        [str(workspace_id), adapter_id, [c.model_dump(mode="json") for c in changes]],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()


def _map_state(detection: Detection) -> tuple[HarnessState, LocalError | None]:
    reason = detection.reason or detection.state.value
    match detection.state:
        case DetectionState.NOT_INSTALLED:
            return HarnessState.NOT_DETECTED, _local_error(
                LocalErrorCode.PROVIDER_NOT_INSTALLED, reason
            )
        case DetectionState.INCOMPATIBLE:
            return HarnessState.INCOMPATIBLE, _local_error(
                LocalErrorCode.PROVIDER_INCOMPATIBLE, reason
            )
        case DetectionState.CONFIGURED:
            return HarnessState.CONFIGURED, None
        case DetectionState.CONFIGURATION_MISSING:
            return HarnessState.DETECTED, None
        case DetectionState.CONFIGURATION_INVALID:
            return HarnessState.ERROR, _local_error(LocalErrorCode.WORKSPACE_CONFIG_INVALID, reason)
        case DetectionState.UNAVAILABLE:
            code = _REFUSAL_CODES.get(reason, LocalErrorCode.INTERNAL_ERROR)
            return HarnessState.ERROR, _local_error(code, reason)
    raise AssertionError("unreachable")


__all__ = [
    "HarnessService",
    "HarnessServiceError",
    "WorkspaceInfo",
    "latest_rollback_id",
]
