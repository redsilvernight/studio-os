from __future__ import annotations

from studio_client.adapters.base import (
    Adapter,
    AdapterArtifact,
    AdapterError,
    AdapterErrorCode,
    AdapterResult,
    AdapterWarning,
    check_harness_compatible,
    get_adapter,
    list_adapters,
    materialize,
    register_adapter,
    sanitize_agent_filename,
)
from studio_client.adapters.claude import ADAPTER_ID as CLAUDE_CODE_ADAPTER_ID
from studio_client.adapters.claude import MANAGED_DIR as CLAUDE_CODE_MANAGED_DIR
from studio_client.adapters.claude import ClaudeCodeAdapter
from studio_client.adapters.opencode import ADAPTER_ID as OPENCODE_ADAPTER_ID
from studio_client.adapters.opencode import MANAGED_DIR as OPENCODE_MANAGED_DIR
from studio_client.adapters.opencode import OpenCodeAdapter

register_adapter(ClaudeCodeAdapter())
register_adapter(OpenCodeAdapter())

__all__ = [
    "CLAUDE_CODE_ADAPTER_ID",
    "CLAUDE_CODE_MANAGED_DIR",
    "OPENCODE_ADAPTER_ID",
    "OPENCODE_MANAGED_DIR",
    "Adapter",
    "AdapterArtifact",
    "AdapterError",
    "AdapterErrorCode",
    "AdapterResult",
    "AdapterWarning",
    "ClaudeCodeAdapter",
    "OpenCodeAdapter",
    "check_harness_compatible",
    "get_adapter",
    "list_adapters",
    "materialize",
    "register_adapter",
    "sanitize_agent_filename",
]
