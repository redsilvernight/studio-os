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
export type UsageTokenTotal = components["schemas"]["UsageTokenTotal"];
export type UsageCostTotal = components["schemas"]["UsageCostTotal"];

/* ------------------------------------------------------------------ */
/* Historique des configurations (P06-history-option, DEC-0221).       */
/*                                                                     */
/* TODO(openapi-sync) : ces types sont un miroir local exact de        */
/* `ConfigurationHistory` (studio_contracts/usage.py) tant que         */
/* l'openapi n'a pas été régénéré. Les remplacer par les types générés */
/* (`components["schemas"]["ConfigurationHistory"]`) à la prochaine    */
/* synchronisation, sans changer le reste du module.                   */
/* ------------------------------------------------------------------ */

export type ConfigurationRateKey = "succeeded" | "session_linked" | "usage_measured";

export interface ConfigurationKey {
  harness: string;
  profile_key: string | null;
  profile_contract_version: number | null;
  profile_digest: string | null;
  harness_version: string | null;
  provider: string | null;
  model: string | null;
}

/** `value` est une fraction 0..1, `null` quand le dénominateur vaut 0. */
export interface ConfigurationRate {
  key: ConfigurationRateKey;
  definition: string;
  numerator: number;
  denominator: number;
  covered: number;
  launches: number;
  value: number | null;
}

export interface ConfigurationHistoryGroup {
  key: ConfigurationKey;
  launches: number;
  first_requested_at: string;
  last_requested_at: string;
  status_counts: Record<string, number>;
  rates: ConfigurationRate[];
  ledger_entries: number;
  ai_work_entries: number;
  total_tokens: UsageTokenTotal;
  cost: UsageCostTotal;
  comparable: false;
}

export interface ConfigurationHistoryUnattributed {
  ledger_entries: number;
  ai_work_entries: number;
}

export interface ConfigurationHistory {
  project_id: string;
  since: string;
  until: string;
  generated_at: string;
  population: "task_launch";
  ranking: "none";
  launches: number;
  groups: ConfigurationHistoryGroup[];
  unattributed: ConfigurationHistoryUnattributed;
  caveats: string[];
  truncated: boolean;
}

export interface ConfigurationHistoryQuery {
  since: string;
  until: string;
}

function isConfigurationHistory(value: unknown): value is ConfigurationHistory {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const candidate = value as { groups?: unknown; unattributed?: unknown };
  return (
    Array.isArray(candidate.groups) &&
    typeof candidate.unattributed === "object" &&
    candidate.unattributed !== null &&
    !Array.isArray(candidate.unattributed)
  );
}

/** GET /api/v1/usage/configuration-history?project_id&since&until (lecture seule). */
export async function fetchConfigurationHistory(
  client: StudioClient,
  projectId: string,
  query: ConfigurationHistoryQuery,
): Promise<ConfigurationHistory> {
  // Le chemin n'existe pas encore dans `paths` (openapi non régénéré) :
  // cast local, le contrat est vérifié par `isConfigurationHistory`.
  const get = client.GET as unknown as (
    path: string,
    init: { params: { query: { project_id: string; since: string; until: string } } },
  ) => Promise<{ data?: unknown; error?: unknown; response: Response }>;
  const result = await get("/api/v1/usage/configuration-history", {
    params: { query: { project_id: projectId, since: query.since, until: query.until } },
  });
  if (result.response.ok && result.data !== undefined) {
    if (!isConfigurationHistory(result.data)) throw new Error("Réponse d'historique des configurations inattendue.");
    return result.data;
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

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
