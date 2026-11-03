/**
 * P12 — Configuration authoring forms (pure builders, no server logic).
 *
 * Open references stay open: harness/provider/model refs are free strings and
 * the UI never proposes a closed vendor catalog (DEC-0070). The harness
 * datalist only suggests known harness ids; any string is still accepted.
 * The server remains the only validator and resolver (DEC-0076); every 4xx it
 * returns is surfaced verbatim.
 */
import type { components } from "../openapi-schema";
import type { CapabilityRequirement, RuntimeCapabilities, RuntimeLevel, LibraryKind } from "../libraryFormat";
import { STORED_RUNTIME_LEVELS } from "../bindingsApi";
import type { FormReader } from "./libraryForms";
import { esc } from "../ui";
import { isDashboardIdentity } from "../machinesApi";

export type RuntimeRegistrationCreate = components["schemas"]["RuntimeRegistrationCreate"];
export type RuntimeRegistrationUpdate = components["schemas"]["RuntimeRegistrationUpdate"];
export type RuntimeRegistrationUpdateRequest = components["schemas"]["RuntimeRegistrationUpdateRequest"];
export type RuntimeBindingCreate = components["schemas"]["RuntimeBindingCreate"];
export type RuntimeTarget = components["schemas"]["RuntimeTarget"];

/** Builder result; `field` names the input to mark invalid and focus. */
export type ConfigBuildResult<T> = { ok: true; value: T } | { ok: false; error: string; field?: string };

export const HARNESS_SUGGESTIONS: readonly string[] = ["claude-code", "opencode", "codex"];

export const ANCHOR_REQUIRED_ERROR = "au moins un ancrage est requis : poste, outil (harness), fournisseur ou modèle";

function trimOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

// ---------------------------------------------------------------------------
// Machines (postes) — options de sélection
// ---------------------------------------------------------------------------

export interface MachineListItem {
  id: string;
  display_name: string;
  workstation_id?: string | null;
}

export interface MachineOption {
  id: string;
  label: string;
}

function machineName(machine: MachineListItem): string {
  return machine.display_name.trim() === "" ? "Poste sans nom" : machine.display_name.trim();
}

/** Libellés humains des machines ; un outil rattaché à un poste devient « Poste › outil ». */
export function machineOptionsFrom(machines: readonly MachineListItem[]): MachineOption[] {
  const byId = new Map(machines.map((machine) => [machine.id, machine]));
  return machines
    .filter((machine) => typeof machine.id === "string" && machine.id !== "" && !isDashboardIdentity(machine.display_name))
    .map((machine) => {
      const parentId = machine.workstation_id;
      const parent = parentId !== null && parentId !== undefined && parentId !== machine.id ? byId.get(parentId) : undefined;
      const label = parent === undefined ? machineName(machine) : `${machineName(parent)} › ${machineName(machine)}`;
      return { id: machine.id, label };
    })
    .sort((a, b) => a.label.localeCompare(b.label));
}

/**
 * Champ « Poste » : une liste des postes de l'utilisateur, ou, si la liste n'a
 * pas pu être chargée (`options === null`), l'ancien champ texte libre.
 */
export function machineFieldHtml(options: MachineOption[] | null, selected: string | null, disabled = false, label = "Poste"): string {
  const attr = disabled ? " disabled" : "";
  const current = selected ?? "";
  if (options === null) {
    return (
      `<label class="stack">${esc(label)} (facultatif) <input name="machine_id" value="${esc(current)}" placeholder="identifiant du poste" autocomplete="off"${attr} />` +
      `<span class="meta">Liste des postes indisponible : saisissez l'identifiant, ou laissez vide pour une cible distante.</span></label>`
    );
  }
  const known = current === "" || options.some((option) => option.id === current);
  const extra = known ? "" : `<option value="${esc(current)}" selected>Poste actuel (non listé)</option>`;
  const items = options
    .map((option) => `<option value="${esc(option.id)}"${option.id === current ? " selected" : ""}>${esc(option.label)}</option>`)
    .join("");
  return (
    `<label class="stack">${esc(label)} <select name="machine_id"${attr}>` +
    `<option value=""${current === "" ? " selected" : ""}>Aucun poste (cible distante)</option>${items}${extra}</select></label>`
  );
}

