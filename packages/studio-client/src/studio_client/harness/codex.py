"""Codex: Studi'OS is declared as a `[mcp_servers.<name>]` table of the user
configuration, `<CODEX_HOME or ~/.codex>/config.toml`.

The file is edited as text, one table at a time, so comments, ordering and every
other setting survive; the result is parsed back and must equal the original
data with only the Studi'OS entry changed, otherwise nothing is written. In
memory the entry uses the vendor-neutral `headers` key, which Codex spells
`http_headers`. Layouts that cannot be edited safely (inline tables, dotted keys)
are refused.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from studio_client.harness.base import STUDIO_MCP_SERVER_NAME, AdapterRefusal, HarnessContext
from studio_client.harness.fsafe import (
    Document,
    FsError,
    atomic_write,
    encode_text,
    is_writable,
    read_document,
    resolve_target,
)
from studio_client.harness.json_mcp import JsonMcpAdapter

_CONFIG_NAME = "config.toml"
_CONTAINER = "mcp_servers"
_HEADER = re.compile(r"^\s*\[\[?\s*(?P<path>[^\[\]#]+?)\s*\]\]?\s*(?:#.*)?$")
_KEY_PART = re.compile(
    r'\s*(?:"(?P<quoted>[^"\\]*)"|\'(?P<literal>[^\']*)\'|(?P<bare>[A-Za-z0-9_-]+))\s*'
)


def _header_path(line: str) -> tuple[str, ...] | None:
    match = _HEADER.match(line)
    if match is None:
        return None
    raw = match.group("path")
    parts: list[str] = []
    position = 0
    while position < len(raw):
        token = _KEY_PART.match(raw, position)
        if token is None:
            return None
        parts.append(token.group("quoted") or token.group("literal") or token.group("bare") or "")
        position = token.end()
        if position < len(raw):
            if raw[position] != ".":
                return None
            position += 1
    return tuple(parts)


def _to_toml(entry: dict[str, Any]) -> dict[str, Any]:
    native = {key: value for key, value in entry.items() if key != "headers"}
    if "headers" in entry:
        native["http_headers"] = entry["headers"]
    return native


def _from_toml(entry: dict[str, Any]) -> dict[str, Any]:
    neutral = {key: value for key, value in entry.items() if key != "http_headers"}
    if "http_headers" in entry:
        neutral["headers"] = entry["http_headers"]
    return neutral


def _value(value: Any) -> str:
    if isinstance(value, dict):
        inner = ", ".join(f"{json.dumps(str(key))} = {_value(item)}" for key, item in value.items())
        return "{ " + inner + " }" if inner else "{}"
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def _table(entry: dict[str, Any]) -> list[str]:
    lines = [f"[{_CONTAINER}.{json.dumps(STUDIO_MCP_SERVER_NAME)}]"]
    lines += [f"{json.dumps(key)} = {_value(value)}" for key, value in entry.items()]
    return lines


def _load(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise AdapterRefusal("invalid_toml") from None


def _servers(data: dict[str, Any]) -> dict[str, Any]:
    servers = data.get(_CONTAINER, {})
    if not isinstance(servers, dict):
        raise AdapterRefusal("unexpected_shape")
    return servers


def _replace_table(text: str, entry: dict[str, Any] | None) -> str:
    """`text` with the Studi'OS table replaced by `entry` (removed when None)."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    owned = (_CONTAINER, STUDIO_MCP_SERVER_NAME)
    start: int | None = None
    end = len(lines)
    for index, line in enumerate(lines):
        path = _header_path(line)
        if path is None:
            continue
        ours = path[:2] == owned
        if start is None:
            if ours:
                if len(path) != 2:
                    raise AdapterRefusal("unsupported_layout")
                start = index
        elif not ours:
            end = index
            break
    if start is not None:
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
    before = _load(text)
    present = STUDIO_MCP_SERVER_NAME in _servers(before)
    if present and start is None:
        raise AdapterRefusal("unsupported_layout")
    block = [] if entry is None else _table(entry)
    if start is None:
        if entry is None:
            return text
        head = lines[:]
        if head and head[-1].strip():
            head.append("")
        merged = head + block
    else:
        merged = lines[:start] + block + lines[end:]
    result = newline.join(merged) + newline
    expected = json.loads(json.dumps(before))
    servers = expected.setdefault(_CONTAINER, {})
    if entry is None:
        servers.pop(STUDIO_MCP_SERVER_NAME, None)
        if not servers:
            expected.pop(_CONTAINER, None)
    else:
        servers[STUDIO_MCP_SERVER_NAME] = entry
    if json.loads(json.dumps(_load(result))) != expected:
        raise AdapterRefusal("edit_verification_failed")
    return result


class CodexAdapter(JsonMcpAdapter):
    adapter_id = "codex"
    harness_id = "codex"
    display_name = "Codex"
    executable_names = ("codex",)
    identity = re.compile(r"^codex-cli\s+(?P<version>\d+\.\d+\.\d+)")
    supported_major = 0
    project_files = ()
    container_path = (_CONTAINER,)

    def _config_dir(self, ctx: HarnessContext) -> str:
        raw = ctx.env_value("CODEX_HOME")
        if not raw:
            return ".codex"
        try:
            relative = Path(raw).resolve().relative_to(ctx.home.resolve())
        except (OSError, ValueError):
            raise AdapterRefusal("unsupported_config_home") from None
        if not relative.parts:
            raise AdapterRefusal("unsupported_config_home")
        return str(PurePosixPath(*relative.parts))

    def user_target(self, ctx: HarnessContext) -> str:
        return f"{self._config_dir(ctx)}/{_CONFIG_NAME}"

    def _document(self, ctx: HarnessContext) -> Document | None:
        return read_document(resolve_target(ctx.home, self.user_target(ctx)))

    def read_user_entry(self, ctx: HarnessContext) -> dict[str, Any] | None:
        document = self._document(ctx)
        if document is None:
            return None
        entry = _servers(_load(document.text)).get(STUDIO_MCP_SERVER_NAME)
        if entry is None:
            return None
        if not isinstance(entry, dict):
            raise AdapterRefusal("unexpected_shape")
        return _from_toml(entry)

    def _edit(self, ctx: HarnessContext, entry: dict[str, Any] | None) -> None:
        try:
            target = self.user_target(ctx)
            document = self._document(ctx)
            if document is None and entry is None:
                return
            native = None if entry is None else _to_toml(entry)
            text = _replace_table("" if document is None else document.text, native)
            path = resolve_target(ctx.home, target)
            if path.exists() and not is_writable(path):
                raise AdapterRefusal("read_only")
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, encode_text(text, bom=False if document is None else document.bom))
        except FsError as error:
            raise AdapterRefusal(error.reason) from None
        except OSError:
            raise AdapterRefusal("write_failed") from None

    def write_user_entry(self, ctx: HarnessContext, entry: dict[str, object]) -> None:
        self._edit(ctx, dict(entry))

    def remove_user_entry(self, ctx: HarnessContext) -> None:
        self._edit(ctx, None)

    def build_entry(self, mcp_url: str, token: str) -> dict[str, object]:
        return {"url": mcp_url, "headers": {"Authorization": f"Bearer {token}"}}

    def headless_argv(self, prompt: str) -> tuple[str, ...]:
        return ("-a", "never", "exec", "--sandbox", "workspace-write", prompt)
