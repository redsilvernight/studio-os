import { describe, expect, it } from "vitest";
import { contractRoadmapDocuments, contractRoadmaps } from "./roadmapFixtures";
import {
  parseRoadmapDocument,
  roadmapToDocument,
  serializeRoadmapDocument,
  validateRoadmapDocument,
} from "./roadmapFormat";
import type { RoadmapDocument } from "./roadmapTypes";

function valid(): RoadmapDocument {
  const fixture = contractRoadmapDocuments[0];
  if (fixture === undefined) throw new Error("fixture missing");
  return structuredClone(fixture);
}

function raw(): Record<string, unknown> {
  return structuredClone(valid()) as unknown as Record<string, unknown>;
}

describe("roadmap document import/export", () => {
  it("round-trips the P1 fixture in a deterministic representation", () => {
    const first = serializeRoadmapDocument(valid());
    expect(first.endsWith("\n")).toBe(true);
    expect(serializeRoadmapDocument(parseRoadmapDocument(first))).toBe(first);
    expect(Object.keys(JSON.parse(first) as object)).toEqual([
      "format",
      "title",
      "objective",
      "context",
      "metadata",
      "phases",
      "exported_at",
      "revision_no",
    ]);
  });

  it("fills P1 defaults while keeping the canonical serialized shape", () => {
    const parsed = parseRoadmapDocument('{"title":"Minimal"}');
    expect(parsed).toEqual({
      format: "studio.roadmap/v1",
      title: "Minimal",
      objective: null,
      context: null,
      metadata: {},
      phases: [],
      exported_at: null,
      revision_no: null,
    });
  });

  it("converts a persisted roadmap to the neutral plan only", () => {
    const fixture = contractRoadmaps[0];
    if (fixture === undefined) throw new Error("fixture missing");
    const json = serializeRoadmapDocument(roadmapToDocument(fixture));
    const document = JSON.parse(json) as Record<string, unknown>;
    expect(document.format).toBe("studio.roadmap/v1");
    for (const forbidden of [
      "project_id",
      "id",
      "status",
      "provenance",
      "linked_tasks",
      "progress",
      "task_progress",
      "state",
      "state_override",
      "criteria_checked",
      "created_at",
      "updated_at",
    ]) {
      expect(json).not.toContain(`"${forbidden}"`);
    }
  });

  it("rejects malformed JSON, unknown fields and a wrong format", () => {
    expect(() => parseRoadmapDocument("{")) .toThrow(/malformed JSON/);
    expect(() => validateRoadmapDocument({ ...raw(), resources: [] })).toThrow(/unknown field/);
    expect(() => validateRoadmapDocument({ ...raw(), format: "studio.roadmap/v2" })).toThrow(/unsupported format/);
  });

  it.each([
    ["title", "", /1-200/],
    ["title", "x".repeat(201), /1-200/],
    ["objective", "x".repeat(2_001), /1-2000/],
    ["context", "x".repeat(4_001), /1-4000/],
  ])("enforces root bound for %s", (field, value, error) => {
    expect(() => validateRoadmapDocument({ ...raw(), [field]: value })).toThrow(error);
  });

  it("enforces phase, step, dependency, criterion and task bounds", () => {
    const base = valid();
    expect(() => validateRoadmapDocument({ ...base, phases: Array.from({ length: 31 }, () => base.phases[0]) })).toThrow(/30 phases/);
    const phase = structuredClone(base.phases[0]);
    if (phase === undefined) throw new Error("fixture missing phase");
    expect(() => validateRoadmapDocument({ ...base, phases: [{ ...phase, steps: Array.from({ length: 51 }, () => phase.steps[0]) }] })).toThrow(/50 steps/);
    const step = structuredClone(phase.steps[0]);
    if (step === undefined) throw new Error("fixture missing step");
    expect(() => validateRoadmapDocument({ ...base, phases: [{ ...phase, steps: [{ ...step, acceptance_criteria: Array.from({ length: 21 }, () => "ok") }] }] })).toThrow(/20 items/);
    expect(() => validateRoadmapDocument({ ...base, phases: [{ ...phase, steps: [{ ...step, depends_on: Array.from({ length: 21 }, (_, index) => `D${index}`) }] }] })).toThrow(/20 items/);
    expect(() => validateRoadmapDocument({ ...base, phases: [{ ...phase, steps: [{ ...step, tasks: Array.from({ length: 21 }, (_, index) => ({ hydration_key: `t${index}`, title: "Task", description: null })) }] }] })).toThrow(/20 tasks/);
  });

  it("rejects duplicate keys, unknown/self dependencies and cycles", () => {
    const document = valid();
    const phase = document.phases[0];
    if (phase === undefined) throw new Error("fixture missing phase");
    expect(() => validateRoadmapDocument({ ...document, phases: [phase, structuredClone(phase)] })).toThrow(/duplicate phase key/);
    expect(() => validateRoadmapDocument({ ...document, phases: [{ ...phase, steps: [phase.steps[0], phase.steps[0]] }] })).toThrow(/duplicate step key/);
    const step = structuredClone(phase.steps[0]);
    if (step === undefined) throw new Error("fixture missing step");
    expect(() => validateRoadmapDocument({ ...document, phases: [{ ...phase, steps: [{ ...step, depends_on: ["missing"] }] }] })).toThrow(/unknown dependency/);
    expect(() => validateRoadmapDocument({ ...document, phases: [{ ...phase, steps: [{ ...step, depends_on: [step.key] }] }] })).toThrow(/self dependency/);
    const a = { ...step, key: "a", depends_on: ["b"], tasks: [] };
    const b = { ...step, key: "b", depends_on: ["a"], tasks: [] };
    expect(() => validateRoadmapDocument({ ...document, phases: [{ ...phase, steps: [a, b] }] })).toThrow(/dependency cycle/);
  });

  it("rejects duplicate hydration keys and unsafe metadata", () => {
    const document = valid();
    const step = document.phases[0]?.steps[0];
    if (step === undefined) throw new Error("fixture missing step");
    const task = { hydration_key: "same", title: "Task", description: null };
    expect(() => validateRoadmapDocument({ ...document, phases: [{ ...document.phases[0]!, steps: [{ ...step, tasks: [task, task] }] }] })).toThrow(/duplicate hydration_key/);
    expect(() => validateRoadmapDocument({ ...document, metadata: { api_key: "never" } })).toThrow(/secret-looking/);
    expect(() => validateRoadmapDocument({ ...document, metadata: { source: "C:\\Users\\alice\\private.json" } })).toThrow(/unsafe metadata/);
    expect(() => validateRoadmapDocument({ ...document, metadata: { nested: { no: true } } })).toThrow(/scalar/);
  });

  it("accepts scalar metadata and valid informational stamps", () => {
    const parsed = validateRoadmapDocument({
      ...raw(),
      metadata: { source: "portable", count: 2, enabled: true, optional: null },
      exported_at: "2026-09-20T10:00:00Z",
      revision_no: 3,
    });
    expect(parsed.metadata).toEqual({ source: "portable", count: 2, enabled: true, optional: null });
  });
});
