"""The vendor-neutral contract every harness adapter implements.

The registry, the service and the bridge only ever see these types. What a
harness is called on disk, which file it reads, what its MCP entry looks like
and how its version is asked for are the adapter's business alone.

Studi'OS is declared once per tool, in the tool's *user* configuration, with a
credential dedicated to that tool (DEC-0104 §2). A workspace file only matters
when it still carries an older project-scoped entry that would shadow it.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from studio_contracts.local.harness import ChangeKind

from studio_client.config import client_channel
from studio_client.harness.fsafe import Document, sha256_hex

STUDIO_MCP_SERVER_NAME = "studio-os-dev" if client_channel() == "dev" else "studio-os"


class DetectionState(StrEnum):
    NOT_INSTALLED = "not_installed"
    CONFIGURATION_MISSING = "configuration_missing"
    CONFIGURED = "configured"
    CONFIGURATION_INVALID = "configuration_invalid"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Detection:
    """What an adapter found. `reason` is a stable token (never free text) that
    explains any state other than `configured` / `configuration_missing`."""

    state: DetectionState
    version: str | None = None
    reason: str | None = None
    managed_files: tuple[str, ...] = ()
    credential_fingerprint: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class HarnessContext:
    """Everything an adapter may use. Paths and environment are injected so a
    test (or a different OS) never depends on the real machine."""

    workspace_root: Path
    mcp_url: str
    env: Mapping[str, str]
    probe_cwd: Path
    home: Path = field(default_factory=Path.home)

    def env_value(self, name: str) -> str | None:
        for key, value in self.env.items():
            if key.upper() == name.upper():
                return value
        return None


@dataclass(frozen=True)
class PlannedEdit:
    """One file change, fully computed and verified but not yet written."""

    target: str
    kind: ChangeKind
    summary: str
    before: Document | None
    after: bytes

    @property
    def before_hash(self) -> str | None:
        return None if self.before is None else self.before.sha256

    @property
    def after_hash(self) -> str:
        return sha256_hex(self.after)


@dataclass(frozen=True)
class UserEntryEdit:
    """The Studi'OS entry of the tool's user configuration, described by its
    redacted form only: hashes never depend on the credential, and nothing
    here can reveal it. `restorable` tells whether the entry it replaces holds
    no secret and can therefore be put back by a rollback."""

    target: str
    kind: ChangeKind
    summary: str
    before: bytes | None
    after: bytes
    restorable: bool

    @property
    def before_hash(self) -> str | None:
        return None if self.before is None else sha256_hex(self.before)

    @property
    def after_hash(self) -> str:
        return sha256_hex(self.after)


@dataclass(frozen=True)
class AdapterPlan:
    user_entry: UserEntryEdit | None = None
    workspace_edits: list[PlannedEdit] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.user_entry is None and not self.workspace_edits


class AdapterRefusal(Exception):
    """The adapter will not produce or apply a change, and says why with a
    stable token. This is the fail-closed path: unknown, too-new or malformed
    input ends here rather than in a guess."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HarnessAdapter(ABC):
    adapter_id: str
    harness_id: str
    display_name: str
    capabilities: tuple[str, ...] = ("mcp.config",)

    @abstractmethod
    def detect(self, ctx: HarnessContext) -> Detection:
        """Read-only. Never writes, never raises for an ordinary failure."""

    @abstractmethod
    def plan(self, ctx: HarnessContext, *, renew: bool = False) -> AdapterPlan:
        """The edits that make the harness use Studi'OS's MCP with a dedicated
        credential; empty when it already does (unless `renew`). Read-only.
        Raises AdapterRefusal when it cannot do so safely."""

    @abstractmethod
    def read_user_entry(self, ctx: HarnessContext) -> dict[str, object] | None:
        """The raw user-scope entry — it may hold a credential: keep it in memory."""

    @abstractmethod
    def write_user_entry(self, ctx: HarnessContext, entry: dict[str, object]) -> None:
        """Set the user-scope entry. Raises AdapterRefusal with a stable token and
        never lets the entry (or a command line holding it) reach an error."""

    @abstractmethod
    def remove_user_entry(self, ctx: HarnessContext) -> None:
        """Remove the user-scope entry; absent is a success."""

    @abstractmethod
    def build_entry(self, mcp_url: str, token: str) -> dict[str, object]:
        """This harness's syntax for Studi'OS's MCP server with `token`."""


def system_env() -> Mapping[str, str]:
    return dict(os.environ)
