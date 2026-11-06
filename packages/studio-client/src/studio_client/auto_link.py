from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from studio_contracts.local.identity import ProfileRef
from studio_workspaces import WorkspaceStoreError, register_workspace

from studio_client.config import ClientConfig
from studio_client.tokens import origin_of

# DEC-0285: the only non-interactive caller of workspace registration. It acts
# on a repository whose AGENTS.md declares its project, after a one-time
# machine consent that also pins the API origin written to config.toml.
CONSENT_FILE = "auto-link.json"
MCP_SERVER_NAME = "studio-os"
_PROJECT_LINE = re.compile(
    r"^\s*(?:projet\s+studio\s*os|studio\s*os\s+project|project[_ ]id)\s*[:=]\s*`?"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE | re.MULTILINE,
)


class AutoLinkStatus(StrEnum):
    LINKED = "linked"
    ALREADY_LINKED = "already_linked"
    NO_PROJECT_ID = "no_project_id"
    NO_CONSENT = "no_consent"
    CONFLICT = "conflict"
    CONFIG_UNAVAILABLE = "config_unavailable"
    CONFIG_MISMATCH = "config_mismatch"
    FAILED = "failed"


@dataclass(frozen=True)
class AutoLinkResult:
    status: AutoLinkStatus
    project_id: UUID | None = None
    server_origin: str | None = None
    detail: str = ""
    config_written: bool = False


def project_id_from_agents(repo: Path) -> UUID | None:
    try:
        text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        return None
    match = _PROJECT_LINE.search(text)
    return UUID(match.group(1)) if match else None


def _server_url(servers: object) -> str | None:
    entry = servers.get(MCP_SERVER_NAME) if isinstance(servers, dict) else None
    url = entry.get("url") if isinstance(entry, dict) else None
    return url if isinstance(url, str) else None


def mcp_origin(repo: Path, home: Path) -> str | None:
    """Origin of the `studio-os` MCP server already declared for a harness.
    Only the `url` field is read, never headers or tokens."""
    urls: list[str | None] = []
    for path in (repo / ".mcp.json", home / ".claude.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        urls.append(_server_url(data.get("mcpServers")))
        for project in (data.get("projects") or {}).values():
            urls.append(
                _server_url(project.get("mcpServers") if isinstance(project, dict) else None)
            )
    try:
        codex = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
        urls.append(_server_url(codex.get("mcp_servers")))
    except (OSError, ValueError):
        pass
    for url in urls:
        if url and url.startswith(("http://", "https://")):
            return origin_of(url)
    return None


def _consent_path(registry_dir: Path) -> Path:
    return registry_dir / CONSENT_FILE


def read_consent(registry_dir: Path) -> str | None:
    """The API origin the user consented to, or None without consent."""
    try:
        data = json.loads(_consent_path(registry_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    origin = data.get("api_origin") if isinstance(data, dict) and data.get("granted") else None
    return origin if isinstance(origin, str) and origin else None


def grant_consent(registry_dir: Path, api_origin: str) -> None:
    registry_dir.mkdir(parents=True, exist_ok=True)
    _consent_path(registry_dir).write_text(
        json.dumps({"granted": True, "api_origin": api_origin}), encoding="utf-8"
    )


def revoke_consent(registry_dir: Path) -> bool:
    try:
        _consent_path(registry_dir).unlink()
    except FileNotFoundError:
        return False
    return True


def _loaded_config() -> ClientConfig | None:
    try:
        return ClientConfig()  # type: ignore[call-arg]
    except ValidationError:
        return None


def auto_link(
    repo: Path,
    registry_dir: Path,
    *,
    home: Path | None = None,
    load_config: Callable[[], ClientConfig | None] = _loaded_config,
) -> AutoLinkResult:
    """Links `repo` to the project its AGENTS.md declares. Never overwrites an
    existing `config.toml` nor an existing link to another project."""
    project_id = project_id_from_agents(repo)
    if project_id is None:
        return AutoLinkResult(AutoLinkStatus.NO_PROJECT_ID, detail="AGENTS.md declares no project")
    consent = read_consent(registry_dir)
    if consent is None:
        return AutoLinkResult(
            AutoLinkStatus.NO_CONSENT,
            project_id,
            detail="run `studio-client workspaces auto-link-consent grant`",
        )
    config = load_config()
    written = False
    if config is None:
        deduced = mcp_origin(repo, home or Path.home())
        if deduced is None:
            return AutoLinkResult(
                AutoLinkStatus.CONFIG_UNAVAILABLE,
                project_id,
                detail="no api_base_url and no studio-os MCP url found",
            )
        if deduced != consent:
            return AutoLinkResult(
                AutoLinkStatus.CONFIG_MISMATCH,
                project_id,
                deduced,
                f"MCP origin differs from the consented one ({consent})",
            )
        registry_dir.mkdir(parents=True, exist_ok=True)
        try:
            with (registry_dir / "config.toml").open("x", encoding="utf-8") as handle:
                handle.write(f'api_base_url = "{deduced}"\n')
        except FileExistsError:
            return AutoLinkResult(
                AutoLinkStatus.CONFIG_UNAVAILABLE, project_id, detail="config.toml is incomplete"
            )
        written = True
        config = load_config()
        if config is None:
            return AutoLinkResult(AutoLinkStatus.FAILED, project_id, detail="config unreadable")
    origin = origin_of(config.api_base_url)
    try:
        profile = ProfileRef(profile_id=config.profile_id, server_origin=origin)
        result = register_workspace(registry_dir, profile, project_id, str(repo))
    except WorkspaceStoreError as exc:
        status = AutoLinkStatus.CONFLICT if "another project" in str(exc) else AutoLinkStatus.FAILED
        return AutoLinkResult(status, project_id, origin, str(exc), written)
    status = (
        AutoLinkStatus.ALREADY_LINKED
        if result.action.value == "unchanged"
        else AutoLinkStatus.LINKED
    )
    return AutoLinkResult(status, project_id, origin, config_written=written)
