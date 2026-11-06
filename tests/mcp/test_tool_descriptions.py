from __future__ import annotations

import re
from pathlib import Path


def test_work_tools_describe_readonly_and_closed_session_boundaries() -> None:
    server_source = Path("services/mcp/src/studio_mcp/server.py").read_text(encoding="utf-8")
    start_work_match = re.search(
        r'name="studio_start_work",\s*description=\((.*?)\),\s*annotations=',
        server_source,
        re.DOTALL,
    )
    sync_match = re.search(
        r'name="studio_sync",\s*description=\((.*?)\),\s*annotations=',
        server_source,
        re.DOTALL,
    )
    handoff_match = re.search(
        r'name="studio_handoff",\s*description=\((.*?)\),\s*annotations=',
        server_source,
        re.DOTALL,
    )
    assert start_work_match and sync_match and handoff_match
    start_work = re.sub(r"\s+", " ", start_work_match.group(1).replace('"', ""))
    sync = re.sub(r"\s+", " ", sync_match.group(1).replace('"', ""))
    handoff = re.sub(r"\s+", " ", handoff_match.group(1).replace('"', ""))
    assert "do not call it for a strictly read-only audit" in start_work
    assert "Explicit read-only intent takes precedence" in start_work
    assert "ended session returns session_not_found" in sync
    assert "After studio_handoff, never reuse that session_id" in sync
    assert "agent_id + task_id" in sync
    assert "never start new work" in handoff
    assert "stateless studio_sync(agent_id, task_id)" in handoff
