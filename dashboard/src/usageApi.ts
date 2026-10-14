/**
 * Consommation — agrégats d'usage d'un projet ou d'une tâche (P03-usage-ui).
 *
 * GET /api/v1/usage/summary : lecture seule, calculée côté serveur à partir
 * du ledger (chaque fait compté une fois, dans sa dernière forme corrigée).
 * Chaque métrique porte un `status` qui fait foi : le client n'additionne
 * jamais rien lui-même. Une erreur garde son statut HTTP (403 = refus final).
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";

export type UsageSummary = components["schemas"]["UsageSummary"];
export type UsageAggregate = components["schemas"]["UsageAggregate"];
export type UsageGroupBy = components["schemas"]["UsageGroupBy"];
export type UsageTotalStatus = components["schemas"]["UsageTotalStatus"];

export interface UsageSummaryQuery {
  projectId: string;
  taskId?: string;
  taskLaunchId?: string;
  groupBy?: UsageGroupBy;
  since?: string;
  until?: string;
}

function isUsageSummary(value: unknown): value is UsageSummary {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as { total?: unknown };
  return typeof candidate.total === "object" && candidate.total !== null && !Array.isArray(value);
}

export async function fetchUsageSummary(client: StudioClient, query: UsageSummaryQuery): Promise<UsageSummary> {
  const params: {
    project_id: string;
    task_id?: string;
    task_launch_id?: string;
    group_by?: UsageGroupBy;
    since?: string;
    until?: string;
  } = { project_id: query.projectId };
  if (query.taskId !== undefined) params.task_id = query.taskId;
  if (query.taskLaunchId !== undefined) params.task_launch_id = query.taskLaunchId;
  if (query.groupBy !== undefined) params.group_by = query.groupBy;
  if (query.since !== undefined) params.since = query.since;
  if (query.until !== undefined) params.until = query.until;
  const result = await client.GET("/api/v1/usage/summary", { params: { query: params } });
  if (result.response.ok && result.data !== undefined) {
    if (!isUsageSummary(result.data)) throw new Error("Réponse de consommation inattendue.");
    return result.data;
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}
