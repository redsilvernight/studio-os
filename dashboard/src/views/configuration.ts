/**
 * UI-12 — Paramètres : surface de configuration séparée des pages métier.
 *
 * Principe : Paramètres = configurer. La résolution et la compatibilité
 * s'expliquent dans l'Inspecteur (UI-11), les Agents (UI-6) et les Machines
 * (UI-9) restent sur leurs pages. Cette vue ne réimplémente aucun resolver :
 * elle liste l'état canonique renvoyé par le serveur et renvoie vers
 * l'Inspecteur pour le résultat de résolution (DEC-0068/0069).
 *
 * Trois domaines réellement existants (audit UI-12) :
 * - Runtimes : `GET/POST /runtimes`, `GET/PATCH /runtimes/{id}`,
 *   `POST /runtimes/{id}/revoke` — une cible/environnement d'exécution,
 *   ni un agent, ni une machine, ni un modèle (`model_ref` est une propriété).
 * - Bindings : `GET/POST /runtime-bindings`, `GET/DELETE /runtime-bindings/{id}`
 *   — un choix stocké par clé logique, à quatre niveaux persistés (`user`,
 *   `project_override`, `project_default`, `studio_default`). `session` est
 *   éphémère et n'est jamais stocké ici.
 * - Projet : ressources, verrous et overrides de projet.
 *
 * Aucune autre surface n'existe côté backend (pas de profil, notifications,
 * clés API, sécurité ou intégrations) : elles ne sont pas fabriquées.
 */
import type { StudioClient } from "../api";
import {
  capabilityEntries,
  kindMeta,
  libraryKindHref,
  runtimeTargetEntries,
  scopeLabel,
  type RuntimeCapabilities,
  type RuntimeTarget,
} from "../libraryFormat";
import {
  getRuntime,
  listRuntimes,
  registerRuntime,
  revokeRuntime,
  updateRuntime,
  type RuntimeRegistration,
  type RuntimeStatus,
} from "../runtimesApi";
import {
  createRuntimeBinding,
  deleteRuntimeBinding,
  listRuntimeBindings,
  STORED_RUNTIME_LEVELS,
  type RuntimeBinding,
  type RuntimeLevel,
} from "../bindingsApi";
import {
  createLibraryLock,
  listLibraryLocks,
  listLibraryResources,
  releaseLibraryLock,
  type LibraryProjectLock,
  type LibraryResource,
} from "../libraryApi";
import {
  buildBindingCreate,
  buildRuntimeCreate,
  buildRuntimeUpdate,
  capabilityFieldsHtml,
} from "./configForms";
import { formReader } from "./libraryForms";
import { uiState } from "../store";
import { describeError, esc, fmtTime, shortId, statusBlock } from "../ui";
import { dsBadge, dsEmptyState, dsNotify, dsPageHeader, dsSkeleton, type DsTone } from "../ds/ds";
// Styles colocalisés : la page reste autonome sans toucher au CSS global.
import "./configuration.css";

export interface ConfigurationContext {
  client: StudioClient;
  authed: boolean;
}

export type ConfigTab = "runtimes" | "bindings" | "project";

const CONFIG_TABS: readonly { name: ConfigTab; label: string; href: string }[] = [
  { name: "runtimes", label: "Runtimes", href: "#/configuration/runtimes" },
  { name: "bindings", label: "Bindings", href: "#/configuration/bindings" },
  { name: "project", label: "Projet", href: "#/configuration/project/resources" },
];

const SETTINGS_DESCRIPTION =
  "Configurer les environnements d'exécution et les règles d'affectation. " +
  "La résolution et la compatibilité s'expliquent dans l'Inspecteur ; les Agents et les Machines restent sur leurs pages.";

/** Navigation locale des domaines réellement configurables. */
export function configTabsHtml(active: ConfigTab): string {
  const links = CONFIG_TABS.map((tab) => {
    const current = active === tab.name;
    return `<a class="tab${current ? " active" : ""}" href="${tab.href}"${current ? ' aria-current="page"' : ""}>${esc(tab.label)}</a>`;
  }).join("");
  return `<nav class="tabs" aria-label="Sections des paramètres">${links}</nav>`;
}

function settingsHeader(title: string, description: string, actions: { label: string; id: string }[] = []): string {
  return dsPageHeader(title, description, actions.map((action) => ({ label: action.label, id: action.id })));
}

// ---------------------------------------------------------------------------
// Vocabulaire commun (français)
// ---------------------------------------------------------------------------

const RUNTIME_STATUS_LABELS: Record<RuntimeStatus, string> = { active: "Actif", revoked: "Révoqué" };
const RUNTIME_STATUS_TONES: Record<RuntimeStatus, DsTone> = { active: "success", revoked: "neutral" };

export function runtimeStatusFr(status: RuntimeStatus): string {
  return RUNTIME_STATUS_LABELS[status] ?? String(status);
}

export function runtimeStatusTone(status: RuntimeStatus): DsTone {
  return RUNTIME_STATUS_TONES[status] ?? "neutral";
}

function nonEmpty(value: string | null | undefined): value is string {
  return value !== null && value !== undefined && value.trim() !== "";
}

/** Titre humain d'un runtime : refs ouvertes d'abord, jamais un UUID seul. */
export function runtimeHumanTitle(runtime: Pick<RuntimeRegistration, "harness_ref" | "provider_ref" | "model_ref" | "machine_id">): string {
  const refs = [runtime.harness_ref, runtime.provider_ref, runtime.model_ref].filter(nonEmpty);
  if (refs.length === 0) {
    return nonEmpty(runtime.machine_id) ? "Runtime rattaché à une machine" : "Runtime sans référence déclarée";
  }
  return refs.join(" · ");
}

function refLine(label: string, value: string | null | undefined): string {
  return `<div class="settings-ref"><dt>${esc(label)}</dt><dd>${nonEmpty(value) ? `<code class="mono">${esc(value)}</code>` : '<span class="meta">non renseigné</span>'}</dd></div>`;
}

/** Sommaire lisible d'une cible de runtime (référence registre ou ancres inline). */
export function runtimeTargetSummary(target: RuntimeTarget): string {
  const entries = runtimeTargetEntries(target);
  if (entries.length === 0) return '<span class="meta">—</span>';
  return entries.map((entry) => `${esc(entry.label)} : <code class="mono">${esc(entry.value)}</code>`).join(" · ");
}

/** Capacités déclarées d'un runtime — déclarations techniques, jamais un score. */
export function capabilitySummary(capabilities: RuntimeCapabilities): string {
  const entries = capabilityEntries(capabilities);
  if (entries.length === 0) return '<span class="meta">Aucune capacité déclarée</span>';
  return entries.map((entry) => `<span class="tag">${esc(entry.label)} = ${esc(entry.value)}</span>`).join(" ");
}

/**
 * Métadonnées libres sûres à afficher. Le registre n'est pas un coffre
 * (P6/DEC-0070) : on filtre défensivement les clés sensibles côté UI, même
 * si le serveur les refuse déjà, et on ne rend jamais un objet imbriqué brut.
 */
const SENSITIVE_METADATA_PARTS = [
  "secret",
  "token",
  "password",
  "passwd",
  "private_key",
  "privatekey",
  "api_key",
  "apikey",
  "credential",
  "bearer",
  "authorization",
  "jwt",
];