/** Champ « Outil (harness) » : chaîne ouverte suggérée par un datalist. */
export function harnessFieldHtml(listId: string, value: string | null, disabled = false): string {
  const attr = disabled ? " disabled" : "";
  const suggestions = HARNESS_SUGGESTIONS.map((harness) => `<option value="${esc(harness)}"></option>`).join("");
  return (
    `<label class="stack">Outil (harness) <input name="harness_ref" list="${esc(listId)}" value="${esc(value ?? "")}" placeholder="ex. claude-code (chaîne libre)" autocomplete="off"${attr} /></label>` +
    `<datalist id="${esc(listId)}">${suggestions}</datalist>`
  );
}

// ---------------------------------------------------------------------------
// Capacités
// ---------------------------------------------------------------------------

const TOOLS_PATTERN = "\\s*[^\\s,]+(\\s*,\\s*[^\\s,]+)*\\s*,?\\s*";

/** Capability inputs read back by `readCapabilities` (`cap_*` names), optionally pre-filled. */
export function capabilityFieldsHtml(disabled = false, values: RuntimeCapabilities | null = null): string {
  const attr = disabled ? " disabled" : "";
  const text = (raw: string | number | null | undefined): string => (raw === null || raw === undefined ? "" : ` value="${esc(raw)}"`);
  const check = (on: boolean | undefined): string => (on === true ? " checked" : "");
  return (
    `<label class="stack">Raisonnement <input name="cap_reasoning" placeholder="étiquette libre (facultatif)"${text(values?.reasoning)}${attr} /></label>` +
    `<label class="stack">Fenêtre de contexte (jetons) <input name="cap_context_window" type="number" min="1" step="1" inputmode="numeric" placeholder="entier positif (facultatif)"${text(values?.context_window)}${attr} /></label>` +
    `<label class="stack">Outils <input name="cap_tools" pattern="${TOOLS_PATTERN}" title="Noms séparés par des virgules, sans espace dans un nom" placeholder="ex. shell,git (facultatif)"${text(values === null ? null : (values.tools ?? []).join(","))}${attr} /></label>` +
    `<label class="stack">Multimodal <input name="cap_multimodal" placeholder="étiquette libre (facultatif)"${text(values?.multimodal)}${attr} /></label>` +
    `<label class="stack">Coût <input name="cap_cost" placeholder="étiquette libre (facultatif)"${text(values?.cost)}${attr} /></label>` +
    `<label class="stack">Latence <input name="cap_latency" placeholder="étiquette libre (facultatif)"${text(values?.latency)}${attr} /></label>` +
    `<label class="check">Code <input name="cap_coding" type="checkbox"${check(values?.coding)}${attr} /></label>` +
    `<label class="check">Local <input name="cap_local" type="checkbox"${check(values?.local)}${attr} /></label>`
  );
}

/** `clé=valeur` lines → non-secret metadata; a malformed line is reported with its number. */
export function parseMetadataLines(text: string): ConfigBuildResult<Record<string, string>> {
  const metadata: Record<string, string> = {};
  const lines = text.split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = (lines[index] ?? "").trim();
    if (trimmed === "") continue;
    const separator = trimmed.indexOf("=");
    const key = separator <= 0 ? "" : trimmed.slice(0, separator).trim();
    if (key === "") {
      return { ok: false, error: `métadonnées, ligne ${index + 1} : format attendu clé=valeur`, field: "metadata" };
    }
    metadata[key] = trimmed.slice(separator + 1).trim();
  }
  return { ok: true, value: metadata };
}

