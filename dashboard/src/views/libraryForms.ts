/**
 * P12 — structured Library authoring forms (pure builders, no server logic).
 *
 * The forms help a human produce a canonical payload; they never validate
 * authoritatively. The server stays the only validator (`422 invalid_content`,
 * `422 invalid_workflow`, `422 invalid_binding`), and every error it returns is
 * surfaced verbatim by the views.
 */
import { esc } from "../ui";
import { LIBRARY_KINDS, type LibraryKind, type LibraryKindSlug } from "../libraryFormat";

export interface FormReader {
  text(name: string): string;
  checked(name: string): boolean;
}

export type BuildResult<T> = { ok: true; value: T } | { ok: false; error: string };

function trimOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function numberOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export function contentSchemaFor(kind: LibraryKind): string {
  return `studio.library.${kind}/v1`;
}

/** Per-kind content inputs, excluding `content_schema` (added on build). */
export function contentFieldsHtml(kind: LibraryKind): string {
  switch (kind) {
    case "rule":
    case "skill":
      return `<label class="stack">Texte <textarea name="text" rows="8" required placeholder="Texte canonique de ${kind === "rule" ? "cette règle" : "cette compétence"}"></textarea></label>`;
    case "agent_definition":
      return (
        `<label class="stack">Résumé <input name="summary" placeholder="résumé en une ligne (facultatif)" /></label>` +
        `<label class="stack">Usage prévu <textarea name="intended_use" rows="3" placeholder="usage prévu (facultatif)"></textarea></label>`
      );
    case "model_profile":
      return (
        `<label class="stack">Description du profil <input name="profile_description" placeholder="facultatif" /></label>` +
        `<label class="stack">Raisonnement <input name="reasoning" placeholder="étiquette libre, ex. élevé (facultatif)" /></label>` +
        `<label class="stack">Fenêtre de contexte min <input name="context_window_min" type="number" min="1" placeholder="facultatif" /></label>` +
        `<label class="stack">Outils requis <input name="tools_required" placeholder="séparés par des virgules (facultatif)" /></label>` +
        `<label class="stack">Multimodal <input name="multimodal" placeholder="étiquette libre (facultatif)" /></label>` +
        `<label class="stack">Coût <input name="cost" placeholder="étiquette libre (facultatif)" /></label>` +
        `<label class="stack">Latence <input name="latency" placeholder="étiquette libre (facultatif)" /></label>` +
        `<label class="check">Code <input name="coding" type="checkbox" /></label>` +
        `<label class="check">Compatible local <input name="local_compatible" type="checkbox" /></label>`
      );
    case "workflow":
      return `<label class="stack">Résumé <input name="summary" placeholder="facultatif" /></label>`;
  }
}

export function buildContent(kind: LibraryKind, read: FormReader): BuildResult<Record<string, unknown>> {
  const schema = contentSchemaFor(kind);
  if (kind === "rule" || kind === "skill") {
    const text = read.text("text").trim();
    if (text === "") return { ok: false, error: "Le texte est obligatoire." };
    return { ok: true, value: { content_schema: schema, text } };
  }
  if (kind === "agent_definition") {
    const summary = trimOrNull(read.text("summary"));
    const intendedUse = trimOrNull(read.text("intended_use"));
    const value: Record<string, unknown> = { content_schema: schema };
    if (summary !== null) value["summary"] = summary;
    if (intendedUse !== null) value["intended_use"] = intendedUse;
    return { ok: true, value };
  }
  if (kind === "model_profile") {
    const tools = read
      .text("tools_required")
      .split(",")
      .map((tool) => tool.trim())
      .filter((tool) => tool !== "");
    const requirements: Record<string, unknown> = { coding: read.checked("coding"), local_compatible: read.checked("local_compatible"), tools_required: tools };
    const reasoning = trimOrNull(read.text("reasoning"));
    const multimodal = trimOrNull(read.text("multimodal"));
    const cost = trimOrNull(read.text("cost"));
    const latency = trimOrNull(read.text("latency"));
    const contextWindow = numberOrNull(read.text("context_window_min"));
    if (reasoning !== null) requirements["reasoning"] = reasoning;
    if (multimodal !== null) requirements["multimodal"] = multimodal;
    if (cost !== null) requirements["cost"] = cost;
    if (latency !== null) requirements["latency"] = latency;
    if (contextWindow !== null) requirements["context_window_min"] = contextWindow;
    const description = trimOrNull(read.text("profile_description"));
    const value: Record<string, unknown> = { content_schema: schema, requirements };
    if (description !== null) value["description"] = description;
    return { ok: true, value };
  }
  return { ok: false, error: "Le contenu d'un flux se construit depuis ses participants et ses entrées/sorties." };
}

