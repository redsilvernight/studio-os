"""The credential a harness itself uses to reach Studi'OS over MCP.

DEC-0104 §2 / DEC-0226: each (workstation, tool) pair owns its own Studi'OS
machine, and the Desktop writes that machine's credential into the tool's own
MCP entry. A session-start hook that asked `agents ensure` with the Desktop's
credential would register the agent under a machine the harness never
authenticates as, so `studio_start_work` then refuses it with `actor_not_owned`
— one agent per conversation, none of them usable.

This module reads that entry back, strictly for the origin the session is bound
to: a tool wired to another server is never adopted. Nothing is written, and the
credential is kept out of every representation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from studio_client.harness.base import AdapterRefusal, HarnessContext
from studio_client.harness.fsafe import FsError
from studio_client.harness.json_mcp import JsonMcpAdapter
from studio_client.harness.jsonc import JsoncError
from studio_client.harness.registry import HarnessRegistry
from studio_client.tokens import origin_of


@dataclass(frozen=True)
class SessionCredential:
    """One harness's own MCP credential for one server origin."""

    harness: str
    origin: str
    token: str = field(repr=False)
    source: str


def _bearer_token(entry: Mapping[str, object]) -> str | None:
    headers = entry.get("headers")
    if not isinstance(headers, Mapping):
        return None
    value = headers.get("Authorization")
    if not isinstance(value, str):
        return None
    scheme, _, token = value.strip().partition(" ")
    if scheme.casefold() != "bearer":
        return None
    token = token.strip()
    return token or None


def read_session_credential(
    harness: str,
    *,
    home: Path,
    origin: str,
    env: Mapping[str, str] | None = None,
    workspace_root: Path | None = None,
) -> SessionCredential | None:
    """The harness's own Studi'OS credential for `origin`.

    None when the tool is not installed, has no Studi'OS MCP entry, names
    another server, or carries no Bearer header — never a fallback token. A
    config Studi'OS cannot parse is a miss too: a session start must not fail
    because the user's file is foreign.
    """
    adapter = HarnessRegistry().get(harness)
    if not isinstance(adapter, JsonMcpAdapter):
        return None
    root = workspace_root or home
    ctx = HarnessContext(
        workspace_root=root,
        mcp_url=f"{origin.rstrip('/')}/mcp",
        env={} if env is None else env,
        probe_cwd=root,
        home=home,
    )
    try:
        entry = adapter.read_user_entry(ctx)
        source = adapter.user_target(ctx)
    except (AdapterRefusal, JsoncError, FsError, OSError, ValueError):
        return None
    if not isinstance(entry, Mapping):
        return None
    url = entry.get("url")
    if not isinstance(url, str) or origin_of(url) != origin_of(origin):
        return None
    token = _bearer_token(entry)
    if token is None:
        return None
    return SessionCredential(harness=harness, origin=origin_of(url), token=token, source=source)
