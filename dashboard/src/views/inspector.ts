/**
 * P12 — Resolution Inspector (the centrepiece).
 *
 * The dashboard has exactly one authority for "what would Studi'OS use":
 * `POST /resolutions`. This view renders the canonical `ResolvedAgentDefinition`
 * and its structured failures as-is; it never ranks scopes, never picks a
 * binding level, never checks compatibility and never falls back on its own.
 */
import type { StudioClient } from "../api";
import type { components } from "../openapi-schema";
import {
  bindingLevelLabel,
  capabilityEntries,
  kindMeta,
  libraryKindHref,
  provenanceReason,
  provenanceSourceLabel,
  relationLabel,
  requirementEntries,
  scopeLabel,
  versionOriginLabel,
  type CapabilityRequirement,
  type LibraryKind,
} from "../libraryFormat";
import { listLibraryResources } from "../libraryApi";
import { postResolution, resolutionErrorView, type ResolvedAgentDefinition, type ResolutionErrorView } from "../resolutionApi";
import { buildBindingCreateTarget } from "./configForms";
import { formReader, type FormReader } from "./libraryForms";
import { uiState } from "../store";
import { describeError, esc, idCell, section, statusBlock } from "../ui";

export interface InspectorContext {
  client: StudioClient;
  authed: boolean;
  stableKey: string | null;
}

type ResolvedRule = components["schemas"]["ResolvedRule"];
type ResolvedSkill = components["schemas"]["ResolvedSkill"];
type ResolvedModelProfile = components["schemas"]["ResolvedModelProfile"];
type ResolvedRuntime = components["schemas"]["ResolvedRuntime"];

export interface InspectorOverrideInput {
  targetKind: string;
  stableKey: string;
  runtimeId: string;
  machineId: string;
  harnessRef: string;
  providerRef: string;
  modelRef: string;
}

export interface InspectorInput {
  stableKey: string;
  projectId: string;
  enableOverride: boolean;
  override: InspectorOverrideInput;
}

export type InspectorBuildResult = { ok: true; value: components["schemas"]["AgentResolutionRequest"] } | { ok: false; error: string };

/** Builds the canonical resolution request; ephemeral overrides never persist. */
export function buildResolutionRequest(input: InspectorInput): InspectorBuildResult {
  const stableKey = input.stableKey.trim();
  if (stableKey === "") return { ok: false, error: "an AgentDefinition stable key is required" };
  const projectId = input.projectId.trim();
  const overrides: components["schemas"]["SessionRuntimeOverride"][] = [];
  if (input.enableOverride) {
    const overrideKey = input.override.stableKey.trim();
    const kind = input.override.targetKind;
    if (kind !== "agent_definition" && kind !== "model_profile") {
      return { ok: false, error: "session override target kind must be agent_definition or model_profile" };
    }
    if (overrideKey === "") return { ok: false, error: "session override needs a target stable key" };
    const target = buildBindingCreateTarget(input.override);
    if (target === null) {
      return { ok: false, error: "session override needs a runtime id or at least one inline anchor" };
    }
    overrides.push({ target_kind: kind as LibraryKind, target_stable_key: overrideKey, target });
  }
  const value: components["schemas"]["AgentResolutionRequest"] = { stable_key: stableKey, session_overrides: overrides };
  if (projectId !== "") value.project_id = projectId;
  return { ok: true, value };
}

function link(kind: LibraryKind, resourceId: string, label: string): string {
  return `<a href="${esc(libraryKindHref(kind, resourceId))}"><code class="mono">${esc(label)}</code></a>`;
}