export interface DependencyInput {
  kind: string;
  stable_key: string;
  version: string;
  relation: string;
}

export type DependencyPinInput = { kind: LibraryKind; stable_key: string; version: number; relation?: string };

export function dependencyRowHtml(values: Partial<DependencyInput> = {}): string {
  const kindOptions = LIBRARY_KINDS.map(
    (meta) => `<option value="${esc(meta.kind)}"${meta.kind === values.kind ? " selected" : ""}>${esc(meta.singular)}</option>`,
  ).join("");
  return (
    `<span class="repeat-row" data-row="dependency">` +
    `<label class="cell">Type <select data-field="kind">${kindOptions}</select></label>` +
    `<label class="cell">Clé stable <input data-field="stable_key" value="${esc(values.stable_key ?? "")}" placeholder="clé stable" /></label>` +
    `<label class="cell">Version <input data-field="version" type="number" min="1" value="${esc(values.version ?? "")}" placeholder="1" /></label>` +
    `<label class="cell">Relation <input data-field="relation" value="${esc(values.relation ?? "")}" placeholder="déduite si vide" /></label>` +
    `<button type="button" data-remove-row aria-label="Retirer la dépendance">Retirer</button>` +
    `</span>`
  );
}

export function buildDependencies(rows: DependencyInput[]): BuildResult<DependencyPinInput[]> {
  const pins: DependencyPinInput[] = [];
  for (const row of rows) {
    const stableKey = row.stable_key.trim();
    const versionRaw = row.version.trim();
    if (stableKey === "" && versionRaw === "") continue;
    const meta = LIBRARY_KINDS.find((candidate) => candidate.kind === row.kind);
    if (meta === undefined) return { ok: false, error: `Type de dépendance inconnu : ${row.kind}` };
    if (stableKey === "") return { ok: false, error: "La clé stable de la dépendance est obligatoire." };
    const version = Number(versionRaw);
    if (!Number.isInteger(version) || version < 1) return { ok: false, error: `La dépendance ${stableKey} exige une version ≥ 1.` };
    const relation = row.relation.trim();
    const pin: DependencyPinInput = { kind: meta.kind, stable_key: stableKey, version };
    if (relation !== "") pin.relation = relation;
    pins.push(pin);
  }
  return { ok: true, value: pins };
}

export function participantRowHtml(values: Partial<{ participant_id: string; agent_stable_key: string; depends_on: string; description: string }> = {}): string {
  return (
    `<span class="repeat-row" data-row="participant">` +
    `<label class="cell">Identifiant du participant <input data-field="participant_id" value="${esc(values.participant_id ?? "")}" placeholder="implementer" /></label>` +
    `<label class="cell">Clé stable de l'agent <input data-field="agent_stable_key" value="${esc(values.agent_stable_key ?? "")}" placeholder="review-helper" /></label>` +
    `<label class="cell">Dépend de <input data-field="depends_on" value="${esc(values.depends_on ?? "")}" placeholder="identifiants séparés par des virgules" /></label>` +
    `<label class="cell">Description <input data-field="description" value="${esc(values.description ?? "")}" placeholder="facultatif" /></label>` +
    `<button type="button" data-remove-row aria-label="Retirer le participant">Retirer</button>` +
    `</span>`
  );
}

export interface ParticipantInput {
  participant_id: string;
  agent_stable_key: string;
  depends_on: string;
  description: string;
}

