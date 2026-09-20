/**
 * P12 — Library/Configuration presentation vocabulary (pure, DOM-free).
 *
 * Human labels and read-only projections of the canonical P7 payloads. This
 * module never decides anything: no shadowing rank, no runtime precedence
 * winner, no compatibility verdict. `bindingLevelLabel` documents the P4 level
 * vocabulary as labels only — it is deliberately never used to compare or sort
 * levels, which stays the server resolution engine's job (DEC-0068/0069).
 */
import type { components } from "./openapi-schema";

export type LibraryKind = components["schemas"]["LibraryKind"];
export type LibraryScope = components["schemas"]["LibraryScope"];
export type LibraryStatus = components["schemas"]["LibraryStatus"];
export type RuntimeLevel = components["schemas"]["RuntimeLevel"];
export type VersionOrigin = components["schemas"]["VersionOrigin"];
export type ProvenanceSource = components["schemas"]["ProvenanceSource"];
export type BindingRelation = components["schemas"]["BindingRelation"];
export type CapabilityRequirement = components["schemas"]["CapabilityRequirement"];
export type RuntimeCapabilities = components["schemas"]["RuntimeCapabilities"];
export type RuntimeTarget = components["schemas"]["RuntimeTarget"];
export type Provenance = components["schemas"]["studio_contracts__resolution__Provenance"];
export type DependencyPin = components["schemas"]["DependencyPin"];

export type LibraryKindSlug =
  | "rules"
  | "skills"
  | "agent-definitions"
  | "workflows"
  | "model-profiles";

export interface LibraryKindMeta {
  kind: LibraryKind;
  slug: LibraryKindSlug;
  singular: string;
  plural: string;
}

export const LIBRARY_KINDS: readonly LibraryKindMeta[] = [
  { kind: "rule", slug: "rules", singular: "Rule", plural: "Rules" },
  { kind: "skill", slug: "skills", singular: "Skill", plural: "Skills" },
  { kind: "agent_definition", slug: "agent-definitions", singular: "Agent Definition", plural: "Agent Definitions" },
  { kind: "workflow", slug: "workflows", singular: "Workflow", plural: "Workflows" },
  { kind: "model_profile", slug: "model-profiles", singular: "Model Profile", plural: "Model Profiles" },
];

export const LIBRARY_SLUGS: readonly LibraryKindSlug[] = LIBRARY_KINDS.map((meta) => meta.slug);

export function kindFromSlug(slug: string): LibraryKindMeta | null {
  return LIBRARY_KINDS.find((meta) => meta.slug === slug) ?? null;
}

export function isLibraryKindSlug(value: string): value is LibraryKindSlug {
  return LIBRARY_KINDS.some((meta) => meta.slug === value);
}

export function kindMeta(kind: LibraryKind): LibraryKindMeta {
  const found = LIBRARY_KINDS.find((meta) => meta.kind === kind);
  if (found !== undefined) return found;
  return { kind, slug: "rules", singular: String(kind), plural: String(kind) };
}

export function libraryKindHref(kind: LibraryKind, resourceId?: string): string {
  const base = `#/library/${kindMeta(kind).slug}`;
  return resourceId === undefined ? base : `${base}/${resourceId}`;
}

const SCOPE_LABELS: Record<LibraryScope, string> = {
  studio: "Studio",
  project: "Projet",
  user: "Utilisateur",
};

export function scopeLabel(scope: LibraryScope): string {
  return SCOPE_LABELS[scope] ?? String(scope);
}

export function statusTone(status: LibraryStatus): "ok" | "warn" | "bad" {
  if (status === "active") return "ok";
  if (status === "deprecated") return "bad";
  return "warn";
}

const LEVEL_LABELS: Record<RuntimeLevel, string> = {
  session: "session (ephemeral)",
  project_override: "project override",
  user: "user",
  project_default: "project default",
  studio_default: "studio default",
};

/** Label for a stored/effective level. Never a ranking: see module header. */
export function bindingLevelLabel(level: RuntimeLevel): string {
  return LEVEL_LABELS[level] ?? String(level);
}

const ORIGIN_LABELS: Record<VersionOrigin, string> = {
  lock: "project lock",
  active: "active pointer",
  pin: "version pin",
};

export function versionOriginLabel(origin: VersionOrigin): string {
  return ORIGIN_LABELS[origin] ?? String(origin);
}

const SOURCE_LABELS: Record<ProvenanceSource, string> = {
  active_pointer: "active pointer",
  project_lock: "project lock",
  version_pin: "version pin",
  runtime_binding: "runtime binding",
  session_override: "temporary session override",
};

export function provenanceSourceLabel(source: ProvenanceSource): string {
  return SOURCE_LABELS[source] ?? String(source);
}

