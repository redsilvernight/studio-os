"""Anti-drift gate (P3.7) as a function: managed harness files must equal a
fresh export of the canonical definitions. Shared by ``studio-client adapters
check`` and the Desktop setup report; never writes, never merges."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LibraryFor = Callable[[str], Any]


@dataclass(frozen=True)
class AdaptersCheck:
    checked: int
    failures: tuple[dict[str, str], ...]


def has_canonical_definitions(root: Path) -> bool:
    """False for a folder that carries no canonical definitions: nothing to check."""
    return (root / ".agents").is_dir()


def check_adapters(
    root: Path,
    *,
    adapter_id: str | None = None,
    stable_key: str | None = None,
    library_for: LibraryFor | None = None,
) -> AdaptersCheck:
    from studio_client.adapters import AdapterError, get_adapter, list_adapters
    from studio_client.canonical import (
        build_merged_resolved,
        build_offline_resolved,
        canonical_agent_keys,
        canonical_rule_keys,
        load_rule_meta,
        render_agents_rules_block,
        render_claude_rule,
    )

    adapter_ids = [adapter_id] if adapter_id else list_adapters()
    keys = [stable_key] if stable_key else canonical_agent_keys(root)
    failures: list[dict[str, str]] = []
    checked = 0
    for current_adapter in adapter_ids:
        try:
            adapter = get_adapter(current_adapter)
        except AdapterError as exc:
            failures.append({"adapter": current_adapter, "key": "*", "error": exc.message})
            continue
        for key in keys:
            checked += 1
            try:
                if library_for is not None:
                    resolved = build_merged_resolved(root, key, library=library_for(key))
                else:
                    resolved = build_offline_resolved(root, key)
                result = adapter.translate(resolved)
            except (AdapterError, ValueError, OSError) as exc:
                failures.append({"adapter": current_adapter, "key": key, "error": str(exc)})
                continue
            for artifact in result.artifacts:
                current = root / artifact.path
                on_disk = (
                    current.read_text(encoding="utf-8").replace("\r\n", "\n")
                    if current.is_file()
                    else None
                )
                if on_disk != artifact.content:
                    failures.append(
                        {
                            "adapter": current_adapter,
                            "key": key,
                            "error": f"drifted or missing: {artifact.path}",
                        }
                    )
    if adapter_id is None and stable_key is None:
        # Rule projections and the AGENTS.md block are managed too (P3.7).
        for key in canonical_rule_keys(root):
            checked += 1
            applies_to, body = load_rule_meta(root, key)
            current = root / ".claude" / "rules" / f"{key}.md"
            on_disk = (
                current.read_text(encoding="utf-8").replace("\r\n", "\n")
                if current.is_file()
                else None
            )
            if on_disk != render_claude_rule(key, applies_to, body):
                failures.append({"adapter": "rules", "key": key, "error": f"drifted: {current}"})
        checked += 1
        agents_text = (root / "AGENTS.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        expected = render_agents_rules_block(root)
        if expected.rstrip("\n") not in agents_text:
            failures.append({"adapter": "rules", "key": "*", "error": "AGENTS.md block drifted"})
    return AdaptersCheck(checked=checked, failures=tuple(failures))