export interface WorkflowParticipantPayload {
  participant_id: string;
  agent_stable_key: string;
  depends_on: string[];
  description?: string;
}

export function buildParticipants(rows: ParticipantInput[]): BuildResult<WorkflowParticipantPayload[]> {
  const participants: WorkflowParticipantPayload[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    const participantId = row.participant_id.trim();
    const agentKey = row.agent_stable_key.trim();
    if (participantId === "" && agentKey === "") continue;
    if (participantId === "") return { ok: false, error: "L'identifiant du participant est obligatoire." };
    if (agentKey === "") return { ok: false, error: `Le participant ${participantId} exige une clé stable d'agent.` };
    if (seen.has(participantId)) return { ok: false, error: `Participant en double : ${participantId}.` };
    seen.add(participantId);
    const dependsOn = row.depends_on
      .split(",")
      .map((dep) => dep.trim())
      .filter((dep) => dep !== "");
    const payload: WorkflowParticipantPayload = { participant_id: participantId, agent_stable_key: agentKey, depends_on: dependsOn };
    const description = trimOrNull(row.description);
    if (description !== null) payload.description = description;
    participants.push(payload);
  }
  if (participants.length === 0) return { ok: false, error: "Au moins un participant est obligatoire." };
  return { ok: true, value: participants };
}

export function ioRowHtml(rowKind: "input" | "output", values: Partial<{ name: string; description: string; type: string; required: string; source_participant: string; source_name: string }> = {}): string {
  const source =
    rowKind === "output"
      ? `<label class="cell">Participant source <input data-field="source_participant" value="${esc(values.source_participant ?? "")}" placeholder="identifiant producteur" /></label>` +
        `<label class="cell">Nom source <input data-field="source_name" value="${esc(values.source_name ?? "")}" placeholder="nom de la sortie" /></label>`
      : "";
  return (
    `<span class="repeat-row" data-row="io-${rowKind}">` +
    `<label class="cell">Nom <input data-field="name" value="${esc(values.name ?? "")}" placeholder="nom" /></label>` +
    `<label class="cell">Description <input data-field="description" value="${esc(values.description ?? "")}" placeholder="facultatif" /></label>` +
    `<label class="cell">Type <input data-field="type" value="${esc(values.type ?? "")}" placeholder="texte libre (facultatif)" /></label>` +
    `<label class="cell">Requise <select data-field="required"><option value="true"${values.required === "false" ? "" : " selected"}>requise</option><option value="false"${values.required === "false" ? " selected" : ""}>facultative</option></select></label>` +
    source +
    `<button type="button" data-remove-row aria-label="Retirer ${rowKind === "input" ? "l'entrée" : "la sortie"}">Retirer</button>` +
    `</span>`
  );
}

export interface IoInput {
  name: string;
  description: string;
  type: string;
  required: string;
  source_participant: string;
  source_name: string;
}

export interface WorkflowIoPayload {
  name: string;
  description?: string;
  required: boolean;
  type?: string;
  source?: { participant_id: string; name: string };
}

export function buildWorkflowInputs(rows: IoInput[]): BuildResult<WorkflowIoPayload[]> {
  const out: WorkflowIoPayload[] = [];
  for (const row of rows) {
    const name = row.name.trim();
    if (name === "") continue;
    const payload: WorkflowIoPayload = { name, required: row.required !== "false" };
    const description = trimOrNull(row.description);
    const type = trimOrNull(row.type);
    if (description !== null) payload.description = description;
    if (type !== null) payload.type = type;
    out.push(payload);
  }
  return { ok: true, value: out };
}

