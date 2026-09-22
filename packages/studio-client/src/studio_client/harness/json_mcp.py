"""Shared mechanics for harnesses whose MCP servers live in a JSON(C) file.

Vendor-neutral: a concrete adapter says which executable to probe, which file
and which path inside it hold the MCP entry, and what that entry looks like.
Everything else — probing, fail-closed version policy, non-destructive edit,
verification — happens here once.
"""

from __future__ import annotations

import json
import re
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any

from studio_contracts.local.harness import ChangeKind

from studio_client.harness import jsonc
from studio_client.harness.base import (
    STUDIO_MCP_SERVER_NAME,
    AdapterRefusal,
    Detection,
    DetectionState,
    HarnessAdapter,
    HarnessContext,
    PlannedEdit,
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

_MAJOR = re.compile(r"^(\d+)\.")


@dataclass(frozen=True)
class _Inspection:
    detection: Detection
    target: str | None = None
    document: Document | None = None


class JsonMcpAdapter(HarnessAdapter):
    executable_names: tuple[str, ...]
    version_args: tuple[str, ...] = ("--version",)
    identity: re.Pattern[str]
    supported_major: int
    candidate_files: tuple[str, ...]
    container_path: tuple[str, ...]
    comments: bool = False
    trailing_commas: bool = False

    @abstractmethod
    def build_entry(self, mcp_url: str) -> dict[str, Any]:
        """This harness's syntax for a remote MCP server authenticated by a
        reference to the machine token — never the token itself."""

    @property
    def _entry_path(self) -> tuple[str, ...]:
        return (*self.container_path, STUDIO_MCP_SERVER_NAME)

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

    def _config_file(self, ctx: HarnessContext) -> tuple[str, Document | None]:
        found: list[tuple[str, Document]] = []
        for name in self.candidate_files:
            document = read_document(resolve_target(ctx.workspace_root, name))
            if document is not None:
                found.append((name, document))
        if len(found) > 1:
            raise AdapterRefusal("ambiguous_config")
        if found:
            return found[0]
        return self.candidate_files[0], None

    def _inspect(self, ctx: HarnessContext) -> _Inspection:
        version, blocked = self._version(ctx)
        if blocked is not None:
            return _Inspection(blocked)
        try:
            target, document = self._config_file(ctx)
        except FsError as error:
            return _Inspection(
                Detection(DetectionState.CONFIGURATION_INVALID, version, error.reason)
            )
        except AdapterRefusal as refusal:
            return _Inspection(
                Detection(DetectionState.CONFIGURATION_INVALID, version, refusal.reason)
            )
        if document is None:
            return _Inspection(Detection(DetectionState.CONFIGURATION_MISSING, version), target)
        try:
            root = jsonc.parse(
                document.text, comments=self.comments, trailing_commas=self.trailing_commas
            )
            if root.kind != "object":
                raise jsonc.JsoncError("unexpected_shape", "root is not an object")
            node = jsonc.lookup(root, self._entry_path)
        except jsonc.JsoncError as error:
            return _Inspection(
                Detection(DetectionState.CONFIGURATION_INVALID, version, error.code),
                target,
                document,
            )
        expected = self.build_entry(ctx.mcp_url)
        if node is not None and jsonc.to_python(node) == expected:
            return _Inspection(
                Detection(DetectionState.CONFIGURED, version, managed_files=(target,)),
                target,
                document,
            )
        reason = "entry_differs" if node is not None else None
        return _Inspection(
            Detection(DetectionState.CONFIGURATION_MISSING, version, reason), target, document
        )

    def detect(self, ctx: HarnessContext) -> Detection:
        try:
            return self._inspect(ctx).detection
        except FsError as error:
            return Detection(DetectionState.UNAVAILABLE, reason=error.reason)

    def plan(self, ctx: HarnessContext) -> list[PlannedEdit]:
        try:
            inspection = self._inspect(ctx)
        except FsError as error:
            raise AdapterRefusal(error.reason) from error
        detection = inspection.detection
        if detection.state is DetectionState.CONFIGURED:
            return []
        if detection.state is not DetectionState.CONFIGURATION_MISSING:
            raise AdapterRefusal(detection.reason or detection.state.value)
        assert inspection.target is not None
        expected = self.build_entry(ctx.mcp_url)
        document = inspection.document
        try:
            path = resolve_target(ctx.workspace_root, inspection.target)
            if not is_writable(path):
                raise AdapterRefusal("read_only")
            if document is None:
                nested: Any = expected
                for key in reversed(self._entry_path):
                    nested = {key: nested}
                text = json.dumps(nested, indent=2, ensure_ascii=False) + "\n"
                bom = False
                kind = ChangeKind.CREATE
                summary = "Create the file with the Studi'OS MCP server entry."
            else:
                text = jsonc.upsert(
                    document.text,
                    self._entry_path,
                    expected,
                    comments=self.comments,
                    trailing_commas=self.trailing_commas,
                )
                bom = document.bom
                kind = ChangeKind.MODIFY
                summary = (
                    "Update the Studi'OS MCP server entry; every other setting is kept."
                    if detection.reason == "entry_differs"
                    else "Add the Studi'OS MCP server entry; every other setting is kept."
                )
            jsonc.verify_edit(
                None if document is None else document.text,
                text,
                self._entry_path,
                expected,
                comments=self.comments,
                trailing_commas=self.trailing_commas,
            )
            data = encode_text(text, bom=bom)
        except jsonc.JsoncError as error:
            raise AdapterRefusal(error.code) from error
        except FsError as error:
            raise AdapterRefusal(error.reason) from error
        return [
            PlannedEdit(
                target=inspection.target, kind=kind, summary=summary, before=document, after=data
            )
        ]
