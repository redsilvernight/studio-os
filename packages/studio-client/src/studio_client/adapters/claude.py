from __future__ import annotations

from typing import Any

from studio_contracts.resolution import ResolvedAgentDefinition

from studio_client.adapters.base import (
    CAPABILITY_DIMENSIONS,
    AdapterArtifact,
    AdapterError,
    AdapterErrorCode,
    AdapterResult,
    AdapterWarning,
    CapabilitySupport,
    agent_summary,
    capability_notes,
    check_harness_compatible,
    ensure_supported,
    render_frontmatter,
    render_shared_body,
    sanitize_agent_filename,
    yaml_quoted,
)

ADAPTER_ID = "claude-code"
MANAGED_DIR = ".claude/agents"

TOOL_DISPLAY_NAMES = {
    "read": "Read",
    "grep": "Grep",
    "glob": "Glob",
    "bash": "Bash",
    "powershell": "PowerShell",
}
"""Canonical tool needs → Claude Code allowlist labels (P3.4: pure mapping,
no invented allowlist — unknown needs are dropped with a warning)."""


class ClaudeCodeAdapter:
    """Local projection of a canonical definition to Claude Code (P10).

    Target format observed in-repo (`.claude/agents/*.md`, non-normative):
    `name`/`description` frontmatter plus a Markdown body. Reads the
    canonical input only — never selects a runtime, never branches on a
    provider or model value, never touches the network."""

    adapter_id = ADAPTER_ID
    managed_dir = MANAGED_DIR

    def capabilities(self) -> dict[str, CapabilitySupport]:
        """Claude Code projection surface (P3.5): native subagents, tool
        allowlist, model pin — everything the canonical definition needs."""
        return dict.fromkeys(CAPABILITY_DIMENSIONS, CapabilitySupport.SUPPORTED)

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
        content_map = resolved.agent.content
        edit_policy = content_map.get("edit_policy")
        edit_policy_str = edit_policy if isinstance(edit_policy, str) else None
        ensure_supported(self.adapter_id, self.capabilities(), edit_policy=edit_policy_str)

        stem = sanitize_agent_filename(resolved.agent.stable_key)
        description = agent_summary(resolved)
        if len(description) > 300:
            description = description[:297] + "..."
        model_ref = resolved.runtime.target.model_ref if resolved.runtime is not None else None

        tools = content_map.get("tools")
        tool_labels: str | None = None
        unknown_tools: list[str] = []
        if isinstance(tools, list) and tools:
            known = [TOOL_DISPLAY_NAMES[t] for t in tools if t in TOOL_DISPLAY_NAMES]
            unknown_tools = [t for t in tools if t not in TOOL_DISPLAY_NAMES]
            if known:
                tool_labels = ", ".join(known)
        frontmatter = render_frontmatter(
            [
                ("name", yaml_quoted(stem)),
                ("description", yaml_quoted(description or stem)),
                ("model", yaml_quoted(model_ref) if model_ref is not None else None),
                ("tools", tool_labels),
            ]
        )
        body, warnings = render_shared_body(resolved, adapter_id=self.adapter_id, context=context)
        content = f"{frontmatter}\n\n{body}"
        if unknown_tools:
            warnings = [
                *warnings,
                AdapterWarning(
                    "tools_not_projected",
                    "canonical tool needs without Claude mapping dropped: "
                    f"{unknown_tools}",
                ),
            ]
        warnings = [
            *warnings,
            *capability_notes(self.adapter_id, self.capabilities(), edit_policy=edit_policy_str),
        ]
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
