import type {
  Roadmap,
  RoadmapDocument,
  RoadmapDocumentPhase,
  RoadmapDocumentStep,
  RoadmapDocumentTask,
  RoadmapMetadata,
} from "./roadmapTypes";

const KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const SECRET_KEY_PATTERN = /(password|secret|token|credential|api[-_]?key|private[-_]?key|authorization|path|local[-_]?path)/i;
const PRIVATE_PATH_PATTERN = /(?:file:\/\/|(?:^|[\s"'])(?:[A-Za-z]:[\\/]|\/(?:home|Users|etc|var|tmp)\/))/i;
const ROOT_FIELDS = ["format", "title", "objective", "context", "metadata", "phases", "exported_at", "revision_no"] as const;
const PHASE_FIELDS = ["key", "title", "objective", "steps"] as const;
const STEP_FIELDS = ["key", "title", "objective", "context", "instructions", "acceptance_criteria", "notes", "metadata", "depends_on", "tasks"] as const;
const TASK_FIELDS = ["hydration_key", "title", "description"] as const;

function fail(path: string, message: string): never {
  throw new Error(`Invalid roadmap document at ${path}: ${message}`);
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail(path, "expected an object");
  return value as Record<string, unknown>;
}

function exact(
  value: Record<string, unknown>,
  allowed: readonly string[],
  required: readonly string[],
  path: string,
): void {
  for (const key of Object.keys(value)) if (!allowed.includes(key)) fail(`${path}.${key}`, "unknown field");
  for (const key of required) if (!(key in value)) fail(`${path}.${key}`, "missing field");
}

function text(value: unknown, path: string, max: number, nullable = false): string | null {
  if (nullable && value === null) return null;
  if (typeof value !== "string" || value.length === 0 || value.length > max) fail(path, `expected 1-${max} characters`);
  if (PRIVATE_PATH_PATTERN.test(value)) fail(path, "private filesystem paths are forbidden");
  return value;
}

function key(value: unknown, path: string): string {
  if (typeof value !== "string" || !KEY_PATTERN.test(value)) fail(path, "invalid key");
  return value;
}

function metadata(value: unknown, path: string): RoadmapMetadata {
  const source = record(value, path);
  if (Object.keys(source).length > 20) fail(path, "metadata allows at most 20 keys");
  const result: RoadmapMetadata = {};
  for (const [name, item] of Object.entries(source)) {
    if (name.length < 1 || name.length > 64) fail(`${path}.${name}`, "metadata keys must be 1-64 characters");
    if (SECRET_KEY_PATTERN.test(name)) fail(`${path}.${name}`, "secret-looking metadata key");
    if (item !== null && !["string", "number", "boolean"].includes(typeof item)) fail(`${path}.${name}`, "metadata values must be scalar");
    if (typeof item === "number" && !Number.isFinite(item)) fail(`${path}.${name}`, "metadata number must be finite");
    if (typeof item === "string" && (item.length > 500 || PRIVATE_PATH_PATTERN.test(item))) fail(`${path}.${name}`, "unsafe metadata value");
    Object.defineProperty(result, name, {
      configurable: true,
      enumerable: true,
      value: item as string | number | boolean | null,
      writable: true,
    });
  }
  return result;
}

function stringList(value: unknown, path: string, maxItems: number, itemMax: number): string[] {
  if (!Array.isArray(value) || value.length > maxItems) fail(path, `expected at most ${maxItems} items`);
  return value.map((item, index) => text(item, `${path}[${index}]`, itemMax) as string);
}

function parseTask(value: unknown, path: string): RoadmapDocumentTask {
  const source = record(value, path);
  exact(source, TASK_FIELDS, ["hydration_key", "title"], path);
  return {
    hydration_key: key(source.hydration_key, `${path}.hydration_key`),
    title: text(source.title, `${path}.title`, 200) as string,
    description: text(source.description ?? null, `${path}.description`, 4_000, true),
  };
}

function parseStep(value: unknown, path: string): RoadmapDocumentStep {
  const source = record(value, path);
  exact(source, STEP_FIELDS, ["key", "title"], path);
  const taskValues = source.tasks ?? [];
  if (!Array.isArray(taskValues) || taskValues.length > 20) fail(`${path}.tasks`, "expected at most 20 tasks");
  const tasks = taskValues.map((item, index) => parseTask(item, `${path}.tasks[${index}]`));
  const hydrationKeys = new Set<string>();
  for (const task of tasks) {
    if (hydrationKeys.has(task.hydration_key)) fail(`${path}.tasks`, `duplicate hydration_key ${task.hydration_key}`);
    hydrationKeys.add(task.hydration_key);
  }
  return {
    key: key(source.key, `${path}.key`),
    title: text(source.title, `${path}.title`, 200) as string,
    objective: text(source.objective ?? null, `${path}.objective`, 2_000, true),
    context: text(source.context ?? null, `${path}.context`, 4_000, true),
    instructions: text(source.instructions ?? null, `${path}.instructions`, 8_000, true),
    acceptance_criteria: stringList(source.acceptance_criteria ?? [], `${path}.acceptance_criteria`, 20, 500),
    notes: text(source.notes ?? null, `${path}.notes`, 4_000, true),
    metadata: metadata(source.metadata ?? {}, `${path}.metadata`),
    depends_on: stringList(source.depends_on ?? [], `${path}.depends_on`, 20, 64).map((item, index) => key(item, `${path}.depends_on[${index}]`)),
    tasks,
  };
}

function parsePhase(value: unknown, path: string): RoadmapDocumentPhase {
  const source = record(value, path);
  exact(source, PHASE_FIELDS, ["key", "title"], path);
  const stepValues = source.steps ?? [];
  if (!Array.isArray(stepValues) || stepValues.length > 50) fail(`${path}.steps`, "expected at most 50 steps");
  return {
    key: key(source.key, `${path}.key`),
    title: text(source.title, `${path}.title`, 200) as string,
    objective: text(source.objective ?? null, `${path}.objective`, 2_000, true),
    steps: stepValues.map((item, index) => parseStep(item, `${path}.steps[${index}]`)),
  };
}

function validateGraph(document: RoadmapDocument): void {
  const phaseKeys = new Set<string>();
  const steps = document.phases.flatMap((phase) => phase.steps);
  if (steps.length > 300) fail("$.phases", "expected at most 300 steps total");
  let taskCount = 0;
  for (const phase of document.phases) {
    if (phaseKeys.has(phase.key)) fail("$.phases", `duplicate phase key ${phase.key}`);
    phaseKeys.add(phase.key);
    taskCount += phase.steps.reduce((sum, step) => sum + step.tasks.length, 0);
  }
  if (taskCount > 500) fail("$.phases", "expected at most 500 tasks total");
  const byKey = new Map<string, RoadmapDocumentStep>();
  for (const step of steps) {
    if (byKey.has(step.key)) fail("$.phases", `duplicate step key ${step.key}`);
    byKey.set(step.key, step);
  }
  for (const step of steps) {
    const dependencies = new Set<string>();
    for (const dependency of step.depends_on) {
      if (!byKey.has(dependency)) fail(`$.steps.${step.key}.depends_on`, `unknown dependency ${dependency}`);
      if (dependency === step.key) fail(`$.steps.${step.key}.depends_on`, "self dependency");
      if (dependencies.has(dependency)) fail(`$.steps.${step.key}.depends_on`, `duplicate dependency ${dependency}`);
      dependencies.add(dependency);
    }
  }
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (stepKey: string): void => {
    if (visiting.has(stepKey)) fail("$.phases", "dependency cycle");
    if (visited.has(stepKey)) return;
    visiting.add(stepKey);
    for (const dependency of byKey.get(stepKey)?.depends_on ?? []) visit(dependency);
    visiting.delete(stepKey);
    visited.add(stepKey);
  };
  for (const stepKey of byKey.keys()) visit(stepKey);
}

export function validateRoadmapDocument(value: unknown): RoadmapDocument {
  const source = record(value, "$");
  exact(source, ROOT_FIELDS, ["title"], "$");
  if ((source.format ?? "studio.roadmap/v1") !== "studio.roadmap/v1") fail("$.format", "unsupported format");
  const phaseValues = source.phases ?? [];
  if (!Array.isArray(phaseValues) || phaseValues.length > 30) fail("$.phases", "expected at most 30 phases");
  let exportedAt: string | null = null;
  if (source.exported_at !== null && source.exported_at !== undefined) {
    if (typeof source.exported_at !== "string" || !Number.isFinite(Date.parse(source.exported_at))) fail("$.exported_at", "expected an ISO timestamp or null");
    exportedAt = source.exported_at;
  }
  if (source.revision_no !== null && source.revision_no !== undefined && !Number.isInteger(source.revision_no)) fail("$.revision_no", "expected an integer or null");
  const document: RoadmapDocument = {
    format: "studio.roadmap/v1",
    title: text(source.title, "$.title", 200) as string,
    objective: text(source.objective ?? null, "$.objective", 2_000, true),
    context: text(source.context ?? null, "$.context", 4_000, true),
    metadata: metadata(source.metadata ?? {}, "$.metadata"),
    phases: phaseValues.map((item, index) => parsePhase(item, `$.phases[${index}]`)),
    exported_at: exportedAt,
    revision_no: (source.revision_no ?? null) as number | null,
  };
  validateGraph(document);
  return document;
}

export function parseRoadmapDocument(textValue: string): RoadmapDocument {
  let value: unknown;
  try {
    value = JSON.parse(textValue);
  } catch {
    throw new Error("Invalid roadmap document: malformed JSON");
  }
  return validateRoadmapDocument(value);
}

export function serializeRoadmapDocument(document: RoadmapDocument): string {
  return `${JSON.stringify(validateRoadmapDocument(document), null, 2)}\n`;
}

export function roadmapToDocument(roadmap: Roadmap): RoadmapDocument {
  const document: RoadmapDocument = {
    format: "studio.roadmap/v1",
    title: roadmap.title,
    objective: roadmap.objective,
    context: roadmap.context,
    metadata: { ...roadmap.metadata },
    phases: (roadmap.phases ?? []).map((phase) => ({
      key: phase.key,
      title: phase.title,
      objective: phase.objective,
      steps: (phase.steps ?? []).map((step) => ({
        key: step.key,
        title: step.title,
        objective: step.objective,
        context: step.context,
        instructions: step.instructions,
        acceptance_criteria: [...step.acceptance_criteria],
        notes: step.notes,
        metadata: { ...step.metadata },
        depends_on: [...step.depends_on],
        tasks: step.tasks.map((task) => ({
          hydration_key: task.hydration_key,
          title: task.title,
          description: task.description,
        })),
      })),
    })),
    exported_at: null,
    revision_no: roadmap.revision_no,
  };
  return validateRoadmapDocument(document);
}