const RELATION_LABELS: Record<BindingRelation, string> = {
  requires_model_profile: "requires model profile",
  uses_skill: "uses skill",
  applies_rule: "applies rule",
  composes_agent: "composes agent",
  references_workflow: "references workflow",
  refines_skill_rule: "refines skill rule",
};

export function relationLabel(relation: BindingRelation): string {
  return RELATION_LABELS[relation] ?? String(relation);
}

export interface Entry {
  key: string;
  label: string;
  value: string;
}

function formatValue(value: string | number): string {
  return String(value);
}

/** Readable projection of a ModelProfile requirement (only meaningful fields). */
export function requirementEntries(requirement: CapabilityRequirement | null | undefined): Entry[] {
  if (requirement === null || requirement === undefined) return [];
  const entries: Entry[] = [];
  if (requirement.reasoning !== null && requirement.reasoning !== undefined)
    entries.push({ key: "reasoning", label: "Reasoning", value: requirement.reasoning });
  if (requirement.coding) entries.push({ key: "coding", label: "Coding", value: "required" });
  if (requirement.context_window_min !== null && requirement.context_window_min !== undefined)
    entries.push({ key: "context_window_min", label: "Context window ≥", value: formatValue(requirement.context_window_min) });
  for (const tool of requirement.tools_required ?? [])
    entries.push({ key: `tool:${tool}`, label: "Tool required", value: tool });
  if (requirement.multimodal !== null && requirement.multimodal !== undefined)
    entries.push({ key: "multimodal", label: "Multimodal", value: requirement.multimodal });
  if (requirement.local_compatible) entries.push({ key: "local_compatible", label: "Local", value: "required" });
  if (requirement.cost !== null && requirement.cost !== undefined)
    entries.push({ key: "cost", label: "Cost", value: requirement.cost });
  if (requirement.latency !== null && requirement.latency !== undefined)
    entries.push({ key: "latency", label: "Latency", value: requirement.latency });
  return entries;
}

/** Readable projection of what a runtime declares. */
export function capabilityEntries(capabilities: RuntimeCapabilities | null | undefined): Entry[] {
  if (capabilities === null || capabilities === undefined) return [];
  const entries: Entry[] = [];
  if (capabilities.reasoning !== null && capabilities.reasoning !== undefined)
    entries.push({ key: "reasoning", label: "Reasoning", value: capabilities.reasoning });
  if (capabilities.coding) entries.push({ key: "coding", label: "Coding", value: "yes" });
  if (capabilities.context_window !== null && capabilities.context_window !== undefined)
    entries.push({ key: "context_window", label: "Context window", value: formatValue(capabilities.context_window) });
  for (const tool of capabilities.tools ?? []) entries.push({ key: `tool:${tool}`, label: "Tool", value: tool });
  if (capabilities.multimodal !== null && capabilities.multimodal !== undefined)
    entries.push({ key: "multimodal", label: "Multimodal", value: capabilities.multimodal });
  if (capabilities.local) entries.push({ key: "local", label: "Local", value: "yes" });
  if (capabilities.cost !== null && capabilities.cost !== undefined)
    entries.push({ key: "cost", label: "Cost", value: capabilities.cost });
  if (capabilities.latency !== null && capabilities.latency !== undefined)
    entries.push({ key: "latency", label: "Latency", value: capabilities.latency });
  return entries;
}

export function dependencyLabel(pin: DependencyPin): string {
  return `${kindMeta(pin.kind).singular} ${pin.stable_key} v${pin.version}`;
}

/** Readable anchors of a runtime choice (registry reference or inline refs). */
export function runtimeTargetEntries(target: RuntimeTarget): Entry[] {
  const entries: Entry[] = [];
  if (target.runtime_id !== null && target.runtime_id !== undefined)
    entries.push({ key: "runtime_id", label: "Runtime registry", value: target.runtime_id });
  if (target.harness_ref !== null && target.harness_ref !== undefined)
    entries.push({ key: "harness_ref", label: "Harness", value: target.harness_ref });
  if (target.provider_ref !== null && target.provider_ref !== undefined)
    entries.push({ key: "provider_ref", label: "Provider", value: target.provider_ref });
  if (target.model_ref !== null && target.model_ref !== undefined)
    entries.push({ key: "model_ref", label: "Model", value: target.model_ref });
  if (target.machine_id !== null && target.machine_id !== undefined)
    entries.push({ key: "machine_id", label: "Machine", value: target.machine_id });
  return entries;
}

