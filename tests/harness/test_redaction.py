from __future__ import annotations

from studio_client.harness.base import machine_token_env
from studio_client.harness.redaction import strip_ansi


def test_strip_ansi_removes_colour_and_cursor_sequences() -> None:
    raw = "\x1b[0mgreen\x1b[0m \x1b[2K\x1b[1Atext\x1b[?25h"
    assert strip_ansi(raw) == "green text"


def test_strip_ansi_removes_osc_and_normalises_line_endings() -> None:
    raw = "\x1b]0;title\x07line1\r\nline2\rline3"
    assert strip_ansi(raw) == "line1\nline2\nline3"


def test_strip_ansi_leaves_plain_text_untouched() -> None:
    assert strip_ansi("hello\nworld") == "hello\nworld"


def test_machine_token_env_extracts_a_literal_bearer_token() -> None:
    entry = {"headers": {"Authorization": "Bearer abc.def"}}
    assert machine_token_env(entry) == {"STUDIO_CLIENT_MACHINE_TOKEN": "abc.def"}


def test_machine_token_env_is_empty_without_a_literal_token() -> None:
    assert machine_token_env(None) == {}
    assert machine_token_env({"headers": {"Authorization": "Bearer ${TOKEN}"}}) == {}
    assert machine_token_env({"command": "obsidian-mcp"}) == {}
