from __future__ import annotations

from studio_client.harness.base import entry_with_credential, machine_token_env
from studio_client.harness.redaction import strip_ansi


def test_strip_ansi_removes_colour_and_cursor_sequences() -> None:
    raw = "\x1b[0mgreen\x1b[0m \x1b[2K\x1b[1Atext\x1b[?25h"
    assert strip_ansi(raw) == "green text"


def test_strip_ansi_removes_osc_and_normalises_line_endings() -> None:
    raw = "\x1b]0;title\x07line1\r\nline2\rline3"
    assert strip_ansi(raw) == "line1\nline2\nline3"


def test_strip_ansi_leaves_plain_text_untouched() -> None:
    assert strip_ansi("hello\nworld") == "hello\nworld"


def test_machine_token_env_carries_the_launch_credential() -> None:
    assert machine_token_env("abc.def") == {"STUDIO_CLIENT_MACHINE_TOKEN": "abc.def"}


def test_entry_with_credential_replaces_the_bearer_without_mutating_the_entry() -> None:
    entry = {"type": "http", "headers": {"Authorization": "Bearer durable", "X-A": "1"}}
    replaced = entry_with_credential(entry, "ephemeral")
    assert replaced["headers"] == {"Authorization": "Bearer ephemeral", "X-A": "1"}
    assert entry["headers"]["Authorization"] == "Bearer durable"
