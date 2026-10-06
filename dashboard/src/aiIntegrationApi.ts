/**
 * AI integration status (AIB P6) — read-only.
 *
 * Backend fact (routers/ai_integration.py): GET /projects/{id}/ai-integration
 * returns the project's *desired* state (aggregated bootstrap plan) next to
 * what each of the caller's machines *reported* through its heartbeat
 * capability report (R1). A reported value is a machine claim with its
 * reception time and a `freshness`: the server never asserts a write on a
 * machine it has not been told about, and neither does this client.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";

export type AiIntegrationStatus = components["schemas"]["AiIntegrationStatus"];
export type DesiredIntegration = components["schemas"]["DesiredIntegration"];
export type ReportedMachineIntegration = components["schemas"]["ReportedMachineIntegration"];
export type HarnessReport = components["schemas"]["HarnessReport"];
export type ReportFreshness = components["schemas"]["ReportFreshness"];

export async function getAiIntegrationStatus(
  client: StudioClient,
  projectId: string,
): Promise<AiIntegrationStatus> {
  const result = await client.GET("/api/v1/projects/{project_id}/ai-integration", {
    params: { path: { project_id: projectId } },
  });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}