export function safeMetadataEntries(metadata: Record<string, unknown> | null | undefined): { key: string; value: string }[] {
  if (metadata === null || metadata === undefined) return [];
  const entries: { key: string; value: string }[] = [];
  for (const [key, raw] of Object.entries(metadata)) {
    const lowered = key.toLowerCase().replace(/-/g, "_");
    if (SENSITIVE_METADATA_PARTS.some((part) => lowered.includes(part))) continue;
    const value = typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean" ? String(raw) : "[valeur structurée masquée]";
    entries.push({ key, value });
  }
  return entries.sort((a, b) => a.key.localeCompare(b.key));
}

// ---------------------------------------------------------------------------
// Runtimes
// ---------------------------------------------------------------------------

export interface RuntimesPageState {
  query: string;
  provider: string;
  machine: string;
  status: RuntimeStatus | "all";
  includeRevoked: boolean;
}

export function initialRuntimesState(): RuntimesPageState {
  return { query: "", provider: "", machine: "", status: "all", includeRevoked: false };
}

export function isRuntimesDefaultState(state: RuntimesPageState): boolean {
  return state.query.trim() === "" && state.provider === "" && state.machine === "" && state.status === "all" && !state.includeRevoked;
}

function runtimeSearchText(runtime: RuntimeRegistration): string {
  return [runtime.harness_ref, runtime.provider_ref, runtime.model_ref, runtime.id, runtime.machine_id, runtimeStatusFr(runtime.status)]
    .filter(nonEmpty)
    .join("\n")
    .toLowerCase();
}

/** Filtre client honnête sur les runtimes déjà chargés. */
export function filterRuntimes(runtimes: RuntimeRegistration[], state: RuntimesPageState): RuntimeRegistration[] {
  const query = state.query.trim().toLowerCase();
  return runtimes.filter((runtime) => {
    if (state.status !== "all" && runtime.status !== state.status) return false;
    if (state.provider !== "" && (runtime.provider_ref ?? "") !== state.provider) return false;
    if (state.machine !== "" && (runtime.machine_id ?? "") !== state.machine) return false;
    if (query === "") return true;
    return runtimeSearchText(runtime).includes(query);
  });
}

export function runtimeProviderOptions(runtimes: RuntimeRegistration[]): string[] {
  return [...new Set(runtimes.map((runtime) => runtime.provider_ref).filter(nonEmpty))].sort();
}

export function runtimeMachineOptions(runtimes: RuntimeRegistration[]): string[] {
  return [...new Set(runtimes.map((runtime) => runtime.machine_id).filter(nonEmpty))].sort();
}

function runtimeOptions(values: string[], selected: string, allLabel: string): string {
  const first = `<option value=""${selected === "" ? " selected" : ""}>${esc(allLabel)}</option>`;
  return first + values.map((value) => `<option value="${esc(value)}"${selected === value ? " selected" : ""}>${esc(shortId(value))}</option>`).join("");
}

export function runtimesToolbarHtml(state: RuntimesPageState, runtimes: RuntimeRegistration[], shown: number): string {
  return (
    `<div class="settings-toolbar" role="search" aria-label="Filtrer les runtimes chargés">` +
    `<div class="ds-search"><span class="ds-search-icon" aria-hidden="true">⌕</span>` +
    `<label class="ds-sr-only" for="settings-runtimes-search">Filtrer les runtimes déjà chargés</label>` +
    `<input class="ds-input" type="search" id="settings-runtimes-search" value="${esc(state.query)}" placeholder="Rechercher par provider, model, harness…" autocomplete="off" /></div>` +
    `<label class="settings-filter"><span>Provider</span><select class="ds-select" id="settings-runtimes-provider">${runtimeOptions(runtimeProviderOptions(runtimes), state.provider, "Tous les providers")}</select></label>` +
    `<label class="settings-filter"><span>Machine</span><select class="ds-select" id="settings-runtimes-machine">${runtimeOptions(runtimeMachineOptions(runtimes), state.machine, "Toutes les machines")}</select></label>` +
    `<label class="settings-filter"><span>Statut</span><select class="ds-select" id="settings-runtimes-status">` +
    `<option value="all"${state.status === "all" ? " selected" : ""}>Tous les statuts</option>` +
    `<option value="active"${state.status === "active" ? " selected" : ""}>Actif</option>` +
    `<option value="revoked"${state.status === "revoked" ? " selected" : ""}>Révoqué</option>` +
    `</select></label>` +
    `<label class="settings-check"><input type="checkbox" id="settings-runtimes-revoked" data-include-revoked${state.includeRevoked ? " checked" : ""} /> Inclure les révoqués</label>` +
    `<button class="ds-btn ds-btn--ghost" type="button" data-reset${isRuntimesDefaultState(state) ? " disabled" : ""}>Réinitialiser</button>` +
    `<p class="ds-list-sub settings-toolbar-count" role="status" aria-live="polite">${shown} runtime(s) affiché(s) sur ${runtimes.length} chargé(s) — recherche et filtres locaux.</p>` +
    `</div>`
  );
}

export function runtimeCardHtml(runtime: RuntimeRegistration): string {
  const machine =
    nonEmpty(runtime.machine_id)
      ? `<a href="#/machines">Machine ${esc(shortId(runtime.machine_id))}</a>`
      : '<span class="meta">Sans machine (cible distante)</span>';
  const status = dsBadge(runtimeStatusFr(runtime.status), runtimeStatusTone(runtime.status));
  return (
    `<li class="ds-list-item settings-runtime-row"><div class="grow">` +
    `<h3 class="settings-card-title">${esc(runtimeHumanTitle(runtime))}</h3>` +
    `<div class="ds-list-sub">${machine}</div>` +
    `<div class="ds-list-sub settings-caps">${capabilitySummary(runtime.capabilities)}</div>` +
    `<div class="ds-list-sub meta">Environnement/cible d'exécution — ni un agent, ni une machine.</div>` +
    `</div><div class="settings-row-side">${status}` +
    `<a class="ds-btn ds-btn--sm" href="#/configuration/runtimes/${esc(runtime.id)}">Détails</a></div></li>`
  );
}

export function runtimesListHtml(runtimes: RuntimeRegistration[]): string {
  return `<ul class="ds-list settings-list">${runtimes.map(runtimeCardHtml).join("")}</ul>`;
}

function runtimesEmptyHtml(): string {
  return dsEmptyState(
    "Aucun runtime enregistré",
    "Un runtime décrit un environnement/cible d'exécution (provider, harness, model). " +
      "Aucun n'est encore déclaré pour ce jeton — utilisez « Déclarer un runtime » ci-dessous.",
  );
}

function runtimesNoMatchHtml(): string {
  return dsEmptyState("Aucun runtime ne correspond", "Modifiez la recherche ou les filtres pour retrouver vos runtimes déjà chargés.");
}