export function inspectorFormHtml(stableKey: string | null, projectId: string | null, agentKeys: string[]): string {
  const options = agentKeys.map((key) => `<option value="${esc(key)}"></option>`).join("");
  return (
    `<form class="stack-form" data-resolve>` +
    `<label class="stack">Agent Definition stable key <input name="stable_key" list="agent-keys" value="${esc(stableKey ?? "")}" placeholder="review-helper" required /></label>` +
    `<datalist id="agent-keys">${options}</datalist>` +
    `<label class="stack">Project ID (optional context) <input name="project_id" value="${esc(projectId ?? "")}" placeholder="uuid" /></label>` +
    `<details class="editor"><summary>Temporary session override — not persisted</summary>` +
    `<label class="check">Enable session override <input name="enable_override" type="checkbox" /></label>` +
    `<label class="stack">Target kind <select name="override_target_kind"><option value="agent_definition">Agent Definition</option><option value="model_profile">Model Profile</option></select></label>` +
    `<label class="stack">Target stable key <input name="override_stable_key" placeholder="the resolved key to override" /></label>` +
    `<label class="stack">Runtime registry id <input name="override_runtime_id" placeholder="uuid (exclusive of inline anchors)" /></label>` +
    `<label class="stack">Machine ID <input name="override_machine_id" placeholder="uuid" /></label>` +
    `<label class="stack">Harness ref <input name="override_harness_ref" placeholder="open string" /></label>` +
    `<label class="stack">Provider ref <input name="override_provider_ref" placeholder="open string" /></label>` +
    `<label class="stack">Model ref <input name="override_model_ref" placeholder="open string" /></label>` +
    `<span class="meta">Sent as <code>session_overrides</code> only: no binding, lock or runtime is created or modified.</span></details>` +
    `<button type="submit">Resolve</button>` +
    `<span class="meta">POST /resolutions · pure read · decisions come from the server</span>` +
    `<div data-msg class="meta"></div></form>`
  );
}

function identityHtml(resolved: ResolvedAgentDefinition): string {
  const agent = resolved.agent;
  const deprecated = agent.deprecated ? ' <span class="status bad">deprecated</span>' : "";
  return (
    `<div class="detail-grid">` +
    `<div>AgentDefinition <code class="mono">${esc(agent.stable_key)}</code>${deprecated}</div>` +
    `<div>Effective version: <strong>v${agent.version}</strong> · origin: ${esc(versionOriginLabel(agent.version_origin))} · scope: ${esc(scopeLabel(agent.scope))}</div>` +
    `<div class="meta">resource ${esc(agent.resource_id)}${agent.title !== "" ? ` · ${esc(agent.title)}` : ""}</div>` +
    `<div>Why: ${esc(provenanceReason(agent.provenance))}</div></div>`
  );
}

function rulePathsHtml(rule: ResolvedRule): string {
  if (rule.paths.length === 0) return '<span class="meta">direct</span>';
  return rule.paths
    .map(
      (path) =>
        `${esc(relationLabel(path.relation))} via ${esc(kindMeta(path.via_kind).singular)} <code class="mono">${esc(path.via_stable_key)}</code> v${path.via_version}`,
    )
    .join("<br />");
}

export function rulesTableHtml(rules: ResolvedRule[] | undefined): string {
  const list = rules ?? [];
  if (list.length === 0) return statusBlock("empty", "No rule resolved.");
  const rows = list
    .map(
      (rule) =>
        `<tr><td>${link("rule", rule.resource_id, rule.stable_key)}${rule.deprecated ? ' <span class="status bad">deprecated</span>' : ""}</td>` +
        `<td>v${rule.version}</td><td>${esc(versionOriginLabel(rule.version_origin))}</td><td>${esc(scopeLabel(rule.scope))}</td>` +
        `<td>${rulePathsHtml(rule)}</td></tr>`,
    )
    .join("");
  return `<table><thead><tr><th>Rule</th><th>Version</th><th>Origin</th><th>Scope</th><th>Path / reason</th></tr></thead><tbody>${rows}</tbody></table>`;
}