/** Metadata baseline rendered back as `clé=valeur` lines (primitive values only). */
export function metadataLinesFrom(metadata: Record<string, unknown> | null | undefined): string {
  if (metadata === null || metadata === undefined) return "";
  return Object.entries(metadata)
    .filter(([, value]) => typeof value === "string" || typeof value === "number" || typeof value === "boolean")
    .map(([key, value]) => `${key}=${String(value)}`)
    .join("\n");
}

export function readCapabilities(read: FormReader): ConfigBuildResult<RuntimeCapabilities> {
  const tools: string[] = [];
  for (const raw of read.text("cap_tools").split(",")) {
    const tool = raw.trim();
    if (tool === "") continue;
    if (/\s/.test(tool)) {
      return { ok: false, error: `outils : « ${tool} » contient un espace — séparez les noms par des virgules`, field: "cap_tools" };
    }
    tools.push(tool);
  }
  const capabilities: RuntimeCapabilities = {
    coding: read.checked("cap_coding"),
    tools,
    local: read.checked("cap_local"),
  };
  const contextWindowRaw = read.text("cap_context_window").trim();
  if (contextWindowRaw !== "") {
    const contextWindow = /^\d+$/.test(contextWindowRaw) ? Number(contextWindowRaw) : Number.NaN;
    if (!Number.isSafeInteger(contextWindow) || contextWindow < 1) {
      return { ok: false, error: "la fenêtre de contexte doit être un entier positif", field: "cap_context_window" };
    }
    capabilities.context_window = contextWindow;
  }
  const reasoning = trimOrNull(read.text("cap_reasoning"));
  const multimodal = trimOrNull(read.text("cap_multimodal"));
  const cost = trimOrNull(read.text("cap_cost"));
  const latency = trimOrNull(read.text("cap_latency"));
  if (reasoning !== null) capabilities.reasoning = reasoning;
  if (multimodal !== null) capabilities.multimodal = multimodal;
  if (cost !== null) capabilities.cost = cost;
  if (latency !== null) capabilities.latency = latency;
  return { ok: true, value: capabilities };
}

function normalizedCapabilities(capabilities: RuntimeCapabilities | null | undefined): string {
  const source = capabilities ?? { coding: false, tools: [], local: false };
  const normalized: Record<string, unknown> = {
    coding: source.coding === true,
    tools: [...(source.tools ?? [])],
    local: source.local === true,
  };
  for (const key of ["reasoning", "context_window", "multimodal", "cost", "latency"] as const) {
    const value = source[key];
    if (value !== null && value !== undefined) normalized[key] = value;
  }
  return JSON.stringify(normalized);
}

// ---------------------------------------------------------------------------
// Écarts déclarés (indicatif — le serveur tranche)
// ---------------------------------------------------------------------------

export interface CapabilityGap {
  key: string;
  label: string;
  required: string;
  declared: string;
}

/**
 * Indicative comparison between a ModelProfile requirement and what a runtime
 * declares. Never a verdict: compatibility is decided server-side (Inspecteur).
 */
export function declaredCapabilityGaps(
  requirement: CapabilityRequirement | null | undefined,
  capabilities: RuntimeCapabilities | null | undefined,
): CapabilityGap[] {
  if (requirement === null || requirement === undefined) return [];
  const caps = capabilities ?? { coding: false, tools: [], local: false };
  const gaps: CapabilityGap[] = [];
  if (requirement.coding === true && caps.coding !== true) {
    gaps.push({ key: "coding", label: "Code", required: "requis", declared: "non déclaré" });
  }
  const min = requirement.context_window_min;
  if (min !== null && min !== undefined) {
    const declared = caps.context_window;
    if (declared === null || declared === undefined) {
      gaps.push({ key: "context_window_min", label: "Fenêtre de contexte", required: `≥ ${min}`, declared: "non déclarée" });
    } else if (declared < min) {
      gaps.push({ key: "context_window_min", label: "Fenêtre de contexte", required: `≥ ${min}`, declared: String(declared) });
    }
  }
  const tools = new Set(caps.tools ?? []);
  for (const tool of requirement.tools_required ?? []) {
    if (!tools.has(tool)) gaps.push({ key: `tool:${tool}`, label: "Outil", required: tool, declared: "non déclaré" });
  }
  if (requirement.local_compatible === true && caps.local !== true) {
    gaps.push({ key: "local_compatible", label: "Local", required: "requis", declared: "non déclaré" });
  }
  return gaps;
}

