/**
 * Roadmaps P7/P9 convergence — canonical P3 HTTP client behind `RoadmapDataSource`.
 *
 * The dashboard tab renders through the `RoadmapDataSource` interface; the
 * fixture implementation stays for tests and offline development, and this
 * adapter talks to the real API when it is available (authenticated session).
 * PDF stays a client concern (`window.print()`): the server `format=pdf`
 * answers `501` and is never a source of truth.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import { newIdempotencyKey } from "./claimsApi";
import type { components } from "./openapi-schema";
import { validateRoadmapDocument } from "./roadmapFormat";
import type {
  Roadmap,
  RoadmapDataSource,
  RoadmapDocument,
  RoadmapPhase,
  RoadmapReviewDecision,
  RoadmapStep,
} from "./roadmapTypes";

type ApiRoadmap = components["schemas"]["Roadmap"];
type ApiPhase = components["schemas"]["Phase"];
type ApiStep = components["schemas"]["Step"];
type ApiDocument = components["schemas"]["RoadmapDocument"];

async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export function toViewStep(step: ApiStep): RoadmapStep {
  return {
    id: step.id,
    roadmap_id: step.roadmap_id,
    phase_id: step.phase_id,
    key: step.key,
    position: step.position,
    title: step.title,
    objective: step.objective ?? null,
    context: step.context ?? null,
    instructions: step.instructions ?? null,
    acceptance_criteria: [...(step.acceptance_criteria ?? [])],
    notes: step.notes ?? null,
    metadata: { ...(step.metadata ?? {}) },
    depends_on: [...(step.depends_on ?? [])],
    tasks: (step.tasks ?? []).map((task) => ({
      hydration_key: task.hydration_key,
      title: task.title,
      description: task.description ?? null,
    })),
    criteria_checked: [...(step.criteria_checked ?? [])],
    linked_tasks: (step.linked_tasks ?? []).map((link) => ({
      task_id: link.task_id,
      hydration_key: link.hydration_key ?? "",
      origin: typeof link.origin === "string" ? link.origin : null,
    })),
    state_override: step.state_override ?? null,
    state_override_reason: step.state_override_reason ?? null,
    state: step.state,
    available: step.available,
    waiting_on: [...(step.waiting_on ?? [])],
    task_progress: step.task_progress
      ? { completed: step.task_progress.completed, total: step.task_progress.total }
      : undefined,
    provenance: step.provenance
      ? {
          origin: step.provenance.origin,
          actor_type: step.provenance.actor_type,
          actor_id: step.provenance.actor_id,
          agent_id: step.provenance.agent_id ?? null,
          machine_id: step.provenance.machine_id ?? null,
          at: step.provenance.at,
        }
      : undefined,
  };
}

export function toViewPhase(phase: ApiPhase): RoadmapPhase {
  return {
    id: phase.id,
    roadmap_id: phase.roadmap_id,
    key: phase.key,
    position: phase.position,
    title: phase.title,
    objective: phase.objective ?? null,
    progress: phase.progress
      ? {
          done: phase.progress.done,
          total: phase.progress.total,
          skipped: phase.progress.skipped,
          ratio: phase.progress.ratio,
        }
      : undefined,
    steps: (phase.steps ?? []).map(toViewStep),
  };
}

export function toViewRoadmap(roadmap: ApiRoadmap): Roadmap {
  return {
    id: roadmap.id,
    project_id: roadmap.project_id,
    title: roadmap.title,
    objective: roadmap.objective ?? null,
    status: roadmap.status,
    revision_no: roadmap.revision_no,
    approved_revision_no: roadmap.approved_revision_no ?? null,
    context: roadmap.context ?? null,
    metadata: { ...(roadmap.metadata ?? {}) },
    progress: roadmap.progress
      ? {
          done: roadmap.progress.done,
          total: roadmap.progress.total,
          skipped: roadmap.progress.skipped,
          ratio: roadmap.progress.ratio,
        }
      : undefined,
    current_step_key: roadmap.current_step_key ?? null,
    provenance: roadmap.provenance
      ? {
          origin: roadmap.provenance.origin,
          actor_type: roadmap.provenance.actor_type,
          actor_id: roadmap.provenance.actor_id,
          agent_id: roadmap.provenance.agent_id ?? null,
          machine_id: roadmap.provenance.machine_id ?? null,
          at: roadmap.provenance.at,
        }
      : undefined,
    phases: (roadmap.phases ?? []).map(toViewPhase),
  };
}

export function toApiDocument(document: RoadmapDocument): ApiDocument {
  return {
    format: "studio.roadmap/v1",
    title: document.title,
    objective: document.objective,
    context: document.context,
    metadata: { ...document.metadata },
    phases: document.phases.map((phase) => ({
      key: phase.key,
      title: phase.title,
      objective: phase.objective,
      steps: phase.steps.map((step) => ({
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
  };
}

/**
 * Canonical API data source: reads go through `GET .../roadmaps` + detail,
 * manual edits through `POST /roadmaps/import` (draft, never a Task), reviews
 * through the transitions endpoint with the version just read. A project with
 * no roadmap answers `null` — a normal state, never an error.
 */
export function createApiRoadmapDataSource(client: StudioClient): RoadmapDataSource {
  async function detail(roadmapId: string): Promise<Roadmap> {
    const roadmap = await unwrap(
      client.GET("/api/v1/roadmaps/{roadmap_id}", { params: { path: { roadmap_id: roadmapId } } }),
    );
    return toViewRoadmap(roadmap);
  }

  return {
    async load(projectId: string): Promise<Roadmap | null> {
      const summaries = await unwrap(
        client.GET("/api/v1/projects/{project_id}/roadmaps", {
          params: { path: { project_id: projectId } },
        }),
      );
      if (summaries.length === 0) return null;
      const picked = summaries.find((summary) => summary.status === "active") ?? summaries[0];
      if (picked === undefined) return null;
      return detail(picked.id);
    },

    async replaceDocument(projectId: string, document: RoadmapDocument): Promise<Roadmap> {
      const valid = validateRoadmapDocument(document);
      const created = await unwrap(
        client.POST("/api/v1/roadmaps/import", {
          params: { header: { "Idempotency-Key": newIdempotencyKey() } },
          body: { project_id: projectId, document: toApiDocument(valid), submit: false },
        }),
      );
      return toViewRoadmap(created);
    },

    async reviewProposal(
      projectId: string,
      decision: RoadmapReviewDecision,
      comment?: string,
    ): Promise<Roadmap | null> {
      const summaries = await unwrap(
        client.GET("/api/v1/projects/{project_id}/roadmaps", {
          params: { path: { project_id: projectId } },
        }),
      );
      const proposed = summaries.find((summary) => summary.status === "proposed");
      if (proposed === undefined) return null;
      const current = await unwrap(
        client.GET("/api/v1/roadmaps/{roadmap_id}", {
          params: { path: { roadmap_id: proposed.id } },
        }),
      );
      const transitioned = await unwrap(
        client.POST("/api/v1/roadmaps/{roadmap_id}/transitions", {
          params: { path: { roadmap_id: proposed.id } },
          body: { transition: decision, expected_version: current.version, comment: comment ?? null },
        }),
      );
      return toViewRoadmap(transitioned);
    },
  };
}
