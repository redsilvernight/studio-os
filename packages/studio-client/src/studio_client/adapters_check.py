"""Anti-drift gate (P3.7) as a function: managed harness files must equal a
fresh projection of the Library bundle. Shared by ``studio-client adapters
check`` and the Desktop setup report; never writes, never merges."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from studio_client.projection_source import ProjectionBundle


@dataclass(frozen=True)
class AdaptersCheck:
    checked: int
    failures: tuple[dict[str, str], ...]


def check_adapters(
    root: Path,
    bundle: ProjectionBundle,
    *,
    adapter_id: str | None = None,
    stable_key: str | None = None,
) -> AdaptersCheck:
    from studio_client.adapters import AdapterError, get_adapter, list_adapters
    from studio_client.canonical import (
        agents_rules_current_with,
        legacy_rules_text,
        render_agents_rules_block_from,
        render_claude_rule,
        skill_projections_from,
    )

    adapter_ids = [adapter_id] if adapter_id else list_adapters()
    keys = [stable_key] if stable_key else list(bundle.agents)
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
                result = adapter.translate(bundle.agents[key])
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
        for key, (applies_to, body) in sorted(bundle.rules.items()):
            checked += 1
            current = root / ".claude" / "rules" / f"{key}.md"
            on_disk = (
                current.read_text(encoding="utf-8").replace("\r\n", "\n")
                if current.is_file()
                else None
            )
            if on_disk != render_claude_rule(key, applies_to, body):
                failures.append({"adapter": "rules", "key": key, "error": f"drifted: {current}"})
        checked += 1
        agents_path = root / "AGENTS.md"
        agents_text = agents_path.read_text(encoding="utf-8") if agents_path.is_file() else ""
        block = render_agents_rules_block_from(bundle.protocol is not None)
        if not agents_rules_current_with(block, legacy_rules_text(bundle.rules), agents_text):
            failures.append(
                {
                    "adapter": "rules",
                    "key": "*",
                    "error": "AGENTS.md block drifted, duplicated or conflicting owner",
                }
            )
        for relative, content in skill_projections_from(bundle.skills, bundle.skill_files).items():
            checked += 1
            target = root / relative
            if not target.is_file() or target.read_text(encoding="utf-8") != content:
                failures.append({"adapter": "skills", "key": "*", "error": f"drifted: {relative}"})
    return AdaptersCheck(checked=checked, failures=tuple(failures))