export function createRuntimeFormHtml(): string {
  return (
    `<details class="editor settings-editor"><summary>Déclarer un runtime</summary><form class="stack-form" data-runtime-create>` +
    `<p class="meta">Tous les champs de référence sont des chaînes ouvertes : aucun catalogue de fournisseurs n'est imposé. Au moins une référence ou une machine est requise. Le serveur refusera toute métadonnée ressemblant à un secret.</p>` +
    `<label class="stack">Machine (facultatif) <input name="machine_id" placeholder="uuid d'une machine possédée" /></label>` +
    `<label class="stack">Harness <input name="harness_ref" placeholder="chaîne ouverte (facultatif)" /></label>` +
    `<label class="stack">Provider <input name="provider_ref" placeholder="chaîne ouverte (facultatif)" /></label>` +
    `<label class="stack">Model <input name="model_ref" placeholder="chaîne ouverte (facultatif)" /></label>` +
    `<details class="settings-subeditor"><summary>Capacités déclarées (facultatif)</summary>${capabilityFieldsHtml()}</details>` +
    `<label class="stack">Métadonnées libres (une par ligne, <code class="mono">clé=valeur</code>) <textarea name="metadata" rows="2" placeholder="facultatif — les secrets sont refusés par le serveur"></textarea></label>` +
    `<button type="submit" class="ds-btn ds-btn--primary">Déclarer le runtime</button>` +
    `<span class="meta">POST /runtimes · Idempotency-Key par tentative · double soumission impossible</span>` +
    `<div data-msg class="meta" role="status" aria-live="polite"></div></form></details>`
  );
}

let runtimesState: RuntimesPageState = initialRuntimesState();

export async function renderRuntimes(root: HTMLElement, ctx: ConfigurationContext): Promise<void> {
  const head = configTabsHtml("runtimes");
  if (!ctx.authed) {
    root.innerHTML =
      `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION)}${head}` +
      `${dsEmptyState("Connexion requise", "Définissez un jeton machine pour lire et configurer vos runtimes.")}</div>`;
    return;
  }
  root.innerHTML = `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION)}${head}${dsSkeleton(4)}</div>`;
  let runtimes: RuntimeRegistration[];
  try {
    runtimes = await listRuntimes(ctx.client, { includeRevoked: runtimesState.includeRevoked });
  } catch (error) {
    root.innerHTML =
      `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION, [{ label: "Recharger", id: "settings-runtimes-reload" }])}${head}` +
      `<div class="state error" role="alert">Impossible de charger les runtimes : ${esc(describeError(error))}</div></div>`;
    root.querySelector("#settings-runtimes-reload")?.addEventListener("click", () => {
      void renderRuntimes(root, ctx);
    });
    return;
  }
  root.innerHTML = runtimesPageHtml(runtimes);
  bindRuntimes(root, ctx, runtimes);
}

export function runtimesPageHtml(runtimes: RuntimeRegistration[]): string {
  const visible = filterRuntimes(runtimes, runtimesState);
  const body = runtimes.length === 0 ? runtimesEmptyHtml() : visible.length === 0 ? runtimesNoMatchHtml() : runtimesListHtml(visible);
  return (
    `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION, [{ label: "Recharger", id: "settings-runtimes-reload" }])}${configTabsHtml("runtimes")}` +
    `<section class="settings-domain"><h2>Runtimes enregistrés</h2>` +
    `<p class="settings-intro">Un runtime est un environnement/cible d'exécution. Le provider, le model et le harness sont des références ouvertes ; le model n'est pas le runtime, et une machine n'est pas un runtime.</p>` +
    `${runtimesToolbarHtml(runtimesState, runtimes, visible.length)}` +
    `<div id="settings-runtimes-list" aria-live="polite">${body}</div>` +
    `${createRuntimeFormHtml()}` +
    `<p class="meta">Les runtimes sont privés à leur propriétaire. Le niveau gagnant lors d'une résolution est décidé par le serveur — voir l'<a href="#/inspector">Inspecteur</a>.</p>` +
    `</section></div>`
  );
}

