from __future__ import annotations

import json

import pytest
from studio_client.harness import jsonc

ENTRY = {"type": "http", "url": "https://x.example/mcp"}
PATH = ("mcpServers", "studio-os")


def _apply(text: str, **flags: bool) -> str:
    after = jsonc.upsert(text, PATH, ENTRY, **flags)
    jsonc.verify_edit(text, after, PATH, ENTRY, **flags)
    return after


def test_insert_into_empty_object() -> None:
    after = _apply("{}\n")
    assert json.loads(after) == {"mcpServers": {"studio-os": ENTRY}}


def test_insert_preserves_other_servers_and_keys() -> None:
    before = json.dumps(
        {"theme": "dark", "mcpServers": {"other": {"command": "x"}}, "z": 1}, indent=2
    )
    after = _apply(before)
    data = json.loads(after)
    assert data["theme"] == "dark"
    assert data["z"] == 1
    assert data["mcpServers"]["other"] == {"command": "x"}
    assert data["mcpServers"]["studio-os"] == ENTRY
    assert after.startswith('{\n  "theme": "dark",\n  "mcpServers": {\n    "other"')


def test_comments_and_trailing_commas_survive() -> None:
    before = (
        '{\n  // keep me\n  "mcp": {\n    "a": {"type": "local"}, // note\n  },\n'
        '  /* block */ "model": "m",\n}\n'
    )
    after = jsonc.upsert(before, ("mcp", "studio-os"), ENTRY, comments=True, trailing_commas=True)
    assert "// keep me" in after and "// note" in after and "/* block */" in after
    jsonc.verify_edit(
        before, after, ("mcp", "studio-os"), ENTRY, comments=True, trailing_commas=True
    )


def test_crlf_and_tabs_are_kept() -> None:
    before = '{\r\n\t"a": 1\r\n}\r\n'
    after = _apply(before)
    assert "\r\n" in after and "\n" not in after.replace("\r\n", "")
    assert '\t"mcpServers"' in after


def test_update_existing_entry_in_place() -> None:
    before = '{"mcpServers": {"studio-os": {"url": "old"}, "b": 1}}'
    after = _apply(before)
    assert json.loads(after)["mcpServers"]["b"] == 1
    assert json.loads(after)["mcpServers"]["studio-os"] == ENTRY


def test_upsert_is_idempotent() -> None:
    once = _apply("{}")
    assert jsonc.upsert(once, PATH, ENTRY) == once or json.loads(
        jsonc.upsert(once, PATH, ENTRY)
    ) == json.loads(once)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("{", "syntax"),
        ('{"a": 1,}', "trailing_comma"),
        ('{"a": 1} x', "syntax"),
        ('{"a": 1, "a": 2}', "duplicate_key"),
        ('{"a": // c\n1}', "comment_not_allowed"),
        ('{"a": "unterminated}', "syntax"),
        ("[" * 100 + "]" * 100, "too_deep"),
    ],
)
def test_malformed_is_rejected(text: str, code: str) -> None:
    with pytest.raises(jsonc.JsoncError) as info:
        jsonc.parse(text)
    assert info.value.code == code


def test_non_object_root_and_path_shape_refused() -> None:
    with pytest.raises(jsonc.JsoncError):
        jsonc.upsert("[]", PATH, ENTRY)
    with pytest.raises(jsonc.JsoncError):
        jsonc.upsert('{"mcpServers": []}', PATH, ENTRY)


def test_verify_detects_collateral_change() -> None:
    before = '{"a": 1, "mcpServers": {}}'
    tampered = (
        '{"a": 2, "mcpServers": {"studio-os": {"type": "http", "url": "https://x.example/mcp"}}}'
    )
    with pytest.raises(jsonc.JsoncError):
        jsonc.verify_edit(before, tampered, PATH, ENTRY)
