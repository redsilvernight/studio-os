import roadmapDocumentsJson from "../../contracts/fixtures/roadmap_documents.json";
import roadmapsJson from "../../contracts/fixtures/roadmaps.json";
import { validateRoadmapDocument } from "./roadmapFormat";
import type { Roadmap, RoadmapDocument, RoadmapPhase, RoadmapStep, RoadmapStatus } from "./roadmapTypes";

function clone<T>(value: T): T {
  return structuredClone(value);
}

export const contractRoadmapDocuments: readonly RoadmapDocument[] = Object.freeze(
  (roadmapDocumentsJson as unknown[]).map((document) => validateRoadmapDocument(document)),
);

export const contractRoadmaps: readonly Roadmap[] = roadmapsJson as unknown as Roadmap[];

export const roadmapFixtureProjectIds = Object.freeze({
  noRoadmap: "fixture-no-roadmap",
  empty: "fixture-empty-roadmap",
  draft: "fixture-draft-roadmap",
  proposed: "fixture-proposed-roadmap",
  active: "fixture-active-roadmap",
  completed: "fixture-completed-roadmap",
  large: "fixture-large-roadmap",
  blocked: "fixture-blocked-roadmap",
  partial: "fixture-partial-roadmap",
});

function hydratedStep(step: RoadmapDocument["phases"][number]["steps"][number], position: number): RoadmapStep {
  return {
    ...clone(step),
    position,
    state: "not_started",
    available: position === 0,
    waiting_on: [...step.depends_on],
    linked_tasks: [],
    criteria_checked: [],
    task_progress: { completed: 0, total: step.tasks.length },
  };
}

function hydratedPhases(document: RoadmapDocument): RoadmapPhase[] {
  return document.phases.map((phase, position) => ({
    ...clone(phase),
    position,
    progress: { done: 0, total: phase.steps.length, skipped: 0, ratio: 0 },
    steps: phase.steps.map(hydratedStep),
  }));
}

function fromDocument(projectId: string, document: RoadmapDocument, status: RoadmapStatus): Roadmap {
  const phases = hydratedPhases(document);
  const total = phases.reduce((count, phase) => count + (phase.steps?.length ?? 0), 0);
  return {
    id: `roadmap-${projectId}`,
    project_id: projectId,
    title: document.title,
    objective: document.objective,
    status,
    revision_no: document.revision_no ?? 1,
    approved_revision_no: status === "active" || status === "completed" ? document.revision_no ?? 1 : null,
    context: document.context,
    metadata: clone(document.metadata),
    progress: { done: status === "completed" ? total : 0, total, skipped: 0, ratio: status === "completed" && total > 0 ? 1 : 0 },
    current_step_key: status === "active" ? phases[0]?.steps?.[0]?.key ?? null : null,
    phases,
  };
}

function largeDocument(): RoadmapDocument {
  const phases = Array.from({ length: 30 }, (_, phaseIndex) => ({
    key: `L${phaseIndex + 1}`,
    title: `Large phase ${phaseIndex + 1}`,
    objective: null,
    steps: Array.from({ length: 10 }, (_, stepIndex) => ({
      key: `L${phaseIndex + 1}.${stepIndex + 1}`,
      title: `Large step ${phaseIndex + 1}.${stepIndex + 1}`,
      objective: null,
      context: null,
      instructions: null,
      acceptance_criteria: [],
      notes: null,
      metadata: {},
      depends_on: stepIndex === 0 ? [] : [`L${phaseIndex + 1}.${stepIndex}`],
      tasks: [],
    })),
  }));
  return validateRoadmapDocument({
    format: "studio.roadmap/v1",
    title: "Grande roadmap",
    objective: null,
    context: null,
    metadata: { fixture: "large" },
    phases,
    exported_at: null,
    revision_no: 1,
  });
}

export function createRoadmapFixtureCases(): ReadonlyMap<string, Roadmap | null> {
  const seedDocument = contractRoadmapDocuments[0];
  if (seedDocument === undefined) throw new Error("Missing P1 roadmap document fixture");
  const activeFixture = contractRoadmaps[0];
  if (activeFixture === undefined) throw new Error("Missing P1 hydrated roadmap fixture");

  const emptyDocument = validateRoadmapDocument({
    format: "studio.roadmap/v1",
    title: "Roadmap vide",
    objective: null,
    context: null,
    metadata: {},
    phases: [],
    exported_at: null,
    revision_no: 1,
  });
  const blocked = fromDocument(roadmapFixtureProjectIds.blocked, seedDocument, "active");
  const blockedStep = blocked.phases?.[0]?.steps?.[0];
  if (blockedStep !== undefined) {
    blockedStep.state = "blocked";
    blockedStep.available = false;
    blockedStep.state_override = null;
    blockedStep.state_override_reason = null;
  }
  const partial: Roadmap = {
    id: "roadmap-fixture-partial",
    project_id: roadmapFixtureProjectIds.partial,
    title: "Roadmap partielle",
    objective: null,
    status: "active",
    revision_no: 1,
    approved_revision_no: 1,
    context: null,
    metadata: { fixture: "partial" },
    phases: [{ key: "PARTIAL", title: "Données partielles", objective: null }],
  };

  const cases = new Map<string, Roadmap | null>([
    [roadmapFixtureProjectIds.noRoadmap, null],
    [roadmapFixtureProjectIds.empty, fromDocument(roadmapFixtureProjectIds.empty, emptyDocument, "draft")],
    [roadmapFixtureProjectIds.draft, fromDocument(roadmapFixtureProjectIds.draft, seedDocument, "draft")],
    [roadmapFixtureProjectIds.proposed, fromDocument(roadmapFixtureProjectIds.proposed, seedDocument, "proposed")],
    [roadmapFixtureProjectIds.active, { ...clone(activeFixture), project_id: roadmapFixtureProjectIds.active }],
    [roadmapFixtureProjectIds.completed, fromDocument(roadmapFixtureProjectIds.completed, seedDocument, "completed")],
    [roadmapFixtureProjectIds.large, fromDocument(roadmapFixtureProjectIds.large, largeDocument(), "active")],
    [roadmapFixtureProjectIds.blocked, blocked],
    [roadmapFixtureProjectIds.partial, partial],
  ]);
  return cases;
}
