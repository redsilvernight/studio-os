from __future__ import annotations

import asyncio
import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import Context
from mcp.types import ClientCapabilities, RootsCapability
from studio_contracts.local.identity import ProfileRef

INITIALIZED_NOTIFICATION = "notifications/initialized"
ROOTS_LIST_CHANGED_NOTIFICATION = "notifications/roots/list_changed"

RESOLVE_WORKSPACE_TOOL = "studio_resolve_workspace"

RESOLVE_WORKSPACE_DESCRIPTION = (
    "Report the local workspace attachment for this connection — read-only. "
    "Returns the folders the client shared (MCP roots, or the launch "
    "directory otherwise), each with its resolved Studio OS project_id or an "
    "explicit machine-readable unresolved reason. Never creates anything: an "
    "unresolved folder only yields a reason, never a workspace."
)

WORKSPACE_INSTRUCTIONS = (
    "Studio OS local workspace: this server attaches the client's folder to a "
    "Studio OS project at initialization (MCP roots when the client declares "
    "them, the launch directory otherwise) and re-attaches when the client "
    "reports roots/list_changed. Call studio_resolve_workspace for the "
    "machine-readable attachment — a project_id when resolved, an explicit "
    "unresolved reason otherwise. Memory and graph tools only ever read this "
    "machine."
)

_NOT_INITIALIZED = "not_initialized"
_NO_ROOTS = "no_roots"
_ROOTS_LIST_FAILED = "roots_list_failed"
_NON_FILE_ROOT = "non_file_root"


@dataclass(frozen=True)
class WorkspaceAttachConfig:
    """How `studio-os-local` attaches the client's folder to a project.

    `profile` selects the server origin the remotes resolve against;
    `registry_dir` is the machine-local registry (defaults inside
    `resolve_workspace` to the Bloc B location); `fallback_dir` overrides the
    process working directory used when the client declares no roots
    capability (tests); `resolver`/`client_factory`/`probe` inject the
    repository resolution dependencies (tests inject a fake resolver so no
    network is ever touched).
    """

    profile: ProfileRef
    registry_dir: Path | None = None
    fallback_dir: Path | None = None
    resolver: Any | None = None
    client_factory: Any | None = None
    probe: Any | None = None


def file_root_to_path(uri: str) -> Path | None:
    """A `file://` root URI to a local path, else `None`.

    Only the `file` scheme with an empty or `localhost` host is accepted —
    anything else (remote schemes, UNC hosts) is skipped, never resolved.
    """
    try:
        parsed = urlparse(uri)
    except ValueError:
        return None
    if parsed.scheme != "file":
        return None
    host = (parsed.hostname or "").lower()
    if host not in ("", "localhost"):
        return None
    raw = url2pathname(unquote(parsed.path or ""))
    if os.name == "nt" and re.match(r"^/[A-Za-z]:", raw):
        raw = raw[1:]
    candidate = Path(raw)
    if not candidate.is_absolute():
        return None
    return candidate


def _entry(
    *,
    uri: str | None,
    path: str,
    status: str,
    reason: str,
    repo_root: str | None = None,
    repository_key: str | None = None,
    project_id: str | None = None,
    project_slug: str | None = None,
    created: bool = False,
    cached: bool = False,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "uri": uri,
        "path": path,
        "status": status,
        "reason": reason,
        "repo_root": repo_root,
        "repository_key": repository_key,
        "project_id": project_id,
        "project_slug": project_slug,
        "created": created,
        "cached": cached,
        "detail": detail,
    }