// ---------------------------------------------------------------------------
// Builders
// ---------------------------------------------------------------------------

export interface TargetAnchorInput {
  runtimeId: string;
  machineId: string;
  harnessRef: string;
  providerRef: string;
  modelRef: string;
}

/** A runtime target with no declared capabilities (server defaults apply). */
function emptyCapabilities(): RuntimeCapabilities {
  return { coding: false, tools: [], local: false };
}

/**
 * Builds a `RuntimeTarget` from raw anchors: `runtime_id` is exclusive (a
 * registry reference carries its own refs/capabilities), otherwise at least one
 * open inline anchor is required. Returns `null` when neither is provided.
 */
export function buildBindingCreateTarget(input: TargetAnchorInput): RuntimeTarget | null {
  const runtimeId = trimOrNull(input.runtimeId);
  if (runtimeId !== null) return { runtime_id: runtimeId, capabilities: emptyCapabilities() };
  const machineId = trimOrNull(input.machineId);
  const harness = trimOrNull(input.harnessRef);
  const provider = trimOrNull(input.providerRef);
  const model = trimOrNull(input.modelRef);
  if (machineId === null && harness === null && provider === null && model === null) return null;
  return {
    machine_id: machineId,
    harness_ref: harness,
    provider_ref: provider,
    model_ref: model,
    capabilities: emptyCapabilities(),
  };
}

export function buildRuntimeCreate(read: FormReader): ConfigBuildResult<RuntimeRegistrationCreate> {
  const machineId = trimOrNull(read.text("machine_id"));
  const harness = trimOrNull(read.text("harness_ref"));
  const provider = trimOrNull(read.text("provider_ref"));
  const model = trimOrNull(read.text("model_ref"));
  if (machineId === null && harness === null && provider === null && model === null) {
    return { ok: false, error: ANCHOR_REQUIRED_ERROR, field: "harness_ref" };
  }
  const capabilities = readCapabilities(read);
  if (!capabilities.ok) return capabilities;
  const metadata = parseMetadataLines(read.text("metadata"));
  if (!metadata.ok) return metadata;
  const value: RuntimeRegistrationCreate = {
    machine_id: machineId,
    harness_ref: harness,
    provider_ref: provider,
    model_ref: model,
    capabilities: capabilities.value,
    capability_source: "declared",
    runtime_metadata: metadata.value,
  };
  return { ok: true, value };
}

/** Current values the update form was pre-filled with. */
export interface RuntimeUpdateBaseline {
  machine_id?: string | null;
  harness_ref?: string | null;
  provider_ref?: string | null;
  model_ref?: string | null;
  capabilities?: RuntimeCapabilities | null;
  runtime_metadata?: Record<string, unknown> | null;
}

const REF_FIELDS = [
  { name: "harness_ref", label: "l'outil (harness)" },
  { name: "provider_ref", label: "le fournisseur" },
  { name: "model_ref", label: "le modèle" },
] as const;

