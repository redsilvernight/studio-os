/**
 * DASH-5 — AI work review resolution.
 *
 * `PATCH /api/v1/ai-work/{id}` with `status: "approved" | "changes_requested"`
 * is the only valid exit from `review_requested`, and the server allows it for
 * a privileged role only (DEC-0041: `403` for the owning non-admin machine,
 * `409 invalid_status_transition` outside `review_requested`). The dashboard
 * never guesses the outcome: it sends the transition and surfaces whatever the
 * server answers.
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
