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
import { describeError, esc } from "../ui";
import { dsEmptyState, dsPageHeader, dsSkeleton } from "../ds/ds";
import "./inspector.css";

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

function resourceLink(kind: LibraryKind, resourceId: string, label: string): string {
  return `<a href="${esc(libraryKindHref(kind, resourceId))}"><code class="mono">${esc(label)}</code></a>`;
}

function configLink(href: string, label: string): string {
  return `<a href="${esc(href)}"><code class="mono">${esc(label)}</code></a>`;
}

export function inspectorFormHtml(stableKey: string | null, projectId: string | null, agentKeys: string[]): string {
  const options = agentKeys.map((key) => `<option value="${esc(key)}"></option>`).join("");
  return (
    `<form class="stack-form inspector-form" data-resolve>` +
    `<div class="inspector-form-section">` +
    `<h3>Demande d'inspection</h3>` +
    `<label class="stack">Clé stable AgentDefinition <input name="stable_key" list="agent-keys" value="${esc(stableKey ?? "")}" placeholder="ex : review-helper" required /></label>` +
    `<datalist id="agent-keys">${options}</datalist>` +
    `<label class="stack">ID Projet (contexte optionnel) <input name="project_id" value="${esc(projectId ?? "")}" placeholder="uuid" /></label>` +
    `</div>` +
    `<details class="editor inspector-form-section"><summary>Remplacement de session éphémère — non persisté</summary>` +
    `<label class="check">Activer le remplacement <input name="enable_override" type="checkbox" /></label>` +
    `<label class="stack">Type de cible <select name="override_target_kind"><option value="agent_definition">Agent Definition</option><option value="model_profile">Model Profile</option></select></label>` +
    `<label class="stack">Clé stable cible <input name="override_stable_key" placeholder="clé stable à remplacer" /></label>` +
    `<label class="stack">Runtime registry ID <input name="override_runtime_id" placeholder="uuid (exclusif des ancres inline)" /></label>` +
    `<label class="stack">Machine ID <input name="override_machine_id" placeholder="uuid" /></label>` +
    `<label class="stack">Harness ref <input name="override_harness_ref" placeholder="chaîne ouverte" /></label>` +
    `<label class="stack">Provider ref <input name="override_provider_ref" placeholder="chaîne ouverte" /></label>` +
    `<label class="stack">Model ref <input name="override_model_ref" placeholder="chaîne ouverte" /></label>` +
    `<p class="meta">Envoyé comme <code>session_overrides</code> uniquement : aucun binding, lock ou runtime n'est créé ou modifié.</p>` +
    `</details>` +
    `<button type="submit" class="ds-btn ds-btn--primary">Résoudre</button>` +
    `<span class="meta">POST /resolutions · lecture pure · les décisions viennent du serveur</span>` +
    `<div data-msg class="meta" role="status" aria-live="polite"></div></form>`
  );
}

