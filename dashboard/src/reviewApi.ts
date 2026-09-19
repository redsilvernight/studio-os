/**
 * DASH-5 / UI-8 — Review Queue actions.
 *
 * Only `ai_work_review` has a real backend transition:
 *   PATCH /api/v1/ai-work/{id} with status "approved" | "changes_requested"
 * Other kinds (decision_proposal, resource_conflict, build_failure, pr_ready)
 * are informational / best-effort signals — no transition endpoint exists.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";

export type AIWorkLog = components["schemas"]["AIWorkLog"];
export type ReviewResolution = "approved" | "changes_requested";

export function resolveReview(
  client: StudioClient,
  workId: string,
  resolution: ReviewResolution,
): Promise<AIWorkLog> {
  return unwrap(
    client.PATCH("/api/v1/ai-work/{work_id}", {
      params: { path: { work_id: workId } },
      body: { status: resolution },
    }),
  );
}

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}