function bindRuntimes(root: HTMLElement, ctx: ConfigurationContext, runtimes: RuntimeRegistration[]): void {
  root.querySelector("#settings-runtimes-reload")?.addEventListener("click", () => {
    void renderRuntimes(root, ctx);
  });
  bindRuntimesToolbar(root, ctx, runtimes);
  const form = root.querySelector<HTMLFormElement>("[data-runtime-create]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = form.querySelector("[data-msg]");
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    const built = buildRuntimeCreate(formReader(form));
    if (!built.ok) {
      if (msg !== null) msg.textContent = built.error;
      return;
    }
    if (submit !== null) submit.disabled = true;
    registerRuntime(ctx.client, built.value)
      .then(() => {
        runtimesState = initialRuntimesState();
        void renderRuntimes(root, ctx);
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
}

function refreshRuntimesList(root: HTMLElement, runtimes: RuntimeRegistration[]): void {
  const visible = filterRuntimes(runtimes, runtimesState);
  const list = root.querySelector("#settings-runtimes-list");
  if (list !== null) {
    list.innerHTML = runtimes.length === 0 ? runtimesEmptyHtml() : visible.length === 0 ? runtimesNoMatchHtml() : runtimesListHtml(visible);
  }
  const toolbar = root.querySelector(".settings-toolbar");
  if (toolbar !== null) {
    const fresh = document.createElement("div");
    fresh.innerHTML = runtimesToolbarHtml(runtimesState, runtimes, visible.length);
    toolbar.replaceWith(...fresh.childNodes);
  }
}

function bindRuntimesToolbar(root: HTMLElement, ctx: ConfigurationContext, runtimes: RuntimeRegistration[]): void {
  const search = root.querySelector<HTMLInputElement>("#settings-runtimes-search");
  search?.addEventListener("input", () => {
    runtimesState.query = search.value;
    refreshRuntimesList(root, runtimes);
    bindRuntimesToolbar(root, ctx, runtimes);
    const again = root.querySelector<HTMLInputElement>("#settings-runtimes-search");
    if (again !== null) {
      again.focus();
      again.setSelectionRange(again.value.length, again.value.length);
    }
  });
  const provider = root.querySelector<HTMLSelectElement>("#settings-runtimes-provider");
  provider?.addEventListener("change", () => {
    runtimesState.provider = provider.value;
    refreshRuntimesList(root, runtimes);
    bindRuntimesToolbar(root, ctx, runtimes);
  });
  const machine = root.querySelector<HTMLSelectElement>("#settings-runtimes-machine");
  machine?.addEventListener("change", () => {
    runtimesState.machine = machine.value;
    refreshRuntimesList(root, runtimes);
    bindRuntimesToolbar(root, ctx, runtimes);
  });
  const status = root.querySelector<HTMLSelectElement>("#settings-runtimes-status");
  status?.addEventListener("change", () => {
    runtimesState.status = status.value === "active" || status.value === "revoked" ? status.value : "all";
    refreshRuntimesList(root, runtimes);
    bindRuntimesToolbar(root, ctx, runtimes);
  });
  const revoked = root.querySelector<HTMLInputElement>("[data-include-revoked]");
  revoked?.addEventListener("change", () => {
    runtimesState.includeRevoked = revoked.checked;
    void renderRuntimes(root, ctx);
  });
  root.querySelector("[data-reset]")?.addEventListener("click", () => {
    runtimesState = initialRuntimesState();
    void renderRuntimes(root, ctx);
  });
}

// ---------------------------------------------------------------------------
// Runtime — détail
// ---------------------------------------------------------------------------

type Settled<T> = { ok: true; value: T } | { ok: false; error: unknown };

async function settle<T>(promise: Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, value: await promise };
  } catch (error) {
    return { ok: false, error };
  }
}

export function runtimeDetailHtml(runtime: RuntimeRegistration, bindings: RuntimeBinding[] | null, bindingsError: string | null): string {
  const links = bindings === null ? "" : runtimeBindingsTableHtml(bindings);
  const bindingsBlock =
    bindings === null
      ? `<p class="state error" role="alert">Bindings indisponibles : ${esc(bindingsError ?? "erreur inconnue")} — le runtime reste consultable.</p>`
      : links;
  const metadata = safeMetadataEntries(runtime.runtime_metadata);
  const metadataHtml =
    metadata.length === 0
      ? '<p class="ds-list-sub">Aucune métadonnée libre.</p>'
      : `<dl class="settings-refs">${metadata.map((entry) => `<div class="settings-ref"><dt>${esc(entry.key)}</dt><dd><code class="mono">${esc(entry.value)}</code></dd></div>`).join("")}</dl>`;
  const technical =
    `<details class="settings-technical"><summary>Informations techniques</summary><dl class="settings-refs">` +
    `<div class="settings-ref"><dt>Identifiant</dt><dd><code class="mono">${esc(runtime.id)}</code></dd></div>` +
    `<div class="settings-ref"><dt>Machine</dt><dd>${nonEmpty(runtime.machine_id) ? `<code class="mono">${esc(runtime.machine_id)}</code>` : "aucune"}</dd></div>` +
    `<div class="settings-ref"><dt>Version</dt><dd>v${runtime.version}</dd></div>` +
    `<div class="settings-ref"><dt>Source des capacités</dt><dd><code class="mono">${esc(runtime.capability_source)}</code></dd></div>` +
    `<div class="settings-ref"><dt>Créé le</dt><dd>${fmtTime(runtime.created_at)}</dd></div>` +
    `<div class="settings-ref"><dt>Mis à jour le</dt><dd>${fmtTime(runtime.updated_at)}</dd></div>` +
    `</dl><h4>Métadonnées</h4>${metadataHtml}</details>`;
  return (
    `<section class="settings-domain"><h2>Configuration du runtime</h2>` +
    `<p class="settings-intro">Runtime = environnement/cible d'exécution. Il n'est ni un agent, ni une machine, ni un modèle : <code class="mono">model_ref</code> est une de ses propriétés.</p>` +
    `<dl class="settings-refs">` +
    `<div class="settings-ref"><dt>Statut</dt><dd>${dsBadge(runtimeStatusFr(runtime.status), runtimeStatusTone(runtime.status))}</dd></div>` +
    `<div class="settings-ref"><dt>Propriétaire</dt><dd>${esc(shortId(runtime.owner_user_id))}</dd></div>` +
    `<div class="settings-ref"><dt>Machine</dt><dd>${nonEmpty(runtime.machine_id) ? `<a href="#/machines">Machine ${esc(shortId(runtime.machine_id))}</a>` : '<span class="meta">Sans machine (cible distante)</span>'}</dd></div>` +
    refLine("Provider", runtime.provider_ref) +
    refLine("Model", runtime.model_ref) +
    refLine("Harness", runtime.harness_ref) +
    `</dl>` +
    `<h3>Capacités déclarées</h3>${capabilitySummary(runtime.capabilities)}` +
    `<h3>Bindings référençant ce runtime</h3>${bindingsBlock}` +
    `<p class="meta"><a class="ds-btn" href="#/inspector">Inspecter la résolution</a> — pourquoi un runtime est choisi se lit dans l'Inspecteur, pas ici.</p>` +
    updateRuntimeFormHtml(runtime) +
    revokeRuntimeFormHtml(runtime) +
    technical +
    `</section>`
  );
}

function updateRuntimeFormHtml(runtime: RuntimeRegistration): string {
  const disabled = runtime.status === "revoked" ? "disabled" : "";
  return (
    `<details class="editor settings-editor"><summary>Modifier ce runtime</summary><form class="stack-form" data-runtime-update>` +
    `<p class="meta">Un champ laissé vide reste inchangé. La modification exige la version courante : une version périmée renvoie un conflit 409, jamais un écrasement silencieux.</p>` +
    `<label class="stack">Harness (vide = inchangé) <input name="harness_ref" placeholder="${esc(runtime.harness_ref ?? "inchangé")}" ${disabled} /></label>` +
    `<label class="stack">Provider (vide = inchangé) <input name="provider_ref" placeholder="${esc(runtime.provider_ref ?? "inchangé")}" ${disabled} /></label>` +
    `<label class="stack">Model (vide = inchangé) <input name="model_ref" placeholder="${esc(runtime.model_ref ?? "inchangé")}" ${disabled} /></label>` +
    `<label class="stack">Machine (vide = inchangée) <input name="machine_id" placeholder="uuid" ${disabled} /></label>` +
    `<label class="settings-check"><input name="detach_machine" type="checkbox" ${disabled} /> Détacher la machine</label>` +
    `<label class="settings-check"><input name="update_capabilities" type="checkbox" ${disabled} /> Remplacer les capacités</label>` +
    `<details class="settings-subeditor"><summary>Capacités de remplacement</summary>${capabilityFieldsHtml(runtime.status === "revoked")}</details>` +
    `<label class="stack">Métadonnées (clé=valeur par ligne, vide = inchangées) <textarea name="metadata" rows="2" ${disabled}></textarea></label>` +
    `<label class="stack">Version attendue <input name="expected_version" type="number" min="1" value="${runtime.version}" required ${disabled} /></label>` +
    `<button type="submit" class="ds-btn ds-btn--primary" ${disabled}>Enregistrer</button>` +
    `<span class="meta">PATCH /runtimes/{id} · version périmée → 409 · aucun retry silencieux</span>` +
    `<div data-msg class="meta" role="status" aria-live="polite"></div></form></details>`
  );
}

function revokeRuntimeFormHtml(runtime: RuntimeRegistration): string {
  const disabled = runtime.status === "revoked" ? "disabled" : "";
  return (
    `<details class="editor settings-editor settings-danger"><summary>Révoquer ce runtime</summary><form class="stack-form" data-revoke>` +
    `<p class="meta">La révocation est logique : la ligne reste consultable mais n'est plus « live », et les bindings qui la visent retombent. Aucune suppression physique n'existe.</p>` +
    `<button type="submit" class="ds-btn ds-btn--danger" ${disabled}>Révoquer le runtime</button>` +
    `<div data-msg class="meta" role="status" aria-live="polite"></div>` +
    `</form></details>`
  );
}

export async function renderRuntimeDetail(root: HTMLElement, ctx: ConfigurationContext, runtimeId: string): Promise<void> {
  const head = configTabsHtml("runtimes");
  if (!ctx.authed) {
    root.innerHTML =
      `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION)}${head}` +
      `${dsEmptyState("Connexion requise", "Définissez un jeton machine pour consulter ce runtime.")}</div>`;
    return;
  }
  root.innerHTML = `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION)}${head}${dsSkeleton(4)}</div>`;
  const [runtime, bindings] = await Promise.all([settle(getRuntime(ctx.client, runtimeId)), settle(listRuntimeBindings(ctx.client))]);
  if (!runtime.ok) {
    root.innerHTML =
      `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION, [{ label: "Recharger", id: "settings-runtime-reload" }])}${head}` +
      `<div class="state error" role="alert">Impossible de charger ce runtime : ${esc(describeError(runtime.error))}</div>` +
      `<p><a href="#/configuration/runtimes">Retour aux runtimes</a></p></div>`;
    root.querySelector("#settings-runtime-reload")?.addEventListener("click", () => {
      void renderRuntimeDetail(root, ctx, runtimeId);
    });
    return;
  }
  const related = bindings.ok ? bindings.value.filter((binding) => binding.target.runtime_id === runtime.value.id) : null;
  root.innerHTML =
    `<div class="settings">${settingsHeader(runtimeHumanTitle(runtime.value), "Détail d'un runtime — environnement/cible d'exécution enregistré.", [
      { label: "Recharger", id: "settings-runtime-reload" },
    ])}${head}` +
    `<p class="settings-back"><a href="#/configuration/runtimes">← Retour aux runtimes</a></p>` +
    runtimeDetailHtml(runtime.value, related, bindings.ok ? null : describeError(bindings.error)) +
    `</div>`;
  bindRuntimeDetail(root, ctx, runtime.value);
}

function bindRuntimeDetail(root: HTMLElement, ctx: ConfigurationContext, runtime: RuntimeRegistration): void {
  root.querySelector("#settings-runtime-reload")?.addEventListener("click", () => {
    void renderRuntimeDetail(root, ctx, runtime.id);
  });
  const updateForm = root.querySelector<HTMLFormElement>("[data-runtime-update]");
  updateForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = updateForm.querySelector("[data-msg]");
    const submit = updateForm.querySelector<HTMLButtonElement>("button[type=submit]");
    const built = buildRuntimeUpdate(formReader(updateForm));
    if (!built.ok) {
      if (msg !== null) msg.textContent = built.error;
      return;
    }
    if (submit !== null) submit.disabled = true;
    updateRuntime(ctx.client, runtime.id, built.value)
      .then(() => {
        void renderRuntimeDetail(root, ctx, runtime.id);
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
  const revokeForm = root.querySelector<HTMLFormElement>("[data-revoke]");
  revokeForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = revokeForm.querySelector("[data-msg]");
    const submit = revokeForm.querySelector<HTMLButtonElement>("button[type=submit]");
    if (!window.confirm("Révoquer ce runtime ? La ligne reste consultable mais n'est plus active.")) return;
    if (submit !== null) submit.disabled = true;
    revokeRuntime(ctx.client, runtime.id)
      .then(() => {
        void renderRuntimeDetail(root, ctx, runtime.id);
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
}

// ---------------------------------------------------------------------------
// Bindings
// ---------------------------------------------------------------------------

export interface BindingsPageState {
  query: string;
  scope: RuntimeLevel | "all";
}

export function initialBindingsState(): BindingsPageState {
  return { query: "", scope: "all" };
}

export function isBindingsDefaultState(state: BindingsPageState): boolean {
  return state.query.trim() === "" && state.scope === "all";
}

const BINDING_SCOPE_LABELS: Record<string, string> = {
  user: "Personnel (privé)",
  project_override: "Projet — remplacement",
  project_default: "Projet — défaut",
  studio_default: "Studio — défaut",
  session: "Session (éphémère, jamais stockée)",
};

const BINDING_SCOPE_DESCRIPTIONS: Record<string, string> = {
  user: "Choix personnel du propriétaire pour cette clé logique. Privé : jamais visible des autres utilisateurs.",
  project_override: "Choix stocké explicitement au niveau d'un projet (remplacement).",
  project_default: "Choix de repli stocké pour un projet.",
  studio_default: "Choix de repli stocké au niveau du studio.",
  session: "Contexte éphémère de résolution, jamais persisté par cette surface.",
};

export function bindingScopeLabel(level: RuntimeLevel): string {
  return BINDING_SCOPE_LABELS[level] ?? String(level);
}

export function bindingScopeDescription(level: RuntimeLevel): string {
  return BINDING_SCOPE_DESCRIPTIONS[level] ?? "";
}

export function bindingScopeTone(level: RuntimeLevel): DsTone {
  if (level === "user") return "info";
  if (level === "project_override") return "warning";
  if (level === "studio_default") return "ai";
  return "neutral";
}

/** Cible lisible d'un binding ; `runtimesById` résout un `runtime_id` en titre humain. */
export function bindingTargetHtml(binding: RuntimeBinding, runtimesById: Map<string, RuntimeRegistration>): string {
  const runtimeId = binding.target.runtime_id;
  if (nonEmpty(runtimeId)) {
    const runtime = runtimesById.get(runtimeId);
    const label = runtime !== undefined ? runtimeHumanTitle(runtime) : `Runtime ${shortId(runtimeId)}`;
    return `<code class="mono" title="${esc(runtimeId)}">${esc(label)}</code>`;
  }
  return runtimeTargetSummary(binding.target);
}

function bindingSearchText(binding: RuntimeBinding): string {
  return [binding.target_stable_key, binding.target_kind, binding.id, binding.project_id, bindingScopeLabel(binding.level), binding.target.runtime_id, binding.target.harness_ref, binding.target.provider_ref, binding.target.model_ref]
    .filter(nonEmpty)
    .join("\n")
    .toLowerCase();
}

export function filterBindings(bindings: RuntimeBinding[], state: BindingsPageState): RuntimeBinding[] {
  const query = state.query.trim().toLowerCase();
  return bindings.filter((binding) => {
    if (state.scope !== "all" && binding.level !== state.scope) return false;
    if (query === "") return true;
    return bindingSearchText(binding).includes(query);
  });
}

export function bindingsToolbarHtml(state: BindingsPageState, shown: number, total: number): string {
  const scopeOptions = (STORED_RUNTIME_LEVELS as readonly RuntimeLevel[])
    .map((level) => `<option value="${esc(level)}"${state.scope === level ? " selected" : ""}>${esc(bindingScopeLabel(level))}</option>`)
    .join("");
  return (
    `<div class="settings-toolbar" role="search" aria-label="Filtrer les bindings chargés">` +
    `<div class="ds-search"><span class="ds-search-icon" aria-hidden="true">⌕</span>` +
    `<label class="ds-sr-only" for="settings-bindings-search">Filtrer les bindings déjà chargés</label>` +
    `<input class="ds-input" type="search" id="settings-bindings-search" value="${esc(state.query)}" placeholder="Rechercher par clé logique…" autocomplete="off" /></div>` +
    `<label class="settings-filter"><span>Niveau</span><select class="ds-select" id="settings-bindings-scope">` +
    `<option value="all"${state.scope === "all" ? " selected" : ""}>Tous les niveaux</option>${scopeOptions}</select></label>` +
    `<button class="ds-btn ds-btn--ghost" type="button" data-reset${isBindingsDefaultState(state) ? " disabled" : ""}>Réinitialiser</button>` +
    `<p class="ds-list-sub settings-toolbar-count" role="status" aria-live="polite">${shown} binding(s) affiché(s) sur ${total} chargé(s) — recherche et filtre locaux.</p>` +
    `</div>`
  );
}

export function bindingCardHtml(binding: RuntimeBinding, runtimesById: Map<string, RuntimeRegistration>): string {
  const project = nonEmpty(binding.project_id)
    ? `<a href="#/projects/${esc(binding.project_id)}">Projet ${esc(shortId(binding.project_id))}</a>`
    : '<span class="meta">Sans projet</span>';
  return (
    `<li class="ds-list-item settings-binding-row"><div class="grow">` +
    `<h3 class="settings-card-title">${esc(kindMeta(binding.target_kind).singular)} · <code class="mono">${esc(binding.target_stable_key)}</code></h3>` +
    `<div class="ds-list-sub">${dsBadge(bindingScopeLabel(binding.level), bindingScopeTone(binding.level))} <span class="meta">${esc(bindingScopeDescription(binding.level))}</span></div>` +
    `<div class="ds-list-sub">Cible : ${bindingTargetHtml(binding, runtimesById)}</div>` +
    `<div class="ds-list-sub">${project} · propriétaire ${esc(shortId(binding.owner_user_id))} · créé le ${fmtTime(binding.created_at)}</div>` +
    `</div><div class="settings-row-side">` +
    `<button class="ds-btn ds-btn--sm ds-btn--danger" type="button" data-delete-binding="${esc(binding.id)}">Supprimer ce binding</button></div></li>`
  );
}

export function bindingsListHtml(bindings: RuntimeBinding[], runtimesById: Map<string, RuntimeRegistration>): string {
  return `<ul class="ds-list settings-list">${bindings.map((binding) => bindingCardHtml(binding, runtimesById)).join("")}</ul>`;
}

export function runtimeBindingsTableHtml(bindings: RuntimeBinding[]): string {
  if (bindings.length === 0) return dsEmptyState("Aucun binding", "Aucun binding ne référence ce runtime.");
  const rows = bindings
    .map(
      (binding) =>
        `<tr><td>${esc(kindMeta(binding.target_kind).singular)}</td><td><code class="mono">${esc(binding.target_stable_key)}</code></td>` +
        `<td>${esc(bindingScopeLabel(binding.level))}</td>` +
        `<td>${nonEmpty(binding.project_id) ? esc(shortId(binding.project_id)) : '<span class="meta">—</span>'}</td><td>${fmtTime(binding.created_at)}</td></tr>`,
    )
    .join("");
  return `<div class="ds-table-wrap"><table class="ds-table"><thead><tr><th>Type</th><th>Clé logique</th><th>Niveau</th><th>Projet</th><th>Créé le</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

export function bindingsTableHtml(bindings: RuntimeBinding[], emptyMessage: string): string {
  if (bindings.length === 0) return dsEmptyState("Aucun binding", emptyMessage);
  const rows = bindings
    .map(
      (binding) =>
        `<tr><td>${esc(kindMeta(binding.target_kind).singular)}</td><td><code class="mono">${esc(binding.target_stable_key)}</code></td>` +
        `<td>${esc(bindingScopeLabel(binding.level))}</td><td>${runtimeTargetSummary(binding.target)}</td></tr>`,
    )
    .join("");
  return `<div class="ds-table-wrap"><table class="ds-table"><thead><tr><th>Type</th><th>Clé logique</th><th>Niveau</th><th>Runtime visé</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function bindingsEmptyHtml(): string {
  return dsEmptyState(
    "Aucun binding stocké",
    "Un binding associe une clé logique (AgentDefinition ou ModelProfile) à un runtime. Utilisez « Nouveau binding » ci-dessous.",
  );
}

function bindingsNoMatchHtml(): string {
  return dsEmptyState("Aucun binding ne correspond", "Modifiez la recherche ou le filtre de niveau pour retrouver vos bindings déjà chargés.");
}

function createBindingFormHtml(runtimes: RuntimeRegistration[], stableKeys: string[]): string {
  const runtimeOptions = runtimes
    .map((runtime) => `<option value="${esc(runtime.id)}">${esc(runtimeHumanTitle(runtime))}</option>`)
    .join("");
  const datalist = stableKeys.map((key) => `<option value="${esc(key)}"></option>`).join("");
  const defaultProject = uiState.selectedProjectId ?? "";
  return (
    `<details class="editor settings-editor"><summary>Nouveau binding</summary><form class="stack-form" data-binding-create>` +
    `<p class="meta">Un binding dit « pour cette clé logique, utiliser ce runtime ». Les niveaux sont des choix stockés ; le niveau gagnant est décidé par le serveur (voir Inspecteur). Le niveau « session » est éphémère et n'est jamais stocké ici.</p>` +
    `<label class="stack">Niveau <select name="level">${(STORED_RUNTIME_LEVELS as readonly RuntimeLevel[]).map((level) => `<option value="${esc(level)}">${esc(bindingScopeLabel(level))}</option>`).join("")}</select></label>` +
    `<label class="stack">Projet (niveaux projet uniquement) <input name="project_id" value="${esc(defaultProject)}" placeholder="uuid" /></label>` +
    `<label class="stack">Type de cible <select name="target_kind"><option value="agent_definition">Agent Definition</option><option value="model_profile">Model Profile</option></select></label>` +
    `<label class="stack">Clé logique cible <input name="target_stable_key" list="settings-stable-keys" required placeholder="clé stable" /></label>` +
    `<datalist id="settings-stable-keys">${datalist}</datalist>` +
    `<label class="stack">Runtime cible (registre) <select name="runtime_id"><option value="">— sélectionner un runtime —</option>${runtimeOptions}</select></label>` +
    `<details class="settings-subeditor"><summary>Ou ancres inline (sans runtime du registre)</summary>` +
    `<label class="stack">Machine <input name="machine_id" placeholder="uuid" /></label>` +
    `<label class="stack">Harness <input name="harness_ref" /></label>` +
    `<label class="stack">Provider <input name="provider_ref" /></label>` +
    `<label class="stack">Model <input name="model_ref" /></label>` +
    `${capabilityFieldsHtml()}</details>` +
    `<button type="submit" class="ds-btn ds-btn--primary">Créer le binding</button>` +
    `<span class="meta">POST /runtime-bindings · Idempotency-Key par tentative · double soumission impossible</span>` +
    `<div data-msg class="meta" role="status" aria-live="polite"></div></form></details>`
  );
}

let bindingsState: BindingsPageState = initialBindingsState();

export async function renderBindings(root: HTMLElement, ctx: ConfigurationContext): Promise<void> {
  const head = configTabsHtml("bindings");
  if (!ctx.authed) {
    root.innerHTML =
      `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION)}${head}` +
      `${dsEmptyState("Connexion requise", "Définissez un jeton machine pour lire et configurer vos bindings.")}</div>`;
    return;
  }
  root.innerHTML = `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION)}${head}${dsSkeleton(4)}</div>`;
  const [bindings, runtimes, library] = await Promise.all([
    settle(listRuntimeBindings(ctx.client)),
    settle(listRuntimes(ctx.client)),
    settle(listLibraryResources(ctx.client, { limit: 200 })),
  ]);
  if (!bindings.ok) {
    root.innerHTML =
      `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION, [{ label: "Recharger", id: "settings-bindings-reload" }])}${head}` +
      `<div class="state error" role="alert">Impossible de charger les bindings : ${esc(describeError(bindings.error))}</div></div>`;
    root.querySelector("#settings-bindings-reload")?.addEventListener("click", () => {
      void renderBindings(root, ctx);
    });
    return;
  }
  const runtimeList = runtimes.ok ? runtimes.value : [];
  const runtimesById = new Map(runtimeList.map((runtime) => [runtime.id, runtime]));
  const stableKeys = library.ok
    ? [...new Set(library.value.filter((resource) => resource.kind === "agent_definition" || resource.kind === "model_profile").map((resource) => resource.stable_key))].sort()
    : [];
  const visible = filterBindings(bindings.value, bindingsState);
  const body = bindings.value.length === 0 ? bindingsEmptyHtml() : visible.length === 0 ? bindingsNoMatchHtml() : bindingsListHtml(visible, runtimesById);
  const degraded = runtimes.ok ? "" : `<p class="state error" role="alert">Runtimes indisponibles : ${esc(describeError(runtimes.error))} — les cibles du registre sont affichées sous forme d'identifiant.</p>`;
  root.innerHTML =
    `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION, [{ label: "Recharger", id: "settings-bindings-reload" }])}${head}` +
    `<section class="settings-domain"><h2>Règles d'affectation (bindings)</h2>` +
    `<p class="settings-intro">Un binding est un choix stocké par clé logique, pas un runtime ni un agent. Les bindings de niveau « personnel » sont privés : ceux des autres utilisateurs ne sont jamais exposés par l'API.</p>` +
    (bindings.value.length === 0 ? "" : bindingsToolbarHtml(bindingsState, visible.length, bindings.value.length)) +
    degraded +
    `<div id="settings-bindings-list">${body}</div>` +
    `${createBindingFormHtml(runtimeList, stableKeys)}` +
    `<p class="meta"><a href="#/inspector">Ouvrir l'Inspecteur</a> pour voir quel niveau gagne réellement à la résolution.</p>` +
    `</section></div>`;
  bindBindings(root, ctx, bindings.value, runtimesById, stableKeys);
}

function bindBindings(
  root: HTMLElement,
  ctx: ConfigurationContext,
  bindings: RuntimeBinding[],
  runtimesById: Map<string, RuntimeRegistration>,
  _stableKeys: string[],
): void {
  root.querySelector("#settings-bindings-reload")?.addEventListener("click", () => {
    void renderBindings(root, ctx);
  });
  bindBindingsToolbar(root, ctx, bindings, runtimesById);
  const form = root.querySelector<HTMLFormElement>("[data-binding-create]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = form.querySelector("[data-msg]");
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    const built = buildBindingCreate(formReader(form));
    if (!built.ok) {
      if (msg !== null) msg.textContent = built.error;
      return;
    }
    if (submit !== null) submit.disabled = true;
    createRuntimeBinding(ctx.client, built.value)
      .then(() => {
        bindingsState = initialBindingsState();
        void renderBindings(root, ctx);
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
  bindBindingDeletes(root, ctx);
}

function bindBindingDeletes(root: HTMLElement, ctx: ConfigurationContext): void {
  root.querySelectorAll<HTMLButtonElement>("[data-delete-binding]").forEach((button) => {
    button.addEventListener("click", () => {
      const bindingId = button.dataset["deleteBinding"];
      if (bindingId === undefined) return;
      if (!window.confirm("Supprimer ce binding ? Le runtime visé n'est pas supprimé.")) return;
      button.disabled = true;
      deleteRuntimeBinding(ctx.client, bindingId)
        .then(() => {
          void renderBindings(root, ctx);
        })
        .catch((error: unknown) => {
          button.disabled = false;
          dsNotify(`Suppression impossible. ${describeError(error)}`, "danger");
        });
    });
  });
}

function bindBindingsToolbar(
  root: HTMLElement,
  ctx: ConfigurationContext,
  bindings: RuntimeBinding[],
  runtimesById: Map<string, RuntimeRegistration>,
): void {
  const refresh = (): void => {
    const visible = filterBindings(bindings, bindingsState);
    const list = root.querySelector("#settings-bindings-list");
    if (list !== null) {
      list.innerHTML = bindings.length === 0 ? bindingsEmptyHtml() : visible.length === 0 ? bindingsNoMatchHtml() : bindingsListHtml(visible, runtimesById);
    }
    const toolbar = root.querySelector(".settings-toolbar");
    if (toolbar !== null) {
      const fresh = document.createElement("div");
      fresh.innerHTML = bindingsToolbarHtml(bindingsState, visible.length, bindings.length);
      toolbar.replaceWith(...fresh.childNodes);
    }
    bindBindingsToolbar(root, ctx, bindings, runtimesById);
    bindBindingDeletes(root, ctx);
  };
  const search = root.querySelector<HTMLInputElement>("#settings-bindings-search");
  search?.addEventListener("input", () => {
    bindingsState.query = search.value;
    refresh();
    const again = root.querySelector<HTMLInputElement>("#settings-bindings-search");
    if (again !== null) {
      again.focus();
      again.setSelectionRange(again.value.length, again.value.length);
    }
  });
  const scope = root.querySelector<HTMLSelectElement>("#settings-bindings-scope");
  scope?.addEventListener("change", () => {
    bindingsState.scope = scope.value === "all" ? "all" : (scope.value as RuntimeLevel);
    refresh();
  });
  root.querySelector("[data-reset]")?.addEventListener("click", () => {
    bindingsState = initialBindingsState();
    void renderBindings(root, ctx);
  });
}

// ---------------------------------------------------------------------------
// Projet (ressources, verrous, overrides)
// ---------------------------------------------------------------------------

let projectConfigOverride: string | null = null;

export function setProjectConfigProject(projectId: string | null): void {
  projectConfigOverride = projectId === null || projectId.trim() === "" ? null : projectId.trim();
}

function effectiveProjectId(): string | null {
  return projectConfigOverride ?? uiState.selectedProjectId;
}

export async function renderProjectConfig(root: HTMLElement, ctx: ConfigurationContext, tab: "resources" | "locks" | "overrides"): Promise<void> {
  const head = configTabsHtml("project");
  const tabs = projectTabsHtml(tab);
  if (!ctx.authed) {
    root.innerHTML =
      `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION)}${head}${tabs}` +
      `${dsEmptyState("Connexion requise", "Définissez un jeton machine pour lire la configuration de projet.")}</div>`;
    return;
  }
  root.innerHTML = `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION)}${head}${tabs}${dsSkeleton(3)}</div>`;
  const projectId = effectiveProjectId();
  let body: string;
  try {
    body = projectId === null ? statusBlock("empty", "Saisissez un identifiant de projet pour voir ses ressources, verrous et overrides.") : await projectTabBody(ctx, projectId, tab);
  } catch (error) {
    body = statusBlock("error", describeError(error));
  }
  root.innerHTML =
    `<div class="settings">${settingsHeader("Paramètres", SETTINGS_DESCRIPTION)}${head}${tabs}` +
    `<section class="settings-domain"><h2>Configuration de projet</h2>` +
    `<p class="settings-intro">${projectId === null ? "Aucun projet actif" : `Projet ${esc(projectId)}`}</p>` +
    `${projectSelectorHtml(projectId)}${body}</section></div>`;
  bindProjectTab(root, ctx, tab, projectId);
}

function projectSelectorHtml(projectId: string | null): string {
  return (
    `<form class="inline-form" data-project-select>` +
    `<label>Projet <input name="project_id" value="${esc(projectId ?? "")}" placeholder="uuid" /></label>` +
    `<button type="submit" class="ds-btn">Charger</button>` +
    `<span class="meta">${projectId === null ? "sélectionnez un projet ici ou dans la Vue d'ensemble" : "projet actif"}</span></form>`
  );
}

function projectTabsHtml(active: "resources" | "locks" | "overrides"): string {
  const labels: Record<"resources" | "locks" | "overrides", string> = { resources: "Ressources", locks: "Verrous", overrides: "Overrides" };
  return `<nav class="tabs" aria-label="Sections de configuration de projet">${(["resources", "locks", "overrides"] as const)
    .map((name) => `<a class="tab${name === active ? " active" : ""}" href="#/configuration/project/${name}"${name === active ? ' aria-current="page"' : ""}>${esc(labels[name])}</a>`)
    .join("")}</nav>`;
}

async function projectTabBody(ctx: ConfigurationContext, projectId: string, tab: "resources" | "locks" | "overrides"): Promise<string> {
  if (tab === "resources") return projectResourcesHtml(ctx, projectId);
  if (tab === "locks") return projectLocksHtml(ctx, projectId);
  return projectOverridesHtml(ctx, projectId);
}

function bindProjectTab(root: HTMLElement, ctx: ConfigurationContext, tab: "resources" | "locks" | "overrides", projectId: string | null): void {
  const selector = root.querySelector<HTMLFormElement>("[data-project-select]");
  selector?.addEventListener("submit", (event) => {
    event.preventDefault();
    setProjectConfigProject(formReader(selector).text("project_id"));
    void renderProjectConfig(root, ctx, tab);
  });
  if (tab !== "locks" || projectId === null) return;
  const lockForm = root.querySelector<HTMLFormElement>("[data-lock]");
  lockForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const read = formReader(lockForm);
    const resourceId = read.text("resource_id").trim();
    const version = Number(read.text("lock_version"));
    const msg = lockForm.querySelector("[data-msg]");
    if (resourceId === "" || !Number.isInteger(version) || version < 1) {
      if (msg !== null) msg.textContent = "Un identifiant de ressource et une version ≥ 1 sont requis.";
      return;
    }
    const submit = lockForm.querySelector<HTMLButtonElement>("button[type=submit]");
    if (submit !== null) submit.disabled = true;
    createLibraryLock(ctx.client, { project_id: projectId, resource_id: resourceId, locked_version: version })
      .then(() => {
        void renderProjectConfig(root, ctx, "locks");
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
  root.querySelectorAll<HTMLButtonElement>("[data-release-lock]").forEach((button) => {
    button.addEventListener("click", () => {
      const lockId = button.dataset["releaseLock"];
      if (lockId === undefined) return;
      if (!window.confirm("Libérer ce verrou de projet ?")) return;
      button.disabled = true;
      releaseLibraryLock(ctx.client, lockId)
        .then(() => {
          void renderProjectConfig(root, ctx, "locks");
        })
        .catch((error: unknown) => {
          button.disabled = false;
          dsNotify(`Libération impossible. ${describeError(error)}`, "danger");
        });
    });
  });
}

async function projectResourcesHtml(ctx: ConfigurationContext, projectId: string): Promise<string> {
  const resources: LibraryResource[] = await listLibraryResources(ctx.client, { projectId });
  const rows = resources
    .map(
      (resource) =>
        `<tr><td><a href="${esc(libraryKindHref(resource.kind, resource.id))}"><code class="mono">${esc(resource.stable_key)}</code></a></td>` +
        `<td>${esc(kindMeta(resource.kind).singular)}</td><td>${esc(scopeLabel(resource.scope))}</td>` +
        `<td>${resource.active_version === 0 ? '<span class="meta">aucune</span>' : `v${resource.active_version}`}</td><td>${esc(resource.status)}</td></tr>`,
    )
    .join("");
  const table =
    resources.length === 0
      ? statusBlock("empty", "Aucune ressource de bibliothèque propre à ce projet.")
      : `<div class="ds-table-wrap"><table class="ds-table"><thead><tr><th>Clé stable</th><th>Type</th><th>Portée</th><th>Active</th><th>Statut</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  return `<h3>Ressources</h3><p class="meta">GET /library?project_id=… — définitions propres au projet. Les ressources Studio/Utilisateur ne sont pas des appartenances de projet.</p>${table}`;
}

async function projectLocksHtml(ctx: ConfigurationContext, projectId: string): Promise<string> {
  const locks: LibraryProjectLock[] = await listLibraryLocks(ctx.client, projectId);
  const rows = locks
    .map(
      (lock) =>
        `<tr><td><code class="mono">${esc(lock.resource_id)}</code></td><td>v${lock.locked_version}</td>` +
        `<td>${esc(shortId(lock.created_by_user_id))}</td><td>${fmtTime(lock.created_at)}</td>` +
        `<td class="actions"><button type="button" class="ds-btn ds-btn--sm ds-btn--danger" data-release-lock="${esc(lock.id)}">Libérer</button></td></tr>`,
    )
    .join("");
  const table =
    locks.length === 0
      ? statusBlock("empty", "Aucun verrou pour ce projet.")
      : `<div class="ds-table-wrap"><table class="ds-table"><thead><tr><th>Ressource</th><th>Version verrouillée</th><th>Créé par</th><th>Créé le</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
  return (
    `<h3>Verrous</h3><p class="meta">RESOURCE | VERSION VERROUILLÉE — le verrou épingle une version pour ce projet ; la version effective n'est décidée que par le serveur (voir Inspecteur).</p>${table}` +
    `<form class="inline-form" data-lock>` +
    `<label>Identifiant de ressource <input name="resource_id" placeholder="uuid" required /></label>` +
    `<label>Version <input name="lock_version" type="number" min="1" required /></label>` +
    `<button type="submit" class="ds-btn">Poser le verrou</button>` +
    `<span class="meta">POST /library-locks</span><div data-msg class="meta" role="status" aria-live="polite"></div></form>`
  );
}

async function projectOverridesHtml(ctx: ConfigurationContext, projectId: string): Promise<string> {
  const [overrides, defaults, studioDefaults] = await Promise.all([
    settle(listRuntimeBindings(ctx.client, { projectId, level: "project_override" })),
    settle(listRuntimeBindings(ctx.client, { projectId, level: "project_default" })),
    settle(listRuntimeBindings(ctx.client, { level: "studio_default" })),
  ]);
  const section = (title: string, meta: string, result: Settled<RuntimeBinding[]>, empty: string): string => {
    const body = result.ok
      ? bindingsTableHtml(result.value, empty)
      : `<div class="ds-notice ds-notice--warning" role="alert"><strong>Section indisponible.</strong> ${esc(describeError(result.error))}</div>`;
    return `<h3>${esc(title)}</h3><p class="meta">${esc(meta)}</p>${body}`;
  };
  return (
    section("Overrides de projet", "GET /runtime-bindings?project_id=…&level=project_override — épinglage explicite pour ce projet.", overrides, "Aucun override de projet.") +
    section("Défauts de projet", "level=project_default — repli pour ce projet, distinct d'un override.", defaults, "Aucun défaut de projet.") +
    section("Défauts de studio", "level=studio_default — affichés uniquement si le serveur les renvoie pour ce jeton.", studioDefaults, "Aucun défaut de studio visible.") +
    `<p><a href="#/inspector">Ouvrir l'Inspecteur de résolution</a> pour voir quel niveau gagne réellement pour une AgentDefinition donnée.</p>`
  );
}