/** Human reason for a canonical `Provenance` — read, never recomputed. */
export function provenanceReason(provenance: Provenance): string {
  const parts: string[] = [];
  if (provenance.source === "runtime_binding" || provenance.source === "session_override") {
    if (provenance.binding_level !== null && provenance.binding_level !== undefined)
      parts.push(bindingLevelLabel(provenance.binding_level));
    if (provenance.via !== null && provenance.via !== undefined) parts.push(`via ${provenance.via}`);
    return parts.length > 0 ? parts.join(" · ") : provenanceSourceLabel(provenance.source);
  }
  parts.push(provenanceSourceLabel(provenance.source));
  if (provenance.version !== null && provenance.version !== undefined) parts.push(`v${provenance.version}`);
  if (provenance.scope !== null && provenance.scope !== undefined) parts.push(scopeLabel(provenance.scope));
  if (provenance.relation !== null && provenance.relation !== undefined)
    parts.push(`relation ${relationLabel(provenance.relation)}`);
  if (provenance.via !== null && provenance.via !== undefined) parts.push(`via ${provenance.via}`);
  return parts.join(" · ");
}

export function contentSchema(content: Record<string, unknown> | null | undefined): string | null {
  if (content === null || content === undefined) return null;
  const value = content["content_schema"];
  return typeof value === "string" ? value : null;
}

export function contentText(content: Record<string, unknown> | null | undefined): string | null {
  if (content === null || content === undefined) return null;
  const value = content["text"];
  return typeof value === "string" ? value : null;
}

export interface WorkflowIOSource {
  participantId: string | null;
  name: string;
}

export interface WorkflowIODeclaration {
  name: string;
  description: string | null;
  required: boolean;
  type: string | null;
  source: WorkflowIOSource | null;
}

export interface WorkflowParticipant {
  participantId: string;
  description: string | null;
  agentStableKey: string;
  dependsOn: string[];
  inputs: WorkflowIODeclaration[];
  outputs: WorkflowIODeclaration[];
}

export interface WorkflowView {
  summary: string | null;
  participants: WorkflowParticipant[];
  inputs: WorkflowIODeclaration[];
  outputs: WorkflowIODeclaration[];
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function parseSource(value: unknown): WorkflowIOSource | null {
  if (value === null || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const name = asString(record["name"]);
  if (name === null) return null;
  return { participantId: asString(record["participant_id"]), name };
}

function parseIo(value: unknown): WorkflowIODeclaration[] {
  if (!Array.isArray(value)) return [];
  const out: WorkflowIODeclaration[] = [];
  for (const item of value) {
    if (item === null || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const name = asString(record["name"]);
    if (name === null) continue;
    out.push({
      name,
      description: asString(record["description"]),
      required: record["required"] !== false,
      type: asString(record["type"]),
      source: parseSource(record["source"]),
    });
  }
  return out;
}

/**
 * Read-only view of a stored `workflow` version content. Returns `null` when
 * the payload is not the canonical `studio.library.workflow/v1` shape; the view
 * then falls back to a raw-but-safe rendering. No validation is performed here.
 */
export function parseWorkflowContent(content: Record<string, unknown> | null | undefined): WorkflowView | null {
  if (content === null || content === undefined) return null;
  if (contentSchema(content) !== "studio.library.workflow/v1") return null;
  const rawParticipants = content["participants"];
  if (!Array.isArray(rawParticipants)) return null;
  const participants: WorkflowParticipant[] = [];
  for (const item of rawParticipants) {
    if (item === null || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const participantId = asString(record["participant_id"]);
    const agentStableKey = asString(record["agent_stable_key"]);
    if (participantId === null || agentStableKey === null) continue;
    const dependsOn = Array.isArray(record["depends_on"])
      ? record["depends_on"].filter((dep): dep is string => typeof dep === "string")
      : [];
    participants.push({
      participantId,
      description: asString(record["description"]),
      agentStableKey,
      dependsOn,
      inputs: parseIo(record["inputs"]),
      outputs: parseIo(record["outputs"]),
    });
  }
  return {
    summary: asString(content["summary"]),
    participants,
    inputs: parseIo(content["inputs"]),
    outputs: parseIo(content["outputs"]),
  };
}

export interface WorkflowEdge {
  from: string;
  to: string;
}

/** Direct projection of `depends_on` declarations — `from` must precede `to`. */
export function workflowEdges(view: WorkflowView): WorkflowEdge[] {
  const edges: WorkflowEdge[] = [];
  for (const participant of view.participants) {
    for (const dependency of participant.dependsOn) {
      edges.push({ from: dependency, to: participant.participantId });
    }
  }
  return edges;
}

export function ioSourceLabel(source: WorkflowIOSource | null): string {
  if (source === null) return "harness / external";
  return source.participantId === null ? `workflow input ${source.name}` : `${source.participantId}.${source.name}`;
}
