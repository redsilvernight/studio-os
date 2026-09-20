import { createRoadmapFixtureCases } from "./roadmapFixtures";
import { validateRoadmapDocument } from "./roadmapFormat";
import type {
  Roadmap,
  RoadmapDataSource,
  RoadmapDocument,
  RoadmapPhase,
  RoadmapReviewDecision,
} from "./roadmapTypes";

function clone<T>(value: T): T {
  return structuredClone(value);
}

function documentToRoadmap(projectId: string, document: RoadmapDocument, previous?: Roadmap | null): Roadmap {
  const phases: RoadmapPhase[] = document.phases.map((phase, phasePosition) => ({
    ...clone(phase),
    position: phasePosition,
    steps: phase.steps.map((step, stepPosition) => ({
      ...clone(step),
      position: stepPosition,
      state: "not_started",
      available: step.depends_on.length === 0,
      waiting_on: [...step.depends_on],
      linked_tasks: [],
      criteria_checked: [],
      task_progress: { completed: 0, total: step.tasks.length },
    })),
  }));
  const total = phases.reduce((count, phase) => count + (phase.steps?.length ?? 0), 0);
  return {
    id: previous?.id ?? `session-roadmap-${projectId}`,
    project_id: projectId,
    title: document.title,
    objective: document.objective,
    context: document.context,
    metadata: clone(document.metadata),
    status: "draft",
    revision_no: document.revision_no ?? (previous?.revision_no ?? 0) + 1,
    approved_revision_no: previous?.approved_revision_no ?? null,
    progress: { done: 0, total, skipped: 0, ratio: 0 },
    current_step_key: null,
    phases,
  };
}

/**
 * Fixture/session-only data source for dashboard development. It never calls or
 * impersonates the canonical Roadmap API and all state disappears with the page.
 */
export function createFixtureRoadmapDataSource(): RoadmapDataSource {
  const initial = createRoadmapFixtureCases();
  const state = new Map<string, Roadmap | null>();
  for (const [projectId, roadmap] of initial) state.set(projectId, roadmap === null ? null : clone(roadmap));

  return {
    async load(projectId: string): Promise<Roadmap | null> {
      const roadmap = state.get(projectId) ?? null;
      return roadmap === null ? null : clone(roadmap);
    },

    async replaceDocument(projectId: string, input: RoadmapDocument): Promise<Roadmap> {
      const document = validateRoadmapDocument(input);
      const roadmap = documentToRoadmap(projectId, document, state.get(projectId));
      state.set(projectId, clone(roadmap));
      return clone(roadmap);
    },

    async reviewProposal(
      projectId: string,
      decision: RoadmapReviewDecision,
      comment?: string,
    ): Promise<Roadmap | null> {
      const current = state.get(projectId) ?? null;
      if (current === null) return null;
      if (current.status !== "proposed") throw new Error("Only a proposed roadmap can be reviewed");
      if (decision === "request_changes" && (comment === undefined || comment.trim() === "")) {
        throw new Error("A comment is required when requesting changes");
      }
      const updated = clone(current);
      if (decision === "approve") {
        updated.status = "active";
        updated.approved_revision_no = updated.revision_no;
      } else if (decision === "request_changes") {
        updated.status = "draft";
      } else {
        updated.status = "archived";
      }
      state.set(projectId, clone(updated));
      return clone(updated);
    },
  };
}
