"""OpenCode: Studi'OS is declared under `mcp` in the global configuration,
`<config home>/opencode/opencode.json[c]`, edited in place so that comments,
trailing commas and every other setting survive. A project-scoped entry in
`<workspace>/opencode.json[c]` would shadow it and is migrated away.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from studio_client.harness import jsonc
from studio_client.harness.base import AdapterRefusal, HarnessContext
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

_CONFIG_NAMES = ("opencode.json", "opencode.jsonc")


class OpenCodeAdapter(JsonMcpAdapter):
    adapter_id = "opencode"
    harness_id = "opencode"
    display_name = "OpenCode"
    executable_names = ("opencode",)
    identity = re.compile(r"^(?P<version>\d+\.\d+\.\d+)$")
    supported_major = 1
    project_files = _CONFIG_NAMES
    container_path = ("mcp",)
    comments = True
    trailing_commas = True

    def _config_dir(self, ctx: HarnessContext) -> str:
        """The configuration directory relative to the home directory. A config
        home outside it is not something Studi'OS writes to."""
        raw = ctx.env_value("XDG_CONFIG_HOME")
        if not raw:
            return ".config/opencode"
        try:
            relative = Path(raw).resolve().relative_to(ctx.home.resolve())
        except (OSError, ValueError):
            raise AdapterRefusal("unsupported_config_home") from None
        return str(PurePosixPath(*relative.parts, "opencode"))

    def _user_file(self, ctx: HarnessContext) -> tuple[str, Document | None]:
        directory = self._config_dir(ctx)
        found: list[tuple[str, Document]] = []
        for name in _CONFIG_NAMES:
            target = f"{directory}/{name}"
            document = read_document(resolve_target(ctx.home, target))
            if document is not None:
                found.append((target, document))
        if len(found) > 1:
            raise AdapterRefusal("ambiguous_config")
        return found[0] if found else (f"{directory}/{_CONFIG_NAMES[0]}", None)

    def user_target(self, ctx: HarnessContext) -> str:
        return self._user_file(ctx)[0]

    def _parse(self, text: str) -> jsonc.Node:
        root = jsonc.parse(text, comments=True, trailing_commas=True)
        if root.kind != "object":
            raise jsonc.JsoncError("unexpected_shape", "root is not an object")
        return root

    def read_user_entry(self, ctx: HarnessContext) -> dict[str, Any] | None:
        _, document = self._user_file(ctx)
        if document is None:
            return None
        node = jsonc.lookup(self._parse(document.text), self._entry_path)
        if node is None:
            return None
        entry = jsonc.to_python(node)
        if not isinstance(entry, dict):
            raise AdapterRefusal("unexpected_shape")
        return entry

    def _write(self, ctx: HarnessContext, target: str, data: bytes) -> None:
        path = resolve_target(ctx.home, target)
        if path.exists() and not is_writable(path):
            raise AdapterRefusal("read_only")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, data)

    def write_user_entry(self, ctx: HarnessContext, entry: dict[str, object]) -> None:
        try:
            target, document = self._user_file(ctx)
            if document is None:
                nested: Any = entry
                for key in reversed(self._entry_path):
                    nested = {key: nested}
                text = json.dumps(nested, indent=2, ensure_ascii=False) + "\n"
                bom = False
            else:
                self._parse(document.text)
                text = jsonc.upsert(
                    document.text, self._entry_path, entry, comments=True, trailing_commas=True
                )
                bom = document.bom
            jsonc.verify_edit(
                None if document is None else document.text,
                text,
                self._entry_path,
                entry,
                comments=True,
                trailing_commas=True,
            )
            self._write(ctx, target, encode_text(text, bom=bom))
        except jsonc.JsoncError as error:
            raise AdapterRefusal(error.code) from None
        except FsError as error:
            raise AdapterRefusal(error.reason) from None
        except OSError:
            raise AdapterRefusal("write_failed") from None

    def remove_user_entry(self, ctx: HarnessContext) -> None:
        try:
            target, document = self._user_file(ctx)
            if (
                document is None
                or jsonc.lookup(self._parse(document.text), self._entry_path) is None
            ):
                return
            text = jsonc.remove(
                document.text, self._entry_path, comments=True, trailing_commas=True
            )
            jsonc.verify_removal(
                document.text, text, self._entry_path, comments=True, trailing_commas=True
            )
            self._write(ctx, target, encode_text(text, bom=document.bom))
        except jsonc.JsoncError as error:
            raise AdapterRefusal(error.code) from None
        except FsError as error:
            raise AdapterRefusal(error.reason) from None
        except OSError:
            raise AdapterRefusal("write_failed") from None

    def build_entry(self, mcp_url: str, token: str) -> dict[str, object]:
        return {
            "type": "remote",
            "url": mcp_url,
            "enabled": True,
            "oauth": False,
            "headers": {"Authorization": f"Bearer {token}"},
        }
