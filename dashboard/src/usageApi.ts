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
import { newUuid } from "./ui";

export type UsageSummary = components["schemas"]["UsageSummary"];
export type UsageAggregate = components["schemas"]["UsageAggregate"];
export type UsageGroupBy = components["schemas"]["UsageGroupBy"];
/** @public PC0 à vérifier : alias miroir du schéma OpenAPI, sans référence. */
export type UsageTotalStatus = components["schemas"]["UsageTotalStatus"];
/** @public PC0 à vérifier : alias miroir du schéma OpenAPI, sans référence. */
export type UsageTokenTotal = components["schemas"]["UsageTokenTotal"];
/** @public PC0 à vérifier : alias miroir du schéma OpenAPI, sans référence. */
export type UsageCostTotal = components["schemas"]["UsageCostTotal"];

/* Historique des configurations (P06-history-option, DEC-0221). */
/** @public PC0 à vérifier : alias miroir du schéma OpenAPI, sans référence. */
export type ConfigurationRateKey = components["schemas"]["ConfigurationRateKey"];
/** @public PC0 à vérifier : alias miroir du schéma OpenAPI, sans référence. */
export type ConfigurationKey = components["schemas"]["ConfigurationKey"];
/** `value` est une fraction 0..1, `null` quand le dénominateur vaut 0. */
export type ConfigurationRate = components["schemas"]["ConfigurationRate"];
export type ConfigurationHistoryGroup = components["schemas"]["ConfigurationHistoryGroup"];
/** @public PC0 à vérifier : alias miroir du schéma OpenAPI, sans référence. */
export type ConfigurationHistoryUnattributed = components["schemas"]["ConfigurationHistoryUnattributed"];
export type ConfigurationHistory = components["schemas"]["ConfigurationHistory"];

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
  const result = await client.GET("/api/v1/usage/configuration-history", {
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

/* Abonnements déclarés par projet (DEC-0361). */
export type UsageSubscription = components["schemas"]["UsageSubscription"];
export type UsageSubscriptionTerms = Omit<components["schemas"]["UsageSubscriptionUpdate"], "expected_version">;

async function unwrapOk<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

/** GET /api/v1/usage/subscriptions?project_id */
export function listUsageSubscriptions(client: StudioClient, projectId: string): Promise<UsageSubscription[]> {
  return unwrapOk(client.GET("/api/v1/usage/subscriptions", { params: { query: { project_id: projectId } } }));
}

/** POST /api/v1/usage/subscriptions — une clé d'idempotence par tentative logique. */
export function createUsageSubscription(
  client: StudioClient,
  projectId: string,
  terms: UsageSubscriptionTerms,
  idempotencyKey: string = newUuid(),
): Promise<UsageSubscription> {
  return unwrapOk(
    client.POST("/api/v1/usage/subscriptions", {
      params: { header: { "Idempotency-Key": idempotencyKey } },
      body: { ...terms, project_id: projectId },
    }),
  );
}

/** PUT /api/v1/usage/subscriptions/{id} — `409 version_conflict` si la version a bougé. */
export function updateUsageSubscription(
  client: StudioClient,
  subscription: UsageSubscription,
  terms: UsageSubscriptionTerms,
): Promise<UsageSubscription> {
  return unwrapOk(
    client.PUT("/api/v1/usage/subscriptions/{subscription_id}", {
      params: { path: { subscription_id: subscription.id } },
      body: { ...terms, expected_version: subscription.version },
    }),
  );
}

/** DELETE /api/v1/usage/subscriptions/{id}?expected_version → 204. */
export async function deleteUsageSubscription(client: StudioClient, subscription: UsageSubscription): Promise<void> {
  const result = await client.DELETE("/api/v1/usage/subscriptions/{subscription_id}", {
    params: { path: { subscription_id: subscription.id }, query: { expected_version: subscription.version } },
  });
  if (!result.response.ok) throw new ApiError(parseErrorBody(result.response.status, result.error));
}
