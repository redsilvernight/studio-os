from __future__ import annotations

from typing import Any

from studio_contracts.resolution import ResolvedAgentDefinition

from studio_client.adapters.base import (
    AdapterArtifact,
    AdapterError,
    AdapterErrorCode,
    AdapterResult,
    AdapterWarning,
    agent_summary,
    check_harness_compatible,
    render_frontmatter,
    render_shared_body,
    sanitize_agent_filename,
    yaml_quoted,
)

ADAPTER_ID = "claude-code"
MANAGED_DIR = ".claude/agents"


class ClaudeCodeAdapter:
    """Local projection of a canonical definition to Claude Code (P10).

    Target format observed in-repo (`.claude/agents/*.md`, non-normative):
    `name`/`description` frontmatter plus a Markdown body. Reads the
    canonical input only — never selects a runtime, never branches on a
    provider or model value, never touches the network."""

    adapter_id = ADAPTER_ID
    managed_dir = MANAGED_DIR

    def translate(
        self,
        resolved: ResolvedAgentDefinition,
        *,
        context: Any | None = None,
    ) -> AdapterResult:
        if not isinstance(resolved, ResolvedAgentDefinition):
            raise AdapterError(
                AdapterErrorCode.INVALID_CANONICAL,
                f"expected ResolvedAgentDefinition, got {type(resolved).__name__}",
                {"type": type(resolved).__name__},
            )
        check_harness_compatible(self.adapter_id, resolved)

        stem = sanitize_agent_filename(resolved.agent.stable_key)
        description = agent_summary(resolved)
        if len(description) > 300:
            description = description[:297] + "..."
        model_ref = resolved.runtime.target.model_ref if resolved.runtime is not None else None

        frontmatter = render_frontmatter(
            [
                ("name", yaml_quoted(stem)),
                ("description", yaml_quoted(description or stem)),
                ("model", yaml_quoted(model_ref) if model_ref is not None else None),
            ]
        )
        body, warnings = render_shared_body(resolved, adapter_id=self.adapter_id, context=context)
        content = f"{frontmatter}\n\n{body}"
        profile = resolved.model_profile
        if profile is not None and profile.requirements.tools_required:
            warnings = [
                *warnings,
                AdapterWarning(
                    "tools_not_projected",
                    "capability `tools_required` stays descriptive; no harness allowlist invented",
                ),
            ]
        artifact = AdapterArtifact(path=f"{MANAGED_DIR}/{stem}.md", content=content)
        metadata: dict[str, object] = {
            "stable_key": resolved.agent.stable_key,
            "agent_version": resolved.agent.version,
            "harness": self.adapter_id,
            "model_projected": model_ref is not None,
        }
        return AdapterResult(
            adapter_id=self.adapter_id,
            artifacts=(artifact,),
            warnings=tuple(warnings),
            metadata=metadata,
        )
