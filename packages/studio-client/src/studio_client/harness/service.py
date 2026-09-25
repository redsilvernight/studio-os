"""Detect, preview, apply and roll back harness configuration.

The bridge-facing service. It speaks only the `harness.*` contract models and
the vendor-neutral adapter interface; it knows no file name, format or CLI.
Preview never writes. Apply is bound to a previewed plan, backs up first,
writes atomically, verifies, and restores on failure. Rollback refuses to
overwrite anything the user changed after the apply.

Each tool gets its own Studi'OS machine (DEC-0104 §2): apply creates it, writes
its credential into the tool's user configuration — the only place it is ever
stored — and revokes the machine it replaces; rollback removes the entry and
revokes the machine. Plans, backups, results, errors and logs only ever see the
redacted entry.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from studio_contracts.local.common import ComponentId, LocalError, LocalErrorCode
from studio_contracts.local.harness import (
    ChangeScope,
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

from studio_client.harness import jsonc
from studio_client.harness.backup import (
    BackupEntry,
    BackupError,
    BackupItem,
    BackupRecord,
    BackupStore,
)
from studio_client.harness.base import (
    AdapterPlan,
    AdapterRefusal,
    Detection,
    DetectionState,
    HarnessAdapter,
    HarnessContext,
    PlannedEdit,
    UserEntryEdit,
    system_env,
)
from studio_client.harness.credentials import (
    CredentialProvisioner,
    CredentialStore,
    ProvisionError,
    ToolCredential,
    retry_pending,
    revoke_or_defer,
    tool_display_name,
    utc_now_iso,
)
from studio_client.harness.fsafe import (
    FsError,
    atomic_write,
    read_document,
    remove_file,
    resolve_target,
)
from studio_client.harness.redaction import bearer_token, fingerprint, redacted_hash
from studio_client.harness.registry import HarnessRegistry

PLAN_TTL_SECONDS = 600
MAX_STORED_PLANS = 64
MCP_VERIFY_TIMEOUT_SECONDS = 15.0
_LATEST_PREFIX = "latest:"
_UNMANAGED = "unmanaged_credential"
_TOKEN_REFERENCE = "token_reference"


@dataclass(frozen=True)
class WorkspaceInfo:
    """What the service needs to know about a workspace, supplied by the daemon
    from its own registry."""

    workspace_id: UUID
    root: Path
    mcp_url: str
    harness_enabled: bool
    server_origin: str | None = None

    @property
    def origin(self) -> str:
        if self.server_origin:
            return self.server_origin.rstrip("/")
        parts = urlsplit(self.mcp_url)
        return f"{parts.scheme}://{parts.netloc}"


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
    "unsupported_launcher": LocalErrorCode.PROVIDER_INCOMPATIBLE,
    "permission_denied": LocalErrorCode.PERMISSION_DENIED,
    "read_only": LocalErrorCode.PERMISSION_DENIED,
    "timeout": LocalErrorCode.TIMEOUT,
    "cli_timeout": LocalErrorCode.TIMEOUT,
    "probe_failed": LocalErrorCode.INTERNAL_ERROR,
    "unexpected_output": LocalErrorCode.INTERNAL_ERROR,
    "not_executable": LocalErrorCode.INTERNAL_ERROR,
    "cli_failed": LocalErrorCode.INTERNAL_ERROR,
    "cli_not_executable": LocalErrorCode.INTERNAL_ERROR,
    "cli_permission_denied": LocalErrorCode.PERMISSION_DENIED,
    "write_failed": LocalErrorCode.INTERNAL_ERROR,
    "workspace_inaccessible": LocalErrorCode.WORKSPACE_INACCESSIBLE,
    "io_error": LocalErrorCode.INTERNAL_ERROR,
    "backup_failed": LocalErrorCode.INTERNAL_ERROR,
    "ledger_unwritable": LocalErrorCode.INTERNAL_ERROR,
    "credential_forbidden": LocalErrorCode.PERMISSION_DENIED,
    "desktop_unauthenticated": LocalErrorCode.SECRET_REVOKED,
    "credential_server_error": LocalErrorCode.INTERNAL_ERROR,
    "credential_unreachable": LocalErrorCode.INTERNAL_ERROR,
}
_RETRYABLE = frozenset({"credential_server_error", "credential_unreachable", "cli_timeout"})
_MESSAGES: dict[LocalErrorCode, str] = {
    LocalErrorCode.PROVIDER_NOT_INSTALLED: "This harness is not installed on this machine.",
    LocalErrorCode.PROVIDER_INCOMPATIBLE: "This harness version is not supported.",
    LocalErrorCode.PERMISSION_DENIED: "The harness configuration cannot be written here.",
    LocalErrorCode.TIMEOUT: "The harness did not answer in time.",
    LocalErrorCode.INTERNAL_ERROR: "The harness could not be inspected or changed.",
    LocalErrorCode.WORKSPACE_INACCESSIBLE: "The workspace is not accessible.",
    LocalErrorCode.WORKSPACE_CONFIG_INVALID: "The harness configuration is not valid.",
    LocalErrorCode.SECRET_REVOKED: "This Desktop is no longer signed in to Studi'OS.",
}


def _refusal_error(reason: str) -> HarnessServiceError:
    code = _REFUSAL_CODES.get(reason, LocalErrorCode.WORKSPACE_CONFIG_INVALID)
    return _error(code, _MESSAGES[code], reason, retryable=reason in _RETRYABLE)


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
    adapter_plan: AdapterPlan
    ctx: HarnessContext
    origin: str


class _ApplyFailure(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


McpProbe = Callable[[str, str], tuple[str | None, int | None]]
"""(mcp_url, credential) -> (failure reason | None, HTTP status | None)."""


class HarnessService:
    def __init__(
        self,
        registry: HarnessRegistry,
        backups: BackupStore,
        workspaces: WorkspaceLookup,
        *,
        credentials: CredentialStore,
        provisioner: CredentialProvisioner,
        env: Callable[[], Mapping[str, str]] = system_env,
        home: Callable[[], Path] = Path.home,
        probe_cwd: Path | None = None,
        clock: Callable[[], datetime] = _now,
        plan_ttl_seconds: int = PLAN_TTL_SECONDS,
        mcp_probe: McpProbe | None = None,
        host_name: Callable[[str], str] = tool_display_name,
    ) -> None:
        self._registry = registry
        self._backups = backups
        self._workspaces = workspaces
        self._credentials = credentials
        self._provisioner = provisioner
        self._env = env
        self._home = home
        self._probe_cwd = probe_cwd or Path(_neutral_cwd())
        self._clock = clock
        self._ttl = timedelta(seconds=plan_ttl_seconds)
        self._mcp_probe = mcp_probe or probe_mcp
        self._display_name = host_name
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
            home=self._home(),
        )

    def _adapter(self, adapter_id: str) -> HarnessAdapter:
        adapter = self._registry.get(adapter_id)
        if adapter is None:
            raise _error(
                LocalErrorCode.INVALID_REQUEST, "Unknown harness adapter.", "adapter_unknown"
            )
        return adapter

    def _managed(self, adapter: HarnessAdapter, detection: Detection, origin: str) -> Detection:
        """A configured entry only counts when its credential is the one this
        Desktop provisioned for the tool; any other is replaced on apply."""
        if detection.state is not DetectionState.CONFIGURED:
            return detection
        record = self._credentials.get(adapter.adapter_id, origin)
        if record is not None and record.credential_sha256 == detection.credential_fingerprint:
            return detection
        return Detection(DetectionState.CONFIGURATION_MISSING, detection.version, _UNMANAGED)

    def _detect(self, adapter: HarnessAdapter, ctx: HarnessContext, origin: str) -> Detection:
        return self._managed(adapter, adapter.detect(ctx), origin)

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
            managed_files=list(detection.managed_files) if state is HarnessState.CONFIGURED else [],
            error=error,
        )

    def _retry_revocations(self) -> None:
        with contextlib.suppress(ProvisionError):
            retry_pending(self._provisioner, self._credentials)

    def detect(self, request: WorkspaceScope) -> HarnessDetectResult:
        info = self._workspace(request.workspace_id, needs_feature=False)
        detections = self._registry.detect_all(self._context(info))
        return HarnessDetectResult(
            harnesses=[
                self._status(adapter, self._managed(adapter, detection, info.origin))
                for adapter, detection in detections
            ]
        )

    def status(self, request: HarnessStatusRequest) -> HarnessStatus:
        info = self._workspace(request.workspace_id, needs_feature=False)
        adapter = self._adapter(request.adapter_id)
        return self._status(adapter, self._detect(adapter, self._context(info), info.origin))

    def preview(self, request: HarnessPreviewRequest) -> HarnessPlan:
        info = self._workspace(request.workspace_id, needs_feature=True)
        adapter = self._adapter(request.adapter_id)
        ctx = self._context(info)
        self._retry_revocations()
        renew = request.renew or self._detect(adapter, ctx, info.origin).reason == _UNMANAGED
        try:
            adapter_plan = adapter.plan(ctx, renew=renew)
        except AdapterRefusal as refusal:
            raise _refusal_error(refusal.reason) from None
        changes = _changes(adapter_plan)
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
            self._plans[plan.plan_id] = _StoredPlan(plan, adapter_plan, ctx, info.origin)
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
            self._retry_revocations()
            if stored.adapter_plan.empty:
                return HarnessApplyResult(
                    plan_id=plan.plan_id,
                    state=_map_state(self._detect(adapter, ctx, info.origin))[0],
                )
            return self._apply_plan(plan, stored, adapter, ctx, info.origin)

    def _read_user_entry(
        self, adapter: HarnessAdapter, ctx: HarnessContext
    ) -> dict[str, Any] | None:
        try:
            return adapter.read_user_entry(ctx)
        except AdapterRefusal as refusal:
            raise _refusal_error(refusal.reason) from None
        except FsError as error:
            raise _refusal_error(error.reason) from None
        except jsonc.JsoncError as error:
            raise _refusal_error(error.code) from None

    def _apply_plan(
        self,
        plan: HarnessPlan,
        stored: _StoredPlan,
        adapter: HarnessAdapter,
        ctx: HarnessContext,
        origin: str,
    ) -> HarnessApplyResult:
        adapter_plan = stored.adapter_plan
        user_edit = adapter_plan.user_entry
        edits = adapter_plan.workspace_edits
        user_change, workspace_changes = _split_changes(plan.changes, user_edit)
        changed = _error(
            LocalErrorCode.INVALID_REQUEST,
            "The configuration changed after the preview; preview again.",
            "changed_since_preview",
        )
        paths: list[Path] = []
        try:
            for edit in edits:
                path = resolve_target(ctx.workspace_root, edit.target)
                current = read_document(path)
                if (None if current is None else current.sha256) != edit.before_hash:
                    raise changed
                paths.append(path)
        except FsError as error:
            raise _refusal_error(error.reason) from None
        previous: dict[str, Any] | None = None
        if user_edit is not None:
            previous = self._read_user_entry(adapter, ctx)
            current_hash = None if previous is None else redacted_hash(previous)
            if current_hash != user_edit.before_hash:
                raise changed
        items: list[BackupItem] = []
        if user_edit is not None and user_change is not None:
            items.append(
                BackupItem(
                    change_id=user_change.change_id,
                    target=user_edit.target,
                    kind=user_edit.kind.value,
                    original=user_edit.before if user_edit.restorable else None,
                    after_hash=user_edit.after_hash,
                    scope=ChangeScope.USER.value,
                    restorable=user_edit.restorable,
                    before_hash=user_edit.before_hash,
                )
            )
        items.extend(
            BackupItem(
                change_id=change.change_id,
                target=edit.target,
                kind=edit.kind.value,
                original=None if edit.before is None else edit.before.raw,
                after_hash=change.after_hash,
            )
            for edit, change in zip(edits, workspace_changes, strict=True)
        )
        rollback_id = f"rb-{uuid4().hex}"
        try:
            record = self._backups.begin(rollback_id, plan.workspace_id, plan.adapter_id, items)
        except BackupError:
            raise _refusal_error("backup_failed") from None
        old = self._credentials.get(adapter.adapter_id, origin)
        new: ToolCredential | None = None
        written: list[int] = []
        user_touched = False
        try:
            token: str | None = None
            if user_edit is not None:
                machine_id, token = self._create_machine(adapter, origin)
                new = ToolCredential(
                    adapter_id=adapter.adapter_id,
                    origin=origin,
                    machine_id=machine_id,
                    display_name=self._display_name(adapter.display_name),
                    credential_sha256=fingerprint(token),
                    created_at=utc_now_iso(),
                )
            for index, (edit, path) in enumerate(zip(edits, paths, strict=True)):
                atomic_write(path, edit.after)
                written.append(index)
                landed = read_document(path)
                if landed is None or landed.sha256 != edit.after_hash:
                    raise _ApplyFailure("verify_failed")
            if user_edit is not None and token is not None and new is not None:
                user_touched = True
                adapter.write_user_entry(ctx, adapter.build_entry(ctx.mcp_url, token))
                landed_entry = adapter.read_user_entry(ctx)
                if (
                    landed_entry is None
                    or redacted_hash(landed_entry) != user_edit.after_hash
                    or bearer_token(landed_entry) != token
                ):
                    raise _ApplyFailure("verify_failed")
                self._credentials.set(new)
            token = None
            state = _map_state(self._detect(adapter, ctx, origin))[0]
            if state is not HarnessState.CONFIGURED:
                raise _ApplyFailure("verify_failed")
        except (_ApplyFailure, AdapterRefusal, ProvisionError, FsError, jsonc.JsoncError) as error:
            reason = _failure_reason(error)
            restored = self._undo(
                adapter, ctx, record, paths, written, user_touched, previous, old, new, origin
            )
            if not restored:
                self._backups.mark_applied(record)
                raise _error(
                    LocalErrorCode.INTERNAL_ERROR,
                    "The change could not be verified and the original could not be restored.",
                    "restore_failed",
                ) from None
            self._backups.mark_failed(record)
            raise _refusal_error(reason) from None
        if new is not None and old is not None and old.machine_id != new.machine_id:
            revoke_or_defer(self._provisioner, self._credentials, old.origin, old.machine_id)
        if new is not None:
            record.machine_id = new.machine_id
            record.credential_sha256 = new.credential_sha256
        self._backups.mark_applied(record)
        return HarnessApplyResult(
            plan_id=plan.plan_id,
            applied=[change.change_id for change in plan.changes],
            rollback_id=rollback_id,
            state=state,
        )

    def _create_machine(self, adapter: HarnessAdapter, origin: str) -> tuple[str, str]:
        machine_id, token = self._provisioner.create(
            origin, self._display_name(adapter.display_name)
        )
        try:
            # Remembered before the credential is written anywhere: a crash
            # from here on leaves a revocation to retry, not an orphan machine.
            self._credentials.add_pending(origin, machine_id)
        except ProvisionError:
            with contextlib.suppress(ProvisionError):
                self._provisioner.revoke(origin, machine_id)
            raise
        return machine_id, token

    def _undo(
        self,
        adapter: HarnessAdapter,
        ctx: HarnessContext,
        record: BackupRecord,
        paths: list[Path],
        written: list[int],
        user_touched: bool,
        previous: dict[str, Any] | None,
        old: ToolCredential | None,
        new: ToolCredential | None,
        origin: str,
    ) -> bool:
        restored = True
        if user_touched:
            try:
                if previous is None:
                    adapter.remove_user_entry(ctx)
                else:
                    adapter.write_user_entry(ctx, previous)
            except (AdapterRefusal, FsError, jsonc.JsoncError):
                restored = False
        workspace_entries = [entry for entry in record.entries if entry.scope != "user"]
        for index in reversed(written):
            entry = workspace_entries[index]
            try:
                if entry.backup_file is None:
                    remove_file(paths[index])
                else:
                    atomic_write(paths[index], self._backups.read_backup(record, entry))
            except (FsError, BackupError):
                restored = False
        if new is not None:
            with contextlib.suppress(ProvisionError):
                if old is not None:
                    self._credentials.set(old)
                else:
                    self._credentials.forget(new.adapter_id, origin, new.machine_id)
            revoke_or_defer(self._provisioner, self._credentials, origin, new.machine_id)
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
            conflict = _error(
                LocalErrorCode.INVALID_REQUEST,
                "The configuration changed after the apply; nothing was restored.",
                "rollback_conflict",
            )
            file_actions: list[tuple[Path, bytes | None, str, bool]] = []
            user_action: tuple[BackupEntry, dict[str, Any] | None, bool] | None = None
            try:
                for entry in record.entries:
                    if entry.scope == ChangeScope.USER.value:
                        user_action = self._plan_user_rollback(adapter, ctx, record, entry)
                        if user_action is None:
                            raise conflict
                        continue
                    path = resolve_target(info.root, entry.target)
                    current = read_document(path)
                    current_hash = None if current is None else current.sha256
                    if current_hash == entry.after_hash:
                        original = (
                            None
                            if entry.backup_file is None
                            else self._backups.read_backup(record, entry)
                        )
                        file_actions.append((path, original, entry.change_id, True))
                    elif current_hash == entry.before_hash:
                        file_actions.append((path, None, entry.change_id, False))
                    else:
                        raise conflict
            except FsError as error:
                raise _refusal_error(error.reason) from None
            except BackupError as error:
                raise _refusal_error(error.reason) from None
            restored: list[str] = []
            try:
                if user_action is not None:
                    entry, user_original, needs_write = user_action
                    if needs_write:
                        if user_original is None:
                            adapter.remove_user_entry(ctx)
                        else:
                            adapter.write_user_entry(ctx, user_original)
                    restored.append(entry.change_id)
                for path, data, change_id, needs_write in file_actions:
                    if needs_write:
                        if data is None:
                            remove_file(path)
                        else:
                            atomic_write(path, data)
                    restored.append(change_id)
            except AdapterRefusal as refusal:
                raise _refusal_error(refusal.reason) from None
            except FsError as error:
                raise _refusal_error(error.reason) from None
            if record.machine_id is not None:
                with contextlib.suppress(ProvisionError):
                    self._credentials.forget(adapter.adapter_id, info.origin, record.machine_id)
                revoke_or_defer(
                    self._provisioner, self._credentials, info.origin, record.machine_id
                )
            self._backups.mark_rolled_back(record)
        return HarnessRollbackResult(
            rollback_id=record.rollback_id,
            restored=restored,
            state=_map_state(self._detect(adapter, ctx, info.origin))[0],
        )

    def _plan_user_rollback(
        self,
        adapter: HarnessAdapter,
        ctx: HarnessContext,
        record: BackupRecord,
        entry: BackupEntry,
    ) -> tuple[BackupEntry, dict[str, Any] | None, bool] | None:
        """(entry, what to put back, whether to write) — None on a conflict.
        Redacted hashes cannot tell two credentials apart, so the entry is only
        ours when it also carries the credential this apply provisioned."""
        current = self._read_user_entry(adapter, ctx)
        current_hash = None if current is None else redacted_hash(current)
        token = bearer_token(current)
        ours = token is not None and fingerprint(token) == record.credential_sha256
        if current_hash == entry.after_hash and ours:
            original: dict[str, Any] | None = None
            if entry.restorable and entry.backup_file is not None:
                try:
                    original = json.loads(self._backups.read_backup(record, entry))
                except ValueError:
                    raise _refusal_error("backup_corrupt") from None
            return entry, original, True
        if current_hash == entry.before_hash and not ours:
            return entry, None, False
        return None

    def verify(self, request: HarnessVerifyRequest) -> HarnessVerifyResult:
        info = self._workspace(request.workspace_id, needs_feature=True)
        adapter = self._adapter(request.adapter_id)
        ctx = self._context(info)
        detection = adapter.detect(ctx)
        if detection.state is not DetectionState.CONFIGURED:
            if detection.reason == _TOKEN_REFERENCE:
                return HarnessVerifyResult(
                    adapter_id=adapter.adapter_id,
                    state=VerifyState.TOKEN_MISSING,
                    mcp_url=info.mcp_url,
                    details={"reason": _TOKEN_REFERENCE},
                )
            return HarnessVerifyResult(
                adapter_id=adapter.adapter_id,
                state=VerifyState.UNCONFIGURED
                if detection.state is DetectionState.CONFIGURATION_MISSING
                else VerifyState.FAILED,
                error=None
                if detection.state is DetectionState.CONFIGURATION_MISSING
                else _map_state(detection)[1]
                or _local_error(LocalErrorCode.INTERNAL_ERROR, detection.state.value),
                details={"detection_state": detection.state.value},
            )
        try:
            token = bearer_token(adapter.read_user_entry(ctx))
        except (AdapterRefusal, FsError, jsonc.JsoncError):
            token = None
        if token is None:
            return HarnessVerifyResult(
                adapter_id=adapter.adapter_id,
                state=VerifyState.TOKEN_MISSING,
                mcp_url=info.mcp_url,
                details={"reason": "token_missing"},
            )
        failure, status = self._mcp_probe(info.mcp_url, token)
        token = None
        if failure is None:
            return HarnessVerifyResult(
                adapter_id=adapter.adapter_id,
                state=VerifyState.VERIFIED,
                mcp_url=info.mcp_url,
                details={"method": "studio_get_projects"},
            )
        details = {"reason": failure}
        if status is not None:
            details["http_status"] = str(status)
        return HarnessVerifyResult(
            adapter_id=adapter.adapter_id,
            state=VerifyState.FAILED,
            mcp_url=info.mcp_url,
            error=LocalError(
                code=LocalErrorCode.INTERNAL_ERROR,
                message=_VERIFY_MESSAGES.get(failure, "Studi'OS could not be reached over MCP."),
                component=ComponentId.HARNESS,
                retryable=True,
                details={key: value for key, value in details.items()},
            ),
            details=details,
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


_VERIFY_MESSAGES: dict[str, str] = {
    "mcp_unauthorized": "Studi'OS refused the tool's credential.",
    "mcp_http_error": "Studi'OS answered the MCP call with an error status.",
    "mcp_no_session": "Studi'OS did not open an MCP session.",
    "mcp_tool_error": "The MCP test call returned an error.",
    "mcp_no_result": "The MCP test call returned no result.",
    "mcp_unreachable": "Studi'OS could not be reached over MCP.",
}


def _sse_messages(text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    lines = text.splitlines() if text.lstrip().startswith(("event:", "data:")) else []
    candidates = [line[len("data:") :].strip() for line in lines if line.startswith("data:")]
    if not lines:
        candidates = [text]
    for raw in candidates:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict):
            messages.append(data)
    return messages


def probe_mcp(mcp_url: str, token: str) -> tuple[str | None, int | None]:
    """One real MCP round trip (initialize, then a read-only tool call) with the
    tool's credential. Returns a stable failure token and the HTTP status only:
    no response body, exception text or header ever leaves this function."""
    import httpx

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "studio-verify", "version": "1.0"},
        },
    }
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "studio_get_projects", "arguments": {}},
    }
    try:
        with httpx.Client(timeout=MCP_VERIFY_TIMEOUT_SECONDS) as client:
            response = client.post(mcp_url, json=initialize, headers=headers)
            if response.status_code in (401, 403):
                return "mcp_unauthorized", response.status_code
            if response.status_code != 200:
                return "mcp_http_error", response.status_code
            session_id = response.headers.get("mcp-session-id")
            if not session_id:
                return "mcp_no_session", None
            headers["Mcp-Session-Id"] = session_id
            response = client.post(mcp_url, json=call, headers=headers)
            if response.status_code in (401, 403):
                return "mcp_unauthorized", response.status_code
            if response.status_code != 200:
                return "mcp_http_error", response.status_code
            succeeded = False
            for message in _sse_messages(response.text):
                if message.get("error"):
                    return "mcp_tool_error", None
                result = message.get("result")
                if not isinstance(result, dict):
                    continue
                structured = result.get("structuredContent")
                if result.get("isError") is True or (
                    isinstance(structured, dict) and "error_code" in structured
                ):
                    return "mcp_tool_error", None
                succeeded = True
            return (None, None) if succeeded else ("mcp_no_result", None)
    except Exception:  # noqa: BLE001 — the message could echo a header; keep only a token
        return "mcp_unreachable", None


def latest_rollback_id(workspace_id: UUID, adapter_id: str) -> str:
    return f"{_LATEST_PREFIX}{workspace_id}:{adapter_id}"


def _neutral_cwd() -> str:
    import tempfile

    return tempfile.gettempdir()


def _change_id(target: str, after_hash: str) -> str:
    return "chg-" + hashlib.sha256(f"{target}:{after_hash}".encode()).hexdigest()[:16]


def _changes(adapter_plan: AdapterPlan) -> list[HarnessChange]:
    changes: list[HarnessChange] = []
    user = adapter_plan.user_entry
    if user is not None:
        changes.append(
            HarnessChange(
                change_id=_change_id(f"~/{user.target}", user.after_hash),
                kind=user.kind,
                target=user.target,
                scope=ChangeScope.USER,
                summary=user.summary,
                before_hash=user.before_hash,
                after_hash=user.after_hash,
            )
        )
    changes.extend(_workspace_change(edit) for edit in adapter_plan.workspace_edits)
    return changes


def _workspace_change(edit: PlannedEdit) -> HarnessChange:
    return HarnessChange(
        change_id=_change_id(edit.target, edit.after_hash),
        kind=edit.kind,
        target=edit.target,
        summary=edit.summary,
        before_hash=edit.before_hash,
        after_hash=edit.after_hash,
    )


def _split_changes(
    changes: list[HarnessChange], user: UserEntryEdit | None
) -> tuple[HarnessChange | None, list[HarnessChange]]:
    if user is None:
        return None, list(changes)
    return changes[0], list(changes[1:])


def _failure_reason(error: BaseException) -> str:
    if isinstance(error, jsonc.JsoncError):
        return error.code
    reason = getattr(error, "reason", None)
    return reason if isinstance(reason, str) else "verify_failed"


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
    "probe_mcp",
]