/** Only fields that differ from `baseline` are sent; `expected_version` guards stale writes. */
export function buildRuntimeUpdate(read: FormReader, baseline: RuntimeUpdateBaseline = {}): ConfigBuildResult<RuntimeRegistrationUpdateRequest> {
  const update: RuntimeRegistrationUpdate = { detach_machine: false };
  let changed = false;
  for (const ref of REF_FIELDS) {
    const next = trimOrNull(read.text(ref.name));
    const current = trimOrNull(baseline[ref.name] ?? "");
    if (next === current) continue;
    if (next === null) {
      return { ok: false, error: `impossible d'effacer ${ref.label} : gardez la valeur actuelle ou saisissez-en une autre`, field: ref.name };
    }
    update[ref.name] = next;
    changed = true;
  }
  const machineNext = trimOrNull(read.text("machine_id"));
  const machineCurrent = trimOrNull(baseline.machine_id ?? "");
  if (machineNext !== machineCurrent) {
    if (machineNext === null) update.detach_machine = true;
    else update.machine_id = machineNext;
    changed = true;
  }
  const capabilities = readCapabilities(read);
  if (!capabilities.ok) return capabilities;
  if (normalizedCapabilities(capabilities.value) !== normalizedCapabilities(baseline.capabilities)) {
    update.capabilities = capabilities.value;
    changed = true;
  }
  const metadata = parseMetadataLines(read.text("metadata"));
  if (!metadata.ok) return metadata;
  const baselineMetadata = parseMetadataLines(metadataLinesFrom(baseline.runtime_metadata));
  const before = baselineMetadata.ok ? baselineMetadata.value : {};
  if (JSON.stringify(sortedEntries(metadata.value)) !== JSON.stringify(sortedEntries(before))) {
    update.runtime_metadata = metadata.value;
    changed = true;
  }
  const expectedRaw = read.text("expected_version").trim();
  const expected = /^\d+$/.test(expectedRaw) ? Number(expectedRaw) : Number.NaN;
  if (!Number.isInteger(expected) || expected < 1) {
    return { ok: false, error: "la version attendue (Avancé) doit être un entier ≥ 1", field: "expected_version" };
  }
  if (!changed) return { ok: false, error: "aucune modification à enregistrer" };
  return { ok: true, value: { update, expected_version: expected } };
}

function sortedEntries(record: Record<string, string>): [string, string][] {
  return Object.entries(record).sort(([a], [b]) => a.localeCompare(b));
}

export function buildBindingCreate(read: FormReader): ConfigBuildResult<RuntimeBindingCreate> {
  const level = read.text("level");
  if (!(STORED_RUNTIME_LEVELS as readonly string[]).includes(level)) {
    return { ok: false, error: "le niveau doit être user, project_override, project_default ou studio_default", field: "level" };
  }
  const projectId = trimOrNull(read.text("project_id"));
  if ((level === "project_override" || level === "project_default") && projectId === null) {
    return { ok: false, error: `${level} exige un ID de projet`, field: "project_id" };
  }
  const targetKind = read.text("target_kind");
  if (targetKind !== "agent_definition" && targetKind !== "model_profile") {
    return { ok: false, error: "le type de cible doit être agent_definition ou model_profile", field: "target_kind" };
  }
  const stableKey = read.text("target_stable_key").trim();
  if (stableKey === "") return { ok: false, error: "la clé stable cible est requise", field: "target_stable_key" };

  const capabilities = readCapabilities(read);
  if (!capabilities.ok) return capabilities;
  const runtimeId = trimOrNull(read.text("runtime_id"));
  let target: RuntimeTarget;
  if (runtimeId !== null) {
    target = { runtime_id: runtimeId, capabilities: capabilities.value };
  } else {
    const machineId = trimOrNull(read.text("machine_id"));
    const harness = trimOrNull(read.text("harness_ref"));
    const provider = trimOrNull(read.text("provider_ref"));
    const model = trimOrNull(read.text("model_ref"));
    if (machineId === null && harness === null && provider === null && model === null) {
      return {
        ok: false,
        error: "choisissez un runtime enregistré, ou au moins un ancrage direct (poste, outil, fournisseur ou modèle)",
        field: "runtime_id",
      };
    }
    target = {
      machine_id: machineId,
      harness_ref: harness,
      provider_ref: provider,
      model_ref: model,
      capabilities: capabilities.value,
    };
  }
  return {
    ok: true,
    value: {
      level: level as RuntimeLevel,
      project_id: projectId,
      target_kind: targetKind as LibraryKind,
      target_stable_key: stableKey,
      target,
    },
  };
}