export function identityHtml(resolved: ResolvedAgentDefinition): string {
  const agent = resolved.agent;
  const deprecated = agent.deprecated ? ' <span class="status bad">Déprécié</span>' : "";
  return (
    `<dl class="detail-grid">` +
    `<dt>AgentDefinition</dt><dd>${resourceLink("agent_definition", agent.resource_id, agent.stable_key)}${deprecated}</dd>` +
    `<dt>Version effective</dt><dd><strong>v${agent.version}</strong> · origine : ${esc(versionOriginLabel(agent.version_origin))} · portée : ${esc(scopeLabel(agent.scope))}</dd>` +
    `<dt>Ressource</dt><dd><code class="mono">${esc(agent.resource_id)}</code>${agent.title !== "" ? ` · ${esc(agent.title)}` : ""}</dd>` +
    `<dt>Provenance</dt><dd>Pourquoi : ${esc(provenanceReason(agent.provenance))}</dd>` +
    `</dl>`
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
  if (list.length === 0) return dsEmptyState("Aucune règle résolue", "Cette AgentDefinition n'applique aucune règle.");
  const rows = list
    .map(
      (rule) =>
        `<tr><td>${resourceLink("rule", rule.resource_id, rule.stable_key)}${rule.deprecated ? ' <span class="status bad">Déprécié</span>' : ""}</td>` +
        `<td>v${rule.version}</td><td>${esc(versionOriginLabel(rule.version_origin))}</td><td>${esc(scopeLabel(rule.scope))}</td>` +
        `<td>${rulePathsHtml(rule)}</td></tr>`,
    )
    .join("");
  return `<div class="ds-table-wrap"><table class="ds-table"><caption>Règles résolues — ${list.length}</caption><thead><tr><th scope="col">Règle</th><th scope="col">Version</th><th scope="col">Origine</th><th scope="col">Portée</th><th scope="col">Chemin / raison</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

export function skillsTableHtml(skills: ResolvedSkill[] | undefined): string {
  const list = skills ?? [];
  if (list.length === 0) return dsEmptyState("Aucune compétence résolue", "Cette AgentDefinition n'utilise aucune compétence.");
  const rows = list
    .map(
      (skill) =>
        `<tr><td>${resourceLink("skill", skill.resource_id, skill.stable_key)}${skill.deprecated ? ' <span class="status bad">Déprécié</span>' : ""}</td>` +
        `<td>v${skill.version}</td><td>${esc(versionOriginLabel(skill.version_origin))}</td><td>${esc(scopeLabel(skill.scope))}</td>` +
        `<td>${esc(provenanceReason(skill.provenance))}</td></tr>`,
    )
    .join("");
  return `<div class="ds-table-wrap"><table class="ds-table"><caption>Compétences résolues — ${list.length}</caption><thead><tr><th scope="col">Compétence</th><th scope="col">Version</th><th scope="col">Origine</th><th scope="col">Portée</th><th scope="col">Raison</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function entriesTable(entries: { label: string; value: string }[], emptyMessage: string, caption = "Détails"): string {
  if (entries.length === 0) return `<p class="meta">${esc(emptyMessage)}</p>`;
  const rows = entries.map((entry) => `<tr><td>${esc(entry.label)}</td><td><code class="mono">${esc(entry.value)}</code></td></tr>`).join("");
  return `<div class="ds-table-wrap"><table class="ds-table"><caption class="ds-sr-only">${esc(caption)}</caption><thead><tr><th scope="col">Dimension</th><th scope="col">Valeur</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

export function modelProfileHtml(profile: ResolvedModelProfile | null | undefined): string {
  if (profile == null) {
    return dsEmptyState(
      "Aucun ModelProfile lié",
      "Cette AgentDefinition n'exprime aucune exigence de capacité. La compatibilité runtime n'est donc pas évaluée.",
    );
  }
  return (
    `<dl class="detail-grid">` +
    `<dt>Model Profile</dt><dd>${resourceLink("model_profile", profile.resource_id, profile.stable_key)} v${profile.version}${profile.deprecated ? ' <span class="status bad">Déprécié</span>' : ""}</dd>` +
    `<dt>Origine</dt><dd>${esc(versionOriginLabel(profile.version_origin))} · portée : ${esc(scopeLabel(profile.scope))} · raison : ${esc(provenanceReason(profile.provenance))}</dd>` +
    `<dt>Exigences déclarées</dt><dd>${entriesTable(requirementEntries(profile.requirements as CapabilityRequirement), "aucune exigence déclarée", "Exigences déclarées")}</dd>` +
    `</dl>`
  );
}

export function runtimeHtml(runtime: ResolvedRuntime | null | undefined): string {
  if (runtime == null) {
    return dsEmptyState(
      "Aucun binding runtime sélectionné",
      "Définition canonique résolue sans runtime applicable. C'est un résultat valide, pas un échec.",
    );
  }
  const target = runtime.target;
  const refs = [
    target.runtime_id !== null && target.runtime_id !== undefined
      ? `Runtime registry : ${configLink(`#/configuration/runtimes/${target.runtime_id}`, target.runtime_id)}`
      : null,
    target.harness_ref !== null && target.harness_ref !== undefined ? `Harness : <code class="mono">${esc(target.harness_ref)}</code>` : null,
    target.provider_ref !== null && target.provider_ref !== undefined ? `Provider : <code class="mono">${esc(target.provider_ref)}</code>` : null,
    target.model_ref !== null && target.model_ref !== undefined ? `Model : <code class="mono">${esc(target.model_ref)}</code>` : null,
    target.machine_id !== null && target.machine_id !== undefined
      ? `Machine : ${esc(target.machine_id)} (<a href="#/machines">voir Machines</a>)`
      : null,
  ]
    .filter((part): part is string => part !== null)
    .join(" · ");
  return (
    `<dl class="detail-grid">` +
    `<dt>Binding gagnant</dt><dd><strong>${esc(bindingLevelLabel(runtime.level))}</strong></dd>` +
    `<dt>Clé matchée</dt><dd>${esc(kindMeta(runtime.matched_kind).singular)} <code class="mono">${esc(runtime.matched_stable_key)}</code></dd>` +
    `<dt>Cible runtime</dt><dd>${refs !== "" ? refs : '<span class="meta">aucune ancre</span>'}</dd>` +
    `<dt>Capacités déclarées</dt><dd>${entriesTable(capabilityEntries(target.capabilities), "aucune déclarée", "Capacités déclarées")}</dd>` +
    `<dt>Provenance</dt><dd>${runtime.provenance != null ? esc(provenanceReason(runtime.provenance)) : '<span class="meta">—</span>'}</dd>` +
    `</dl>`
  );
}

/** Requirements vs runtime capabilities, with the canonical verdict. */
export function compatibilityComparisonHtml(resolved: ResolvedAgentDefinition): string {
  const requirements = entriesTable(requirementEntries(resolved.requirements as CapabilityRequirement), "Aucune exigence exprimée.", "Exigences du ModelProfile");
  const runtime = resolved.runtime;
  if (runtime == null) {
    return `${requirements}<p class="meta">Aucun runtime sélectionné : la compatibilité n'est pas évaluée.</p>`;
  }
  const capabilities = entriesTable(capabilityEntries(runtime.target.capabilities), "aucune déclarée", "Capacités runtime déclarées");
  const unsatisfied = runtime.unsatisfied ?? [];
  const verdict =
    unsatisfied.length === 0
      ? `<p class="status ok"><strong>Compatible</strong> — le serveur ne signale aucune exigence non satisfaite.</p>`
      : `<p class="status bad"><strong>Incompatible</strong> — exigences non satisfaites : ${unsatisfied.map((item) => esc(item)).join(" · ")}</p>`;
  return (
    `<div class="compare"><div><h4>Exigences (ModelProfile)</h4>${requirements}</div>` +
    `<div><h4>Capacités runtime (déclarées)</h4>${capabilities}</div></div>${verdict}`
  );
}

export function provenanceReasonsHtml(resolved: ResolvedAgentDefinition): string {
  const parts: string[] = [];
  parts.push(`<div><strong>Pourquoi cette version ?</strong> ${esc(provenanceReason(resolved.agent.provenance))}</div>`);
  for (const rule of resolved.rules ?? []) {
    parts.push(`<div><strong>Pourquoi la règle ${esc(rule.stable_key)} ?</strong> v${rule.version} · ${rulePathsHtml(rule)}</div>`);
  }
  for (const skill of resolved.skills ?? []) {
    parts.push(`<div><strong>Pourquoi la compétence ${esc(skill.stable_key)} ?</strong> ${esc(provenanceReason(skill.provenance))}</div>`);
  }
  if (resolved.model_profile != null) {
    parts.push(`<div><strong>Pourquoi ce ModelProfile ?</strong> ${esc(provenanceReason(resolved.model_profile.provenance))}</div>`);
  }
  if (resolved.runtime != null) {
    const provenance = resolved.runtime.provenance;
    parts.push(
      `<div><strong>Quel binding a gagné ?</strong> ${esc(bindingLevelLabel(resolved.runtime.level))}` +
        `${provenance != null ? ` · source : ${esc(provenanceSourceLabel(provenance.source))}` : ""}` +
        `${provenance?.via != null ? ` · via ${esc(provenance.via)}` : ""}</div>`,
    );
  } else {
    parts.push(`<div><strong>Quel binding a gagné ?</strong> aucun — pas de binding runtime applicable.</div>`);
  }
  return `<div class="reasons">${parts.join("")}</div>`;
}

export function resolutionFailureHtml(view: ResolutionErrorView, resolved: ResolvedAgentDefinition | null = null): string {
  if (resolved !== null) return "";
  if (view.code === "runtime_incompatible") {
    return (
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Échec de résolution · runtime_incompatible</strong>` +
      `<div>Binding sélectionné : ${view.bindingLevel !== null ? esc(bindingLevelLabel(view.bindingLevel)) : '<span class="meta">—</span>'}` +
      `${view.matchedKind !== null && view.matchedStableKey !== null ? ` sur ${esc(kindMeta(view.matchedKind).singular)} <code class="mono">${esc(view.matchedStableKey)}</code>` : ""}</div>` +
      `<div>Exigences non satisfaites : ${view.unsatisfied.length > 0 ? view.unsatisfied.map((item) => esc(item)).join(" · ") : '<span class="meta">—</span>'}</div>` +
      `<div>Aucun repli automatique — le binding sélectionné reste le binding sélectionné.</div>` +
      `<div class="meta">Corrigez les capacités runtime ou changez le binding ; le serveur ne tente jamais un niveau inférieur silencieusement.</div></div>`
    );
  }
  if (view.notFound) {
    return (
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Non trouvé · ${esc(view.code ?? "HTTP 404")}</strong>` +
      `<div>La ressource n'existe pas, ou elle n'est pas visible pour ce jeton. Le serveur ne révèle jamais laquelle.</div></div>`
    );
  }
  if (view.projectAccessDenied) {
    return (
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Accès au projet refusé · HTTP 403</strong>` +
      `<div>Votre compte n'a pas accès à ce projet, ou il n'existe pas. Demandez l'accès à un administrateur.</div></div>`
    );
  }
  if (view.forbidden) {
    return `<div class="ds-notice ds-notice--danger" role="alert"><strong>Accès refusé · HTTP 403</strong><div>${esc(view.message)}</div></div>`;
  }
  if (view.isAuth) {
    return `<div class="ds-notice ds-notice--danger" role="alert"><strong>Non autorisé · HTTP ${view.status}</strong><div>${esc(view.message)}</div></div>`;
  }
  return (
    `<div class="ds-notice ds-notice--danger" role="alert"><strong>Échec de résolution · ${esc(view.code ?? `HTTP ${view.status}`)}</strong>` +
    `${view.reason !== null ? `<div>Raison : <code class="mono">${esc(view.reason)}</code></div>` : ""}<div>${esc(view.message)}</div></div>`
  );
}

/** Safe allowlisted projection of the canonical response for the raw-data drawer. */
export function safeResponseJson(resolved: ResolvedAgentDefinition): string {
  const safe = {
    agent: {
      resource_id: resolved.agent.resource_id,
      stable_key: resolved.agent.stable_key,
      scope: resolved.agent.scope,
      version: resolved.agent.version,
      version_origin: resolved.agent.version_origin,
      deprecated: resolved.agent.deprecated,
      title: resolved.agent.title,
      provenance: resolved.agent.provenance,
    },
    rules: (resolved.rules ?? []).map((r) => ({
      resource_id: r.resource_id,
      stable_key: r.stable_key,
      scope: r.scope,
      version: r.version,
      version_origin: r.version_origin,
      deprecated: r.deprecated,
      paths: r.paths,
    })),
    skills: (resolved.skills ?? []).map((s) => ({
      resource_id: s.resource_id,
      stable_key: s.stable_key,
      scope: s.scope,
      version: s.version,
      version_origin: s.version_origin,
      deprecated: s.deprecated,
      provenance: s.provenance,
    })),
    model_profile: resolved.model_profile
      ? {
          resource_id: resolved.model_profile.resource_id,
          stable_key: resolved.model_profile.stable_key,
          scope: resolved.model_profile.scope,
          version: resolved.model_profile.version,
          version_origin: resolved.model_profile.version_origin,
          deprecated: resolved.model_profile.deprecated,
          requirements: resolved.model_profile.requirements,
          provenance: resolved.model_profile.provenance,
        }
      : null,
    requirements: resolved.requirements,
    composed_agents: resolved.composed_agents,
    workflows: resolved.workflows,
    runtime: resolved.runtime
      ? {
          target: resolved.runtime.target,
          level: resolved.runtime.level,
          matched_kind: resolved.runtime.matched_kind,
          matched_stable_key: resolved.runtime.matched_stable_key,
          compatible: resolved.runtime.compatible,
          unsatisfied: resolved.runtime.unsatisfied,
          provenance: resolved.runtime.provenance,
        }
      : null,
  };
  return JSON.stringify(safe, null, 2);
}

export function rawJsonHtml(resolved: ResolvedAgentDefinition): string {
  return `<details class="editor inspector-raw"><summary>Données brutes (JSON filtré)</summary><pre class="code">${esc(safeResponseJson(resolved))}</pre></details>`;
}

export function resolutionResultHtml(resolved: ResolvedAgentDefinition): string {
  return (
    `<section class="ds-panel inspector-section" aria-labelledby="inspector-identity"><header><h2 id="inspector-identity">Identité résolue</h2></header><div class="body">${identityHtml(resolved)}</div></section>` +
    `<section class="ds-panel inspector-section" aria-labelledby="inspector-model-profile"><header><h2 id="inspector-model-profile">Model Profile et exigences</h2></header><div class="body">${modelProfileHtml(resolved.model_profile)}</div></section>` +
    `<section class="ds-panel inspector-section" aria-labelledby="inspector-runtime"><header><h2 id="inspector-runtime">Runtime sélectionné</h2></header><div class="body">${runtimeHtml(resolved.runtime)}</div></section>` +
    `<section class="ds-panel inspector-section" aria-labelledby="inspector-compatibility"><header><h2 id="inspector-compatibility">Compatibilité — exigences vs runtime</h2></header><div class="body">${compatibilityComparisonHtml(resolved)}</div></section>` +
    `<section class="ds-panel inspector-section" aria-labelledby="inspector-provenance"><header><h2 id="inspector-provenance">Pourquoi ce résultat ?</h2></header><div class="body">${provenanceReasonsHtml(resolved)}</div></section>` +
    `<section class="ds-panel inspector-section" aria-labelledby="inspector-rules"><header><h2 id="inspector-rules">Règles (${(resolved.rules ?? []).length})</h2></header><div class="body">${rulesTableHtml(resolved.rules)}</div></section>` +
    `<section class="ds-panel inspector-section" aria-labelledby="inspector-skills"><header><h2 id="inspector-skills">Compétences (${(resolved.skills ?? []).length})</h2></header><div class="body">${skillsTableHtml(resolved.skills)}</div></section>` +
    rawJsonHtml(resolved)
  );
}

export async function renderInspector(root: HTMLElement, ctx: InspectorContext): Promise<void> {
  const title = "Inspecteur de résolution";
  const subtitle =
    "Inspectez ici la manière dont Studi'OS résout une configuration d'agent et évalue la compatibilité avec le runtime — le serveur décide, cette page explique.";
  if (!ctx.authed) {
    root.innerHTML =
      dsPageHeader(title, subtitle) +
      dsEmptyState("Non connecté", "Saisissez un jeton machine pour lancer une inspection.", { label: "Aller à l'accueil", href: "#/" });
    return;
  }

  root.innerHTML = dsPageHeader(title, subtitle) + dsSkeleton(4);

  let agentKeys: string[] = [];
  try {
    const agents = await listLibraryResources(ctx.client, { kind: "agent_definition" });
    agentKeys = agents.map((agent) => agent.stable_key).filter((key, index, all) => all.indexOf(key) === index);
  } catch {
    agentKeys = [];
  }

  const projectId = uiState.selectedProjectId;
  root.innerHTML =
    dsPageHeader(title, subtitle) +
    `<div class="inspector-grid">` +
    `<div class="inspector-form-panel">${inspectorFormHtml(ctx.stableKey, projectId, agentKeys)}</div>` +
    `<div class="inspector-result-panel"><div data-result>${emptyResultHtml()}</div></div>` +
    `</div>`;

  bindInspector(root, ctx);

  if (ctx.stableKey !== null && ctx.stableKey !== "") {
    await runResolution(root, ctx);
  }
}

function emptyResultHtml(): string {
  return (
    `<div class="ds-panel inspector-section"><div class="body">` +
    dsEmptyState(
      "Aucune inspection lancée",
      "Choisissez un champ puis lancez une résolution : le résultat détaille l'identité résolue, le runtime retenu, la compatibilité et la provenance.",
    ) +
    `</div></div>`
  );
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

function setFormMessage(form: HTMLFormElement, text: string, isError: boolean): void {
  const msg = form.querySelector("[data-msg]");
  if (msg === null) return;
  msg.textContent = text;
  if (isError) {
    msg.className = "meta ds-field-error";
    msg.setAttribute("role", "alert");
  } else {
    msg.className = "meta";
    msg.removeAttribute("role");
  }
}

function blockSubmit(form: HTMLFormElement): void {
  const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
  if (submit !== null) {
    submit.disabled = true;
    submit.classList.add("ds-btn--loading");
  }
}

function releaseSubmit(form: HTMLFormElement): void {
  const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
  if (submit !== null) {
    submit.disabled = false;
    submit.classList.remove("ds-btn--loading");
  }
}

function bindInspector(root: HTMLElement, ctx: InspectorContext): void {
  const form = root.querySelector<HTMLFormElement>("[data-resolve]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const built = buildResolutionRequest(readInspectorInput(form));
    if (!built.ok) {
      setFormMessage(form, built.error, true);
      return;
    }
    blockSubmit(form);
    setFormMessage(form, "Analyse de la résolution…", false);
    void executeResolution(root, ctx, built.value).then((status) => {
      releaseSubmit(form);
      setFormMessage(form, status.text, status.error);
    });
  });
}

interface ResolutionStatus {
  text: string;
  error: boolean;
}

async function runResolution(root: HTMLElement, ctx: InspectorContext): Promise<void> {
  const form = root.querySelector<HTMLFormElement>("[data-resolve]");
  if (form === null) return;
  const built = buildResolutionRequest(readInspectorInput(form));
  if (!built.ok) {
    setFormMessage(form, built.error, true);
    return;
  }
  blockSubmit(form);
  setFormMessage(form, "Analyse de la résolution…", false);
  const status = await executeResolution(root, ctx, built.value);
  releaseSubmit(form);
  setFormMessage(form, status.text, status.error);
}

/** Renders the canonical response or its structured failure; returns a status
 *  string for the form message. Never throws. */
async function executeResolution(
  root: HTMLElement,
  ctx: InspectorContext,
  request: components["schemas"]["AgentResolutionRequest"],
): Promise<ResolutionStatus> {
  const result = root.querySelector("[data-result]");
  if (result === null) return { text: "", error: false };
  result.innerHTML = dsSkeleton(6);
  try {
    const resolved = await postResolution(ctx.client, request);
    result.innerHTML = resolutionResultHtml(resolved);
    return { text: "Résolution terminée — résultat serveur affiché.", error: false };
  } catch (error) {
    const view = resolutionErrorView(error);
    result.innerHTML = resolutionFailureHtml(view);
    return { text: view.code ?? describeError(error), error: true };
  }
}
