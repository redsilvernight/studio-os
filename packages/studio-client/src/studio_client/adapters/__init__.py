from __future__ import annotations

from studio_client.adapters.base import (
    CAPABILITY_DIMENSIONS,
    Adapter,
    AdapterArtifact,
    AdapterError,
    AdapterErrorCode,
    AdapterResult,
    AdapterWarning,
    CapabilitySupport,
    capability_notes,
    check_harness_compatible,
    ensure_supported,
    get_adapter,
    list_adapters,
    materialize,
    register_adapter,
    sanitize_agent_filename,
)
from studio_client.adapters.claude import ADAPTER_ID as CLAUDE_CODE_ADAPTER_ID
from studio_client.adapters.claude import MANAGED_DIR as CLAUDE_CODE_MANAGED_DIR
from studio_client.adapters.claude import ClaudeCodeAdapter
from studio_client.adapters.codex import ADAPTER_ID as CODEX_ADAPTER_ID
from studio_client.adapters.codex import MANAGED_DIR as CODEX_MANAGED_DIR
from studio_client.adapters.codex import CodexAdapter
from studio_client.adapters.opencode import ADAPTER_ID as OPENCODE_ADAPTER_ID
from studio_client.adapters.opencode import MANAGED_DIR as OPENCODE_MANAGED_DIR
from studio_client.adapters.opencode import OpenCodeAdapter

register_adapter(ClaudeCodeAdapter())
register_adapter(OpenCodeAdapter())
register_adapter(CodexAdapter())

__all__ = [
    "CAPABILITY_DIMENSIONS",
    "CLAUDE_CODE_ADAPTER_ID",
    "CLAUDE_CODE_MANAGED_DIR",
    "CODEX_ADAPTER_ID",
    "CODEX_MANAGED_DIR",
    "OPENCODE_ADAPTER_ID",
    "OPENCODE_MANAGED_DIR",
    "Adapter",
    "AdapterArtifact",
    "AdapterError",
    "AdapterErrorCode",
    "AdapterResult",
    "AdapterWarning",
    "CapabilitySupport",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "OpenCodeAdapter",
    "capability_notes",
    "check_harness_compatible",
    "ensure_supported",
    "get_adapter",
    "list_adapters",
    "materialize",
    "register_adapter",
    "sanitize_agent_filename",
]
