/**
 * P12 — Configuration authoring forms (pure builders, no server logic).
 *
 * Open references stay open: harness/provider/model refs are free strings and
 * the UI never proposes a closed vendor catalog (DEC-0070). The server remains
 * the only validator; every 4xx it returns is surfaced verbatim.
 */
import type { components } from "../openapi-schema";
import type { RuntimeCapabilities, RuntimeLevel, LibraryKind } from "../libraryFormat";
import { STORED_RUNTIME_LEVELS } from "../bindingsApi";
import type { BuildResult, FormReader } from "./libraryForms";

export type RuntimeRegistrationCreate = components["schemas"]["RuntimeRegistrationCreate"];
export type RuntimeRegistrationUpdate = components["schemas"]["RuntimeRegistrationUpdate"];
export type RuntimeRegistrationUpdateRequest = components["schemas"]["RuntimeRegistrationUpdateRequest"];
export type RuntimeBindingCreate = components["schemas"]["RuntimeBindingCreate"];
export type RuntimeTarget = components["schemas"]["RuntimeTarget"];

function trimOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/** Capability inputs read back by `readCapabilities` (`cap_*` names). */
export function capabilityFieldsHtml(disabled = false): string {
  const attr = disabled ? "disabled" : "";
  return (
    `<label class="stack">Reasoning <input name="cap_reasoning" placeholder="étiquette libre (optionnel)" ${attr} /></label>` +
    `<label class="stack">Context window <input name="cap_context_window" type="number" min="1" placeholder="optionnel" ${attr} /></label>` +
    `<label class="stack">Tools <input name="cap_tools" placeholder="séparés par des virgules (optionnel)" ${attr} /></label>` +
    `<label class="stack">Multimodal <input name="cap_multimodal" placeholder="étiquette libre (optionnel)" ${attr} /></label>` +
    `<label class="stack">Cost <input name="cap_cost" placeholder="étiquette libre (optionnel)" ${attr} /></label>` +
    `<label class="stack">Latency <input name="cap_latency" placeholder="étiquette libre (optionnel)" ${attr} /></label>` +
    `<label class="check">Coding <input name="cap_coding" type="checkbox" ${attr} /></label>` +
    `<label class="check">Local <input name="cap_local" type="checkbox" ${attr} /></label>`
  );
}

/** `key=value` lines → non-secret metadata object (empty when blank). */
export function parseMetadataLines(text: string): Record<string, string> {
  const metadata: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (trimmed === "") continue;
    const index = trimmed.indexOf("=");
    if (index <= 0) continue;
    const key = trimmed.slice(0, index).trim();
    const value = trimmed.slice(index + 1).trim();
    if (key !== "") metadata[key] = value;
  }
  return metadata;
}

export function readCapabilities(read: FormReader): RuntimeCapabilities {
  const tools = read
    .text("cap_tools")
    .split(",")
    .map((tool) => tool.trim())
    .filter((tool) => tool !== "");
  const capabilities: RuntimeCapabilities = {
    coding: read.checked("cap_coding"),
    tools,
    local: read.checked("cap_local"),
  };
  const reasoning = trimOrNull(read.text("cap_reasoning"));
  const multimodal = trimOrNull(read.text("cap_multimodal"));
  const cost = trimOrNull(read.text("cap_cost"));
  const latency = trimOrNull(read.text("cap_latency"));
  const contextWindowRaw = read.text("cap_context_window").trim();
  const contextWindow = contextWindowRaw === "" ? null : Number(contextWindowRaw);
  if (reasoning !== null) capabilities.reasoning = reasoning;
  if (multimodal !== null) capabilities.multimodal = multimodal;
  if (cost !== null) capabilities.cost = cost;
  if (latency !== null) capabilities.latency = latency;
  if (contextWindow !== null && Number.isFinite(contextWindow)) capabilities.context_window = contextWindow;
  return capabilities;
}

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

export function buildRuntimeCreate(read: FormReader): BuildResult<RuntimeRegistrationCreate> {
  const machineId = trimOrNull(read.text("machine_id"));
  const harness = trimOrNull(read.text("harness_ref"));
  const provider = trimOrNull(read.text("provider_ref"));
  const model = trimOrNull(read.text("model_ref"));
  if (machineId === null && harness === null && provider === null && model === null) {
    return { ok: false, error: "au moins un ancrage est requis : machine, harness, provider ou model" };
  }
  const value: RuntimeRegistrationCreate = {
    machine_id: machineId,
    harness_ref: harness,
    provider_ref: provider,
    model_ref: model,
    capabilities: readCapabilities(read),
    capability_source: "declared",
    runtime_metadata: parseMetadataLines(read.text("metadata")),
  };
  return { ok: true, value };
}

export function buildRuntimeUpdate(read: FormReader): BuildResult<RuntimeRegistrationUpdateRequest> {
  const update: RuntimeRegistrationUpdate = { detach_machine: false };
  const machineId = trimOrNull(read.text("machine_id"));
  const harness = trimOrNull(read.text("harness_ref"));
  const provider = trimOrNull(read.text("provider_ref"));
  const model = trimOrNull(read.text("model_ref"));
  if (machineId !== null) update.machine_id = machineId;
  if (harness !== null) update.harness_ref = harness;
  if (provider !== null) update.provider_ref = provider;
  if (model !== null) update.model_ref = model;
  if (read.checked("detach_machine")) update.detach_machine = true;
  if (read.checked("update_capabilities")) update.capabilities = readCapabilities(read);
  const metadata = read.text("metadata").trim();
  if (metadata !== "") update.runtime_metadata = parseMetadataLines(metadata);
  const expected = Number(read.text("expected_version"));
  if (!Number.isInteger(expected) || expected < 1) return { ok: false, error: "la version attendue (expected_version) doit être ≥ 1" };
  return { ok: true, value: { update, expected_version: expected } };
}

export function buildBindingCreate(read: FormReader): BuildResult<RuntimeBindingCreate> {
  const level = read.text("level");
  if (!(STORED_RUNTIME_LEVELS as readonly string[]).includes(level)) {
    return { ok: false, error: "le niveau doit être user, project_override, project_default ou studio_default" };
  }
  const projectId = trimOrNull(read.text("project_id"));
  if ((level === "project_override" || level === "project_default") && projectId === null) {
    return { ok: false, error: `${level} exige un ID de projet` };
  }
  const targetKind = read.text("target_kind");
  if (targetKind !== "agent_definition" && targetKind !== "model_profile") {
    return { ok: false, error: "le type de cible doit être agent_definition ou model_profile" };
  }
  const stableKey = read.text("target_stable_key").trim();
  if (stableKey === "") return { ok: false, error: "la clé stable cible est requise" };

  const runtimeId = trimOrNull(read.text("runtime_id"));
  let target: RuntimeTarget;
  if (runtimeId !== null) {
    target = { runtime_id: runtimeId, capabilities: readCapabilities(read) };
  } else {
    const machineId = trimOrNull(read.text("machine_id"));
    const harness = trimOrNull(read.text("harness_ref"));
    const provider = trimOrNull(read.text("provider_ref"));
    const model = trimOrNull(read.text("model_ref"));
    if (machineId === null && harness === null && provider === null && model === null) {
      return {
        ok: false,
        error: "fournissez un ID de registre runtime, ou au moins un ancrage direct (machine/harness/provider/model)",
      };
    }
    target = {
      machine_id: machineId,
      harness_ref: harness,
      provider_ref: provider,
      model_ref: model,
      capabilities: readCapabilities(read),
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
