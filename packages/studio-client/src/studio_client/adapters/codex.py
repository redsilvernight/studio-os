from __future__ import annotations

from typing import Any

from studio_contracts.resolution import ResolvedAgentDefinition

from studio_client.adapters.base import (
    CAPABILITY_DIMENSIONS,
    AdapterArtifact,
    AdapterError,
    AdapterErrorCode,
    AdapterResult,
    CapabilitySupport,
    agent_summary,
    capability_notes,
    check_harness_compatible,
    ensure_supported,
    render_shared_body,
    sanitize_agent_filename,
)

ADAPTER_ID = "codex"
MANAGED_DIR = ".codex/agents"


def _toml_string(value: str) -> str:
    """Double-quoted TOML basic string, single-quoted only when safe —
    deterministic: same value always renders the same way."""
    if '"' not in value and "\\" not in value and "\n" not in value and "'" in value:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_single(value: str) -> str:
    if "'" not in value and "\n" not in value:
        return f"'{value}'"
    return _toml_string(value)


class CodexAdapter:
    """Local projection of a canonical definition to Codex (P3).

    Target format observed in-repo (`.codex/agents/*.toml`,
    non-normative): `name`/`description`/`model`/`model_reasoning_effort`
    keys plus a `developer_instructions` literal block. Reads the
    canonical input only — never selects a runtime, never branches on a
    provider or model value, never touches the network. Reasoning effort
    comes from the resolved model-profile requirements (open string),
    never from a pinned model."""

    adapter_id = ADAPTER_ID
    managed_dir = MANAGED_DIR

    def capabilities(self) -> dict[str, CapabilitySupport]:
        """Codex projection surface (P3.5): the TOML format carries no
        permission or shell declaration, so those stay degraded (harness
        defaults + instruction); everything else projects losslessly."""
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
        effort = resolved.requirements.reasoning

        lines = [
            f"name = {_toml_string(stem)}",
            f"description = {_toml_string(description or stem)}",
        ]
        if model_ref is not None:
            lines.append(f"model = {_toml_single(model_ref)}")
        if effort:
            lines.append(f"model_reasoning_effort = {_toml_single(effort)}")
        body, warnings = render_shared_body(resolved, adapter_id=self.adapter_id, context=context)
        lines += ["developer_instructions = '''", body, "'''", ""]
        content = "\n".join(lines) + "\n"
        warnings = [
            *warnings,
            *capability_notes(self.adapter_id, self.capabilities(), edit_policy=edit_policy_str),
        ]
        artifact = AdapterArtifact(path=f"{MANAGED_DIR}/{stem}.toml", content=content)
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
