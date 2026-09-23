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
    render_shared_body,
    sanitize_agent_filename,
    yaml_quoted,
)

ADAPTER_ID = "opencode"
MANAGED_DIR = ".opencode/agents"


class OpenCodeAdapter:
    """Local projection of a canonical definition to OpenCode (P10).

    Target format observed in-repo (`.opencode/agents/*.md`,
    non-normative): `description`/`mode` frontmatter plus a Markdown
    body. Consumes exactly the same canonical input as
    `ClaudeCodeAdapter` — never a Claude intermediate. Reads only:
    no runtime selection, no provider/model branching, no network."""

    adapter_id = ADAPTER_ID
    managed_dir = MANAGED_DIR

    def capabilities(self) -> dict[str, CapabilitySupport]:
        """OpenCode projection surface (P3.5): subagents, model pin and
        default-deny editing project fine; shell execution and fine-grained
        permissions stay degraded (bash-only, technically unrestrictable)."""
        caps = dict.fromkeys(CAPABILITY_DIMENSIONS, CapabilitySupport.SUPPORTED)
        caps["permissions"] = CapabilitySupport.DEGRADED
        caps["shell_execution"] = CapabilitySupport.DEGRADED
        return caps

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

        fields = [
            ("description", yaml_quoted(description or stem)),
            ("mode", "subagent"),
            ("model", yaml_quoted(model_ref) if model_ref is not None else None),
        ]
        lines = ["---"]
        for key, value in fields:
            if value is not None:
                lines.append(f"{key}: {value}")
        if edit_policy_str in ("deny", "ask"):
            lines += ["permission:", f"  edit: {edit_policy_str}"]
        lines.append("---")
        frontmatter = "\n".join(lines)
        body, warnings = render_shared_body(resolved, adapter_id=self.adapter_id, context=context)
        content = f"{frontmatter}\n\n{body}"
        if edit_policy_str in ("deny", "ask"):
            policy_note = (
                f"canonical read-only policy projected as harness `edit: {edit_policy_str}`"
            )
        else:
            policy_note = "no canonical edit policy; harness defaults apply"
        warnings = [
            *warnings,
            AdapterWarning("permissions_defaulted", policy_note + " (bash unrestrictable)"),
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