export function skillsTableHtml(skills: ResolvedSkill[] | undefined): string {
  const list = skills ?? [];
  if (list.length === 0) return statusBlock("empty", "No skill resolved.");
  const rows = list
    .map(
      (skill) =>
        `<tr><td>${link("skill", skill.resource_id, skill.stable_key)}${skill.deprecated ? ' <span class="status bad">deprecated</span>' : ""}</td>` +
        `<td>v${skill.version}</td><td>${esc(versionOriginLabel(skill.version_origin))}</td><td>${esc(scopeLabel(skill.scope))}</td>` +
        `<td>${esc(provenanceReason(skill.provenance))}</td></tr>`,
    )
    .join("");
  return `<table><thead><tr><th>Skill</th><th>Version</th><th>Origin</th><th>Scope</th><th>Reason</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function entriesTable(entries: { label: string; value: string }[], emptyMessage: string): string {
  if (entries.length === 0) return `<span class="meta">${esc(emptyMessage)}</span>`;
  const rows = entries.map((entry) => `<tr><td>${esc(entry.label)}</td><td><code class="mono">${esc(entry.value)}</code></td></tr>`).join("");
  return `<table><thead><tr><th>Dimension</th><th>Value</th></tr></thead><tbody>${rows}</tbody></table>`;
}

export function modelProfileHtml(profile: ResolvedModelProfile | null | undefined): string {
  if (profile == null) return statusBlock("empty", "No ModelProfile linked: this AgentDefinition expresses no capability requirement.");
  return (
    `<div class="detail-grid"><div>Model Profile ${link("model_profile", profile.resource_id, profile.stable_key)} v${profile.version}` +
    `${profile.deprecated ? ' <span class="status bad">deprecated</span>' : ""}</div>` +
    `<div>Origin: ${esc(versionOriginLabel(profile.version_origin))} · scope: ${esc(scopeLabel(profile.scope))} · reason: ${esc(provenanceReason(profile.provenance))}</div></div>`
  );
}

export function runtimeHtml(runtime: ResolvedRuntime | null | undefined): string {
  if (runtime == null) {
    return statusBlock("empty", "No runtime binding selected — canonical definition resolved. This is a valid outcome, not a failure.");
  }
  const target = runtime.target;
  const refs = [
    target.runtime_id !== null && target.runtime_id !== undefined
      ? `Runtime registry: <a href="#/configuration/runtimes/${esc(target.runtime_id)}"><code class="mono">${esc(target.runtime_id)}</code></a>`
      : null,
    target.harness_ref !== null && target.harness_ref !== undefined ? `Harness: <code class="mono">${esc(target.harness_ref)}</code>` : null,
    target.provider_ref !== null && target.provider_ref !== undefined ? `Provider: <code class="mono">${esc(target.provider_ref)}</code>` : null,
    target.model_ref !== null && target.model_ref !== undefined ? `Model: <code class="mono">${esc(target.model_ref)}</code>` : null,
    target.machine_id !== null && target.machine_id !== undefined ? `Machine: ${idCell(target.machine_id)}` : null,
  ]
    .filter((part): part is string => part !== null)
    .join(" · ");
  return (
    `<div class="detail-grid">` +
    `<div>Selected runtime selection — binding level: <strong>${esc(bindingLevelLabel(runtime.level))}</strong></div>` +
    `<div>Matched key: ${esc(kindMeta(runtime.matched_kind).singular)} <code class="mono">${esc(runtime.matched_stable_key)}</code></div>` +
    `<div>${refs}</div>` +
    `<div>Capabilities: ${entriesTable(capabilityEntries(target.capabilities), "none declared")}</div>` +
    `<div>Reason: ${runtime.provenance != null ? esc(provenanceReason(runtime.provenance)) : '<span class="meta">—</span>'}</div></div>`
  );
}

/** Requirements vs runtime capabilities, with the canonical verdict. */
export function compatibilityComparisonHtml(resolved: ResolvedAgentDefinition): string {
  const requirements = entriesTable(requirementEntries(resolved.requirements as CapabilityRequirement), "No requirement expressed.");
  const runtime = resolved.runtime;
  if (runtime == null) {
    return `${requirements}<p class="meta">No runtime selected, so compatibility is not evaluated.</p>`;
  }
  const capabilities = entriesTable(capabilityEntries(runtime.target.capabilities), "none declared");
  const unsatisfied = runtime.unsatisfied ?? [];
  const verdict =
    unsatisfied.length === 0
      ? `<p class="status ok">Compatible</p>`
      : `<p class="status bad">Unsatisfied: ${unsatisfied.map((item) => esc(item)).join(" · ")}</p>`;
  return (
    `<div class="compare"><div><h4>Requirements (ModelProfile)</h4>${requirements}</div>` +
    `<div><h4>Runtime capabilities (declared)</h4>${capabilities}</div></div>${verdict}`
  );
}

export function provenanceReasonsHtml(resolved: ResolvedAgentDefinition): string {
  const parts: string[] = [];
  parts.push(`<div><strong>Why this version?</strong> ${esc(provenanceReason(resolved.agent.provenance))}</div>`);
  for (const rule of resolved.rules ?? []) {
    parts.push(`<div><strong>Why rule ${esc(rule.stable_key)}?</strong> v${rule.version} · ${rulePathsHtml(rule)}</div>`);
  }
  for (const skill of resolved.skills ?? []) {
    parts.push(`<div><strong>Why skill ${esc(skill.stable_key)}?</strong> ${esc(provenanceReason(skill.provenance))}</div>`);
  }
  if (resolved.model_profile != null) {
    parts.push(`<div><strong>Why this ModelProfile?</strong> ${esc(provenanceReason(resolved.model_profile.provenance))}</div>`);
  }
  if (resolved.runtime != null) {
    const provenance = resolved.runtime.provenance;
    parts.push(
      `<div><strong>Which binding won?</strong> ${esc(bindingLevelLabel(resolved.runtime.level))}` +
        `${provenance != null ? ` · source: ${esc(provenanceSourceLabel(provenance.source))}` : ""}</div>`,
    );
  } else {
    parts.push(`<div><strong>Which binding won?</strong> none — no applicable runtime binding.</div>`);
  }
  return `<div class="reasons">${parts.join("")}</div>`;
}

export function resolutionFailureHtml(view: ResolutionErrorView, resolved: ResolvedAgentDefinition | null = null): string {
  if (resolved !== null) return "";
  if (view.code === "runtime_incompatible") {
    return (
      `<div class="state error"><strong>Resolution failed · runtime_incompatible</strong>` +
      `<div>Selected binding: ${view.bindingLevel !== null ? esc(bindingLevelLabel(view.bindingLevel)) : '<span class="meta">—</span>'}` +
      `${view.matchedKind !== null && view.matchedStableKey !== null ? ` on ${esc(kindMeta(view.matchedKind).singular)} <code class="mono">${esc(view.matchedStableKey)}</code>` : ""}</div>` +
      `<div>Unsatisfied: ${view.unsatisfied.length > 0 ? view.unsatisfied.map((item) => esc(item)).join(" · ") : '<span class="meta">—</span>'}</div>` +
      `<div>No fallback performed — the selected binding stays the selected binding.</div>` +
      `<div class="meta">Fix the runtime capabilities or change the binding; the server will not silently try a lower level.</div></div>`
    );
  }
  if (view.notFound) {
    return (
      `<div class="state error"><strong>Not found · ${esc(view.code ?? "HTTP 404")}</strong>` +
      `<div>The resource does not exist, or it is not visible to this token. The server never reveals which.</div></div>`
    );
  }
  if (view.isAuth) {
    return `<div class="state error"><strong>Not authorised · HTTP ${view.status}</strong><div>${esc(view.message)}</div></div>`;
  }
  return (
    `<div class="state error"><strong>Resolution failed · ${esc(view.code ?? `HTTP ${view.status}`)}</strong>` +
    `${view.reason !== null ? `<div>Reason: <code class="mono">${esc(view.reason)}</code></div>` : ""}<div>${esc(view.message)}</div></div>`
  );
}

export function resolutionResultHtml(resolved: ResolvedAgentDefinition): string {
  return (
    identityHtml(resolved) +
    section("Rules", `${(resolved.rules ?? []).length} resolved`, rulesTableHtml(resolved.rules)) +
    section("Skills", `${(resolved.skills ?? []).length} resolved`, skillsTableHtml(resolved.skills)) +
    section("Model Profile", "requirements", modelProfileHtml(resolved.model_profile)) +
    section("Requirements vs runtime capabilities", "canonical compatibility verdict", compatibilityComparisonHtml(resolved)) +
    section("Runtime", "winning selection", runtimeHtml(resolved.runtime)) +
    section("Why (provenance & reasons)", "from the canonical response", provenanceReasonsHtml(resolved))
  );
}

export async function renderInspector(root: HTMLElement, ctx: InspectorContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = section("Resolution Inspector", "POST /resolutions", statusBlock("empty", "Set a machine token to resolve."));
    return;
  }
  root.innerHTML = section("Resolution Inspector", "POST /resolutions", statusBlock("loading"));
  let agentKeys: string[] = [];
  try {
    const agents = await listLibraryResources(ctx.client, { kind: "agent_definition" });
    agentKeys = agents.map((agent) => agent.stable_key).filter((key, index, all) => all.indexOf(key) === index);
  } catch {
    agentKeys = [];
  }
  const projectId = uiState.selectedProjectId;
  root.innerHTML = section(
    "Resolution Inspector",
    "POST /resolutions · server decides, dashboard displays",
    inspectorFormHtml(ctx.stableKey, projectId, agentKeys) + `<div data-result></div>`,
  );
  bindInspector(root, ctx);
  if (ctx.stableKey !== null && ctx.stableKey !== "") {
    await runResolution(root, ctx);
  }
}

function readInspectorInput(form: HTMLFormElement): InspectorInput {
  const read: FormReader = formReader(form);
  return {
    stableKey: read.text("stable_key"),
    projectId: read.text("project_id"),
    enableOverride: read.checked("enable_override"),
    override: {
      targetKind: read.text("override_target_kind"),
      stableKey: read.text("override_stable_key"),
      runtimeId: read.text("override_runtime_id"),
      machineId: read.text("override_machine_id"),
      harnessRef: read.text("override_harness_ref"),
      providerRef: read.text("override_provider_ref"),
      modelRef: read.text("override_model_ref"),
    },
  };
}

function bindInspector(root: HTMLElement, ctx: InspectorContext): void {
  const form = root.querySelector<HTMLFormElement>("[data-resolve]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = form.querySelector("[data-msg]");
    const built = buildResolutionRequest(readInspectorInput(form));
    if (!built.ok) {
      if (msg !== null) msg.textContent = built.error;
      return;
    }
    if (msg !== null) msg.textContent = "Resolving…";
    void executeResolution(root, ctx, built.value).then((errorText) => {
      if (msg !== null) msg.textContent = errorText;
    });
  });
}

async function runResolution(root: HTMLElement, ctx: InspectorContext): Promise<void> {
  const form = root.querySelector<HTMLFormElement>("[data-resolve]");
  if (form === null) return;
  const built = buildResolutionRequest(readInspectorInput(form));
  const msg = form.querySelector("[data-msg]");
  if (!built.ok) {
    if (msg !== null) msg.textContent = built.error;
    return;
  }
  const errorText = await executeResolution(root, ctx, built.value);
  if (msg !== null) msg.textContent = errorText;
}

/** Renders the canonical response or its structured failure; returns a status
 *  string for the form message. Never throws. */
async function executeResolution(
  root: HTMLElement,
  ctx: InspectorContext,
  request: components["schemas"]["AgentResolutionRequest"],
): Promise<string> {
  const result = root.querySelector("[data-result]");
  if (result === null) return "";
  try {
    const resolved = await postResolution(ctx.client, request);
    result.innerHTML =
      resolutionResultHtml(resolved) +
      `<details class="editor"><summary>Canonical response (JSON)</summary><pre class="code">${esc(JSON.stringify(resolved, null, 2))}</pre></details>`;
    return "Resolved (server result).";
  } catch (error) {
    const view = resolutionErrorView(error);
    result.innerHTML = resolutionFailureHtml(view);
    return view.code ?? describeError(error);
  }
}
