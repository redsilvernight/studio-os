import { createRoadmapFixtureCases, roadmapFixtureProjectIds } from "./roadmapFixtures";
import { validateRoadmapDocument } from "./roadmapFormat";
import type {
  Roadmap,
  RoadmapDataSource,
  RoadmapDiffEntry,
  RoadmapDocument,
  RoadmapLifecycleTransition,
  RoadmapPendingProposal,
  RoadmapPhase,
  RoadmapReviewDecision,
  RoadmapStatus,
} from "./roadmapTypes";

function clone<T>(value: T): T {
  return structuredClone(value);
}

/** Lifecycle subset of the server transition table (studio_contracts.roadmaps.ROADMAP_TRANSITIONS). */
const LIFECYCLE_TARGETS: Partial<Record<RoadmapStatus, Partial<Record<RoadmapLifecycleTransition, RoadmapStatus>>>> = {
  draft: { activate: "active", archive: "archived" },
  active: { complete: "completed", archive: "archived" },
  completed: { reopen: "active", archive: "archived" },
};

function seedPendingProposal(roadmap: Roadmap): RoadmapPendingProposal {
  const firstStep = (roadmap.phases ?? []).flatMap((phase) => phase.steps ?? [])[0];
  const revisionNo = (roadmap.revision_no ?? 1) + 1;
  const entries: RoadmapDiffEntry[] = [];
  if (firstStep !== undefined) {
    entries.push({ scope: "step", key: firstStep.key, change: "changed", fields: ["title", "objective"] });
  }
  return {
    roadmapId: roadmap.id,
    roadmapVersion: roadmap.version ?? 1,
    revision: {
      id: `fixture-revision-${roadmap.id}`,
      roadmap_id: roadmap.id,
      revision_no: revisionNo,
      kind: "proposal",
      status: "pending",
      base_revision_no: roadmap.approved_revision_no ?? roadmap.revision_no ?? 1,
      summary: "Clarifier la première étape et son objectif",
      provenance: {
        origin: "ai_proposal",
        actor_type: "agent",
        actor_id: "fixture-agent",
        agent_id: "fixture-agent",
        machine_id: null,
        at: "2026-01-01T00:00:00+00:00",
      },
      reviewed_by_user_id: null,
      reviewed_at: null,
      review_comment: null,
    },
    diff: {
      base_revision_no: roadmap.approved_revision_no ?? null,
      proposal_revision_no: revisionNo,
      entries,
    },
  };
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
  const pending = new Map<string, RoadmapPendingProposal>();
  const activeRoadmap = state.get(roadmapFixtureProjectIds.active) ?? null;
  if (activeRoadmap !== null) {
    pending.set(roadmapFixtureProjectIds.active, seedPendingProposal(activeRoadmap));
  }

  return {
    demo: true,
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

    async loadPendingProposal(projectId: string): Promise<RoadmapPendingProposal | null> {
      const proposal = pending.get(projectId);
      return proposal === undefined ? null : clone(proposal);
    },

    async reviewProposalRevision(
      projectId: string,
      revisionNo: number,
      decision: RoadmapReviewDecision,
      comment?: string,
    ): Promise<Roadmap | null> {
      const proposal = pending.get(projectId);
      const current = state.get(projectId) ?? null;
      if (proposal === undefined || current === null || proposal.revision.revision_no !== revisionNo) {
        return current === null ? null : clone(current);
      }
      if (decision !== "approve" && (comment === undefined || comment.trim() === "")) {
        throw new Error("A comment is required when requesting changes or rejecting");
      }
      if (decision === "approve") {
        const updated = clone(current);
        updated.revision_no = proposal.revision.revision_no;
        updated.approved_revision_no = proposal.revision.revision_no;
        state.set(projectId, clone(updated));
      }
      pending.delete(projectId);
      return clone(state.get(projectId) ?? null);
    },

    async transitionRoadmap(
      roadmap: Roadmap,
      transition: RoadmapLifecycleTransition,
      comment?: string,
    ): Promise<Roadmap> {
      const current = state.get(roadmap.project_id) ?? null;
      if (current === null || current.id !== roadmap.id) throw new Error("Roadmap introuvable");
      if (current.version !== roadmap.version) throw new Error("Version périmée : rechargez la roadmap");
      const target = LIFECYCLE_TARGETS[current.status]?.[transition];
      if (target === undefined) throw new Error(`Transition ${transition} impossible depuis ${current.status}`);
      if (transition === "reopen" && (comment === undefined || comment.trim() === "")) {
        throw new Error("A comment is required to reopen a roadmap");
      }
      const updated = clone(current);
      updated.status = target;
      if (updated.version !== undefined) updated.version += 1;
      state.set(roadmap.project_id, clone(updated));
      return clone(updated);
    },
  };
}
