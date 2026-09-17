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
                ("description", yaml_quoted(description or stem)),
                ("mode", "subagent"),
                ("model", yaml_quoted(model_ref) if model_ref is not None else None),
            ]
        )
        body, warnings = render_shared_body(resolved, adapter_id=self.adapter_id, context=context)
        content = f"{frontmatter}\n\n{body}"
        warnings = [
            *warnings,
            AdapterWarning(
                "permissions_defaulted",
                "canonical definition carries no permission policy; harness defaults apply",
            ),
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
