"""Read-only local usage collection for interactive desktop sessions.

Public surface of the `usage.local` package: the three certified readers, the
dated EUR price table, and the scanner that turns their output into ledger
entries per (session, task, model, UTC day) bucket.
"""

from __future__ import annotations

from studio_client.usage.local.base import (
    BilledTokens,
    LocalSession,
    LocalUsageReader,
    TaskClaim,
    UsageEvent,
)
from studio_client.usage.local.claude_code import ClaudeCodeLocalReader
from studio_client.usage.local.codex import CodexLocalReader
from studio_client.usage.local.opencode import OpenCodeLocalReader
from studio_client.usage.local.pricing import (
    BUNDLED_PRICE_LIST_ID,
    PriceTable,
    load_price_table,
)
from studio_client.usage.local.scanner import (
    LocalUsageScanner,
    ScanReport,
    WorkspaceRoot,
    project_for_path,
)

__all__ = [
    "BUNDLED_PRICE_LIST_ID",
    "BilledTokens",
    "ClaudeCodeLocalReader",
    "CodexLocalReader",
    "LocalSession",
    "LocalUsageReader",
    "LocalUsageScanner",
    "OpenCodeLocalReader",
    "PriceTable",
    "ScanReport",
    "TaskClaim",
    "UsageEvent",
    "WorkspaceRoot",
    "load_price_table",
    "project_for_path",
]
