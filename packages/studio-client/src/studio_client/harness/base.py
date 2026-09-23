"""The vendor-neutral contract every harness adapter implements.

The registry, the service and the bridge only ever see these types. What a
harness is called on disk, which file it reads, what its MCP entry looks like
and how its version is asked for are the adapter's business alone.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from studio_contracts.local.harness import ChangeKind

from studio_client.harness.fsafe import Document, sha256_hex

STUDIO_MCP_SERVER_NAME = "studio-os"
STUDIO_MCP_TOKEN_ENV = "STUDIO_MCP_MACHINE_TOKEN"  # noqa: S105 — the variable's name, never a value


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


@dataclass(frozen=True)
class HarnessContext:
    """Everything an adapter may use. Paths and environment are injected so a
    test (or a different OS) never depends on the real machine."""

    workspace_root: Path
    mcp_url: str
    env: Mapping[str, str]
    probe_cwd: Path

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
    def plan(self, ctx: HarnessContext) -> list[PlannedEdit]:
        """The edits that make the harness use Studi'OS's MCP; empty when it
        already does. Read-only. Raises AdapterRefusal when it cannot do so
        safely."""


def system_env() -> Mapping[str, str]:
    return dict(os.environ)
