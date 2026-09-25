"""Shared mechanics for harnesses whose MCP servers live in JSON(C) files.

Vendor-neutral: a concrete adapter says which executable to probe, where its
user configuration keeps the Studi'OS entry and how to write it, and which
workspace files may still carry an older project-scoped entry. Probing,
fail-closed version policy, redaction, migration planning and verification
happen here once.

Studi'OS is declared in the tool's *user* configuration with a credential
dedicated to that tool (DEC-0104 §2). A project-scoped `studio-os` entry would
shadow it, so the plan removes it from the workspace file; one that holds a
literal secret is never touched and blocks the plan instead.
"""

from __future__ import annotations

import re
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any

from studio_contracts.local.harness import ChangeKind

from studio_client.harness import jsonc
from studio_client.harness.base import (
    STUDIO_MCP_SERVER_NAME,
    AdapterPlan,
    AdapterRefusal,
    Detection,
    DetectionState,
    HarnessAdapter,
    HarnessContext,
    PlannedEdit,
    UserEntryEdit,
)
from studio_client.harness.fsafe import (
    Document,
    FsError,
    encode_text,
    is_writable,
    read_document,
    resolve_target,
)
from studio_client.harness.probe import (
    ProbeFailure,
    extract_version,
    locate_executable,
    run_probe,
)
from studio_client.harness.redaction import (
    bearer_token,
    canonical,
    fingerprint,
    holds_secret,
    is_reference,
    redact,
)

_MAJOR = re.compile(r"^(\d+)\.")
_SAMPLE_TOKEN = "sample"  # noqa: S105 — only ever redacted


@dataclass(frozen=True)
class _ProjectEntry:
    target: str
    document: Document


@dataclass(frozen=True)
class _Inspection:
    detection: Detection
    project_entries: list[_ProjectEntry] = field(default_factory=list)
    user_entry: dict[str, Any] | None = field(default=None, repr=False)
    user_configured: bool = False


