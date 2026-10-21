from __future__ import annotations

import re
from pathlib import Path

from studio_client.daemon.service import SERVED

ALLOWLIST_RS = (
    Path(__file__).resolve().parents[2] / "desktop" / "src-tauri" / "src" / "allowlist.rs"
)


def _desktop_served() -> set[str]:
    source = ALLOWLIST_RS.read_text(encoding="utf-8")
    block = re.search(r"SERVED_BY_DAEMON: &\[&str\] = &\[(.*?)\];", source, re.S)
    assert block is not None, "SERVED_BY_DAEMON not found in allowlist.rs"
    return set(re.findall(r'"([a-z_.]+)"', block.group(1)))


def test_desktop_relays_exactly_the_commands_the_daemon_serves() -> None:
    daemon = {command.value for command in SERVED}
    desktop = _desktop_served()
    assert desktop - daemon == set(), "relayed by the Desktop but refused by the daemon"
    assert daemon - desktop == set(), "served by the daemon but refused by the Desktop"