class WorkspaceAttachment:
    """Per-connection workspace attachment for `studio-os-local`.

    `refresh` runs at initialization and on `notifications/roots/list_changed`:
    with the roots capability it lists the client roots and resolves every
    `file://` one, otherwise it resolves the launch directory. Resolution
    delegates to `studio_client.workspace_resolution.resolve_workspace`
    (imported lazily so importing this module never drags in the credential
    or network machinery): a failure is a typed `unresolved` entry and never
    writes a workspace config. `payload` is the machine-readable state served
    by `studio_resolve_workspace`.
    """

    def __init__(self, config: WorkspaceAttachConfig) -> None:
        self._config = config
        # Serializes refreshes: a tools/call racing the refresh of
        # notifications/initialized must not resolve (and create) twice.
        self._lock = asyncio.Lock()
        self._state: dict[str, Any] = {
            "status": "unresolved",
            "reason": _NOT_INITIALIZED,
            "source": None,
            "path": None,
            "repo_root": None,
            "repository_key": None,
            "project_id": None,
            "project_slug": None,
            "created": False,
            "cached": False,
            "detail": (
                "the client has not completed initialization yet; the attachment "
                "refreshes on notifications/initialized"
            ),
            "roots": [],
        }

    @property
    def config(self) -> WorkspaceAttachConfig:
        return self._config

    @property
    def needs_refresh(self) -> bool:
        """True until an attachment refresh has run for a live connection."""
        return self._state.get("reason") == _NOT_INITIALIZED

    def payload(self) -> dict[str, Any]:
        state = dict(self._state)
        state["roots"] = [dict(entry) for entry in self._state["roots"]]
        return state

    async def _resolve_path(self, uri: str | None, path: Path) -> dict[str, Any]:
        from studio_client.workspace_resolution import resolve_workspace

        try:
            resolution = await resolve_workspace(
                path,
                self._config.profile,
                registry_dir=self._config.registry_dir,
                client=self._config.resolver,
                client_factory=self._config.client_factory,
                probe=self._config.probe,
            )
        except Exception as exc:  # never break the connection on resolution
            return _entry(
                uri=uri,
                path=str(path),
                status="unresolved",
                reason="server_error",
                detail=f"{type(exc).__name__}: {exc}",
            )
        return _entry(
            uri=uri,
            path=resolution.path,
            status=resolution.status.value,
            reason=resolution.reason.value,
            repo_root=resolution.repo_root,
            repository_key=resolution.repository_key,
            project_id=str(resolution.project_id) if resolution.project_id else None,
            project_slug=resolution.project_slug,
            created=resolution.created,
            cached=resolution.cached,
            detail=resolution.detail,
        )

    async def refresh(self, session: Any, *, if_needed: bool = False) -> None:
        """Re-resolve the attachment for one connection, never raising.

        `if_needed` re-checks `needs_refresh` once the lock is held, so a
        caller that waited behind an in-flight refresh does not repeat it.
        """
        async with self._lock:
            if if_needed and not self.needs_refresh:
                return
            try:
                await self._refresh(session)
            except Exception as exc:  # last-resort guard for the middleware chain
                self._state = {
                    "status": "unresolved",
                    "reason": "server_error",
                    "source": None,
                    "path": None,
                    "repo_root": None,
                    "repository_key": None,
                    "project_id": None,
                    "project_slug": None,
                    "created": False,
                    "cached": False,
                    "detail": f"workspace attachment failed: {type(exc).__name__}: {exc}",
                    "roots": [],
                }

    async def _refresh(self, session: Any) -> None:
        try:
            supports_roots = bool(
                session.check_client_capability(ClientCapabilities(roots=RootsCapability()))
            )
        except Exception:
            supports_roots = False
        if not supports_roots:
            fallback = self._config.fallback_dir or Path.cwd()
            entry = await self._resolve_path(None, fallback)
            self._state = {**entry, "source": "cwd", "roots": [entry]}
            return
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                listed = await session.list_roots()
        except Exception as exc:
            self._state = {
                "status": "unresolved",
                "reason": _ROOTS_LIST_FAILED,
                "source": "roots",
                "path": None,
                "repo_root": None,
                "repository_key": None,
                "project_id": None,
                "project_slug": None,
                "created": False,
                "cached": False,
                "detail": f"roots/list failed: {type(exc).__name__}: {exc}",
                "roots": [],
            }
            return
        entries: list[dict[str, Any]] = []
        for root in listed.roots or []:
            uri = str(root.uri)
            path = file_root_to_path(uri)
            if path is None:
                entries.append(
                    _entry(
                        uri=uri,
                        path=uri,
                        status="unresolved",
                        reason=_NON_FILE_ROOT,
                        detail="only file:// roots are resolved",
                    )
                )
                continue
            entries.append(await self._resolve_path(uri, path))
        if not entries:
            self._state = {
                "status": "unresolved",
                "reason": _NO_ROOTS,
                "source": "roots",
                "path": None,
                "repo_root": None,
                "repository_key": None,
                "project_id": None,
                "project_slug": None,
                "created": False,
                "cached": False,
                "detail": "the client declared roots but listed none; no workspace attached",
                "roots": [],
            }
            return
        primary = next((item for item in entries if item["status"] == "resolved"), entries[0])
        self._state = {**primary, "source": "roots", "roots": entries}


class WorkspaceAttachmentMiddleware:
    """Refresh the attachment on `notifications/initialized` and
    `notifications/roots/list_changed`, then let the message through.

    Registered on `MCPServer(middleware=...)`, so it observes every inbound
    message without touching the private low-level server. Refresh runs after
    the chain (`call_next` first): on `initialized` the connection is fully
    established, so `roots/list` can use the back-channel; a refresh failure
    is already recorded as a degraded state and never breaks the chain.
    """

    def __init__(self, attachment: WorkspaceAttachment) -> None:
        self._attachment = attachment

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        result = await call_next(ctx)
        if ctx.method in (INITIALIZED_NOTIFICATION, ROOTS_LIST_CHANGED_NOTIFICATION):
            await self._attachment.refresh(ctx.session)
        return result


def make_resolve_workspace(
    attachment: WorkspaceAttachment,
) -> Any:
    """Build the `studio_resolve_workspace` handler serving the cached state.

    The refresh on `notifications/initialized` pre-warms the state, but a
    `tools/call` may win the race on a busy connection: when the handler sees
    a live session and no refresh has run yet, it refreshes on demand before
    answering, so the first call after initialization is never stale.
    """

    async def studio_resolve_workspace(ctx: Context | None = None) -> dict[str, Any]:
        try:
            session = ctx.session if ctx is not None else None
        except Exception:
            # A bare Context outside of a request (in-process `call_tool`
            # without a connection): no live session to refresh from.
            session = None
        if session is not None and attachment.needs_refresh:
            await attachment.refresh(session, if_needed=True)
        return attachment.payload()

    return studio_resolve_workspace


def attach_workspace(server: Any, config: WorkspaceAttachConfig) -> WorkspaceAttachment:
    """Register the attachment middleware and `studio_resolve_workspace` tool.

    Returns the attachment holding the per-connection state.
    """
    attachment = WorkspaceAttachment(config)
    server.add_tool(
        make_resolve_workspace(attachment),
        name=RESOLVE_WORKSPACE_TOOL,
        description=RESOLVE_WORKSPACE_DESCRIPTION,
        annotations=_read_only(),
    )
    middleware = getattr(server, "middleware", None)
    if middleware is not None:
        middleware.append(WorkspaceAttachmentMiddleware(attachment))
    return attachment


def _read_only() -> Any:
    from mcp.types import ToolAnnotations

    return ToolAnnotations(read_only_hint=True)