class JsonMcpAdapter(HarnessAdapter):
    executable_names: tuple[str, ...]
    version_args: tuple[str, ...] = ("--version",)
    identity: re.Pattern[str]
    supported_major: int
    project_files: tuple[str, ...]
    container_path: tuple[str, ...]
    comments: bool = False
    trailing_commas: bool = False

    @abstractmethod
    def user_target(self, ctx: HarnessContext) -> str:
        """The user configuration file, relative to `ctx.home` (POSIX)."""

    def local_override(self, ctx: HarnessContext) -> bool:
        """True when a per-workspace entry kept outside the workspace would
        shadow the user entry. Studi'OS never edits it: the user removes it."""
        return False

    @property
    def _entry_path(self) -> tuple[str, ...]:
        return (*self.container_path, STUDIO_MCP_SERVER_NAME)

    def expected_entry(self, mcp_url: str) -> dict[str, Any]:
        """The redacted entry Studi'OS writes: credential masked."""
        entry: dict[str, Any] = redact(self.build_entry(mcp_url, _SAMPLE_TOKEN))
        return entry

    def _version(self, ctx: HarnessContext) -> tuple[str | None, Detection | None]:
        executable = locate_executable(
            self.executable_names,
            path_env=ctx.env_value("PATH"),
            excluded_dirs=[ctx.workspace_root],
        )
        if executable is None:
            return None, Detection(DetectionState.NOT_INSTALLED, reason="executable_not_found")
        try:
            version = extract_version(
                run_probe(executable, self.version_args, env=ctx.env, cwd=ctx.probe_cwd),
                self.identity,
            )
        except ProbeFailure as failure:
            return None, Detection(DetectionState.UNAVAILABLE, reason=failure.reason)
        match = _MAJOR.match(version)
        if match is None or int(match.group(1)) != self.supported_major:
            return version, Detection(
                DetectionState.INCOMPATIBLE, version=version, reason="unsupported_version"
            )
        return version, None

    def _project_entries(self, ctx: HarnessContext) -> list[tuple[_ProjectEntry, Any]]:
        found: list[tuple[_ProjectEntry, Any]] = []
        for name in self.project_files:
            document = read_document(resolve_target(ctx.workspace_root, name))
            if document is None:
                continue
            root = jsonc.parse(
                document.text, comments=self.comments, trailing_commas=self.trailing_commas
            )
            if root.kind != "object":
                raise jsonc.JsoncError("unexpected_shape", "root is not an object")
            node = jsonc.lookup(root, self._entry_path)
            if node is not None:
                found.append((_ProjectEntry(name, document), jsonc.to_python(node)))
        return found

    def _missing_reason(self, ctx: HarnessContext, entry: Any) -> str:
        if isinstance(entry, dict) and entry.get("url") == ctx.mcp_url:
            headers = entry.get("headers")
            value = headers.get("Authorization") if isinstance(headers, dict) else None
            if isinstance(value, str) and is_reference(value):
                return "token_reference"
        return "entry_differs"

    def _inspect(self, ctx: HarnessContext) -> _Inspection:
        version, blocked = self._version(ctx)
        if blocked is not None:
            return _Inspection(blocked)

        def invalid(reason: str) -> _Inspection:
            return _Inspection(Detection(DetectionState.CONFIGURATION_INVALID, version, reason))

        try:
            project = self._project_entries(ctx)
        except FsError as error:
            return invalid(error.reason)
        except jsonc.JsoncError as error:
            return invalid(error.code)
        if any(holds_secret(value) for _, value in project):
            return invalid("project_entry_conflict")
        try:
            if self.local_override(ctx):
                return invalid("local_entry_conflict")
            user_entry = self.read_user_entry(ctx)
        except FsError as error:
            return invalid(error.reason)
        except jsonc.JsoncError as error:
            return invalid(error.code)
        except AdapterRefusal as refusal:
            return invalid(refusal.reason)
        entries = [entry for entry, _ in project]
        token = bearer_token(user_entry)
        configured = (
            user_entry is not None
            and token is not None
            and redact(user_entry) == self.expected_entry(ctx.mcp_url)
        )
        if configured and not entries:
            assert token is not None
            detection = Detection(
                DetectionState.CONFIGURED,
                version,
                managed_files=(self.user_target(ctx),),
                credential_fingerprint=fingerprint(token),
            )
        elif entries:
            detection = Detection(
                DetectionState.CONFIGURATION_MISSING, version, "project_entry_migration"
            )
        elif user_entry is None:
            detection = Detection(DetectionState.CONFIGURATION_MISSING, version)
        else:
            detection = Detection(
                DetectionState.CONFIGURATION_MISSING,
                version,
                self._missing_reason(ctx, user_entry),
            )
        return _Inspection(detection, entries, user_entry, configured)

    def detect(self, ctx: HarnessContext) -> Detection:
        try:
            return self._inspect(ctx).detection
        except FsError as error:
            return Detection(DetectionState.UNAVAILABLE, reason=error.reason)

    def _user_edit(self, ctx: HarnessContext, previous: dict[str, Any] | None) -> UserEntryEdit:
        after = canonical(self.expected_entry(ctx.mcp_url))
        if previous is None:
            return UserEntryEdit(
                target=self.user_target(ctx),
                kind=ChangeKind.CREATE,
                summary=(
                    f"Declare Studi'OS in {self.display_name}'s user configuration with "
                    "a credential dedicated to this tool."
                ),
                before=None,
                after=after,
                restorable=True,
            )
        restorable = not holds_secret(previous)
        summary = (
            f"Replace the studio-os entry of {self.display_name}'s user configuration "
            "with a new dedicated credential; every other setting is kept."
        )
        if not restorable:
            summary += " The replaced entry holds a credential and is not kept for rollback."
        return UserEntryEdit(
            target=self.user_target(ctx),
            kind=ChangeKind.MODIFY,
            summary=summary,
            before=canonical(redact(previous)),
            after=after,
            restorable=restorable,
        )

    def _removal(self, ctx: HarnessContext, entry: _ProjectEntry) -> PlannedEdit:
        document = entry.document
        try:
            if not is_writable(resolve_target(ctx.workspace_root, entry.target)):
                raise AdapterRefusal("read_only")
            text = jsonc.remove(
                document.text,
                self._entry_path,
                comments=self.comments,
                trailing_commas=self.trailing_commas,
            )
            jsonc.verify_removal(
                document.text,
                text,
                self._entry_path,
                comments=self.comments,
                trailing_commas=self.trailing_commas,
            )
            data = encode_text(text, bom=document.bom)
        except jsonc.JsoncError as error:
            raise AdapterRefusal(error.code) from None
        except FsError as error:
            raise AdapterRefusal(error.reason) from None
        return PlannedEdit(
            target=entry.target,
            kind=ChangeKind.MODIFY,
            summary=(
                "Remove the project-scoped studio-os entry: Studi'OS is now declared in "
                f"{self.display_name}'s user configuration. Every other setting is kept."
            ),
            before=document,
            after=data,
        )

    def plan(self, ctx: HarnessContext, *, renew: bool = False) -> AdapterPlan:
        try:
            inspection = self._inspect(ctx)
        except FsError as error:
            raise AdapterRefusal(error.reason) from None
        detection = inspection.detection
        if detection.state not in (
            DetectionState.CONFIGURED,
            DetectionState.CONFIGURATION_MISSING,
        ):
            raise AdapterRefusal(detection.reason or detection.state.value)
        user_edit = (
            None
            if inspection.user_configured and not renew
            else self._user_edit(ctx, inspection.user_entry)
        )
        removals = [self._removal(ctx, entry) for entry in inspection.project_entries]
        return AdapterPlan(user_entry=user_edit, workspace_edits=removals)
