from __future__ import annotations

from studio_client.harness.redaction import strip_ansi


def test_strip_ansi_removes_colour_and_cursor_sequences() -> None:
    raw = "\x1b[0mgreen\x1b[0m \x1b[2K\x1b[1Atext\x1b[?25h"
    assert strip_ansi(raw) == "green text"


def test_strip_ansi_removes_osc_and_normalises_line_endings() -> None:
    raw = "\x1b]0;title\x07line1\r\nline2\rline3"
    assert strip_ansi(raw) == "line1\nline2\nline3"


def test_strip_ansi_leaves_plain_text_untouched() -> None:
    assert strip_ansi("hello\nworld") == "hello\nworld"