export function buildWorkflowOutputs(rows: IoInput[]): BuildResult<WorkflowIoPayload[]> {
  const out: WorkflowIoPayload[] = [];
  for (const row of rows) {
    const name = row.name.trim();
    if (name === "") continue;
    const participant = row.source_participant.trim();
    const sourceName = row.source_name.trim();
    if (participant === "" || sourceName === "") {
      return { ok: false, error: `La sortie ${name} exige un participant et un nom sources.` };
    }
    const payload: WorkflowIoPayload = {
      name,
      required: row.required !== "false",
      source: { participant_id: participant, name: sourceName },
    };
    const description = trimOrNull(row.description);
    const type = trimOrNull(row.type);
    if (description !== null) payload.description = description;
    if (type !== null) payload.type = type;
    out.push(payload);
  }
  return { ok: true, value: out };
}

export interface WorkflowBuildInput {
  summary: string;
  participants: ParticipantInput[];
  inputs: IoInput[];
  outputs: IoInput[];
}

export function buildWorkflowContent(input: WorkflowBuildInput): BuildResult<Record<string, unknown>> {
  const summary = trimOrNull(input.summary);
  const participants = buildParticipants(input.participants);
  if (!participants.ok) return participants;
  const inputs = buildWorkflowInputs(input.inputs);
  if (!inputs.ok) return inputs;
  const outputs = buildWorkflowOutputs(input.outputs);
  if (!outputs.ok) return outputs;
  const content: Record<string, unknown> = {
    content_schema: contentSchemaFor("workflow"),
    participants: participants.value,
    inputs: inputs.value,
    outputs: outputs.value,
  };
  if (summary !== null) content["summary"] = summary;
  return { ok: true, value: content };
}

/** `<option>` list for the create-form kind selector. */
export function kindOptionsHtml(selected?: LibraryKind): string {
  return LIBRARY_KINDS.map(
    (meta) => `<option value="${esc(meta.kind)}"${meta.kind === selected ? " selected" : ""}>${esc(meta.plural)}</option>`,
  ).join("");
}

export function slugOptionsHtml(): { slug: LibraryKindSlug; plural: string }[] {
  return LIBRARY_KINDS.map((meta) => ({ slug: meta.slug, plural: meta.plural }));
}

/** Reads `[data-row]` editors of one kind into plain records (DOM helper). */
export function readRows(scope: ParentNode, rowKind: string): Record<string, string>[] {
  const rows: Record<string, string>[] = [];
  scope.querySelectorAll<HTMLElement>(`[data-row="${rowKind}"]`).forEach((row) => {
    const record: Record<string, string> = {};
    row.querySelectorAll<HTMLInputElement | HTMLSelectElement>("[data-field]").forEach((field) => {
      const name = field.dataset["field"];
      if (name !== undefined) record[name] = field.value;
    });
    rows.push(record);
  });
  return rows;
}

export function asDependencyInputs(rows: Record<string, string>[]): DependencyInput[] {
  return rows.map((row) => ({
    kind: row["kind"] ?? "",
    stable_key: row["stable_key"] ?? "",
    version: row["version"] ?? "",
    relation: row["relation"] ?? "",
  }));
}

export function asParticipantInputs(rows: Record<string, string>[]): ParticipantInput[] {
  return rows.map((row) => ({
    participant_id: row["participant_id"] ?? "",
    agent_stable_key: row["agent_stable_key"] ?? "",
    depends_on: row["depends_on"] ?? "",
    description: row["description"] ?? "",
  }));
}

export function asIoInputs(rows: Record<string, string>[]): IoInput[] {
  return rows.map((row) => ({
    name: row["name"] ?? "",
    description: row["description"] ?? "",
    type: row["type"] ?? "",
    required: row["required"] ?? "true",
    source_participant: row["source_participant"] ?? "",
    source_name: row["source_name"] ?? "",
  }));
}

/** Reads named fields from a form as a `FormReader` (DOM helper). */
export function formReader(form: HTMLFormElement): FormReader {
  return {
    text(name: string): string {
      const field = form.elements.namedItem(name);
      if (
        field instanceof HTMLInputElement ||
        field instanceof HTMLTextAreaElement ||
        field instanceof HTMLSelectElement
      ) {
        return field.value;
      }
      return "";
    },
    checked(name: string): boolean {
      const field = form.elements.namedItem(name);
      return field instanceof HTMLInputElement ? field.checked : false;
    },
  };
}
