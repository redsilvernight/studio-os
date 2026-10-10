/**
 * AIB R2/R4 — lancements de tâche à distance (modèle pull).
 *
 * Enveloppes minces sur les routes canoniques : aucune logique métier. La
 * création est rejouable (`Idempotency-Key` fourni par l'appelant, une clé par
 * tentative logique) ; après toute mutation l'appelant relit, le serveur reste
 * la seule vérité. La machine cible seule rapporte l'exécution.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";

export type TaskLaunch = components["schemas"]["TaskLaunch"];
export type TaskLaunchCreate = components["schemas"]["TaskLaunchCreate"];
export type TaskLaunchStatus = components["schemas"]["TaskLaunchStatus"];
export type TaskLaunchReasonCode = components["schemas"]["TaskLaunchReasonCode"];
export type TaskLaunchProtocol = components["schemas"]["TaskLaunchProtocol"];
export type TaskLaunchProtocolStatus = components["schemas"]["TaskLaunchProtocolStatus"];
export type TaskLaunchView = components["schemas"]["TaskLaunchView"];
/**
 * Lancement tel que la liste projet le rend : `TaskLaunch` plus la preuve de
 * protocole. Le champ reste optionnel — un serveur plus ancien, ou la lecture
 * par id, ne l'envoie pas ; l'UI le traite alors comme non vérifié plutôt que
 * de le deviner.
 */
export type TaskLaunchWithProtocol = TaskLaunch & { protocol?: TaskLaunchProtocol };
export type EligibleMachines = components["schemas"]["EligibleMachines"];
export type MachineEligibility = components["schemas"]["MachineEligibility"];
export type IneligibilityReason = components["schemas"]["IneligibilityReason"];
export type HarnessReport = components["schemas"]["HarnessReport"];

export const TASK_LAUNCH_PAGE_LIMIT = 100;

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export function getEligibleMachines(
  client: StudioClient,
  taskId: string,
  harnessId?: string,
): Promise<EligibleMachines> {
  return unwrap(
    client.GET("/api/v1/tasks/{task_id}/eligible-machines", {
      params: {
        path: { task_id: taskId },
        ...(harnessId === undefined || harnessId === "" ? {} : { query: { harness_id: harnessId } }),
      },
    }),
  );
}

export function listTaskLaunches(
  client: StudioClient,
  projectId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<TaskLaunchWithProtocol[]> {
  return unwrap(
    client.GET("/api/v1/projects/{project_id}/task-launches", {
      params: {
        path: { project_id: projectId },
        query: { limit: opts.limit ?? TASK_LAUNCH_PAGE_LIMIT, offset: opts.offset ?? 0 },
      },
    }),
  ).then((page) => page.items);
}

export function getTaskLaunch(client: StudioClient, launchId: string): Promise<TaskLaunch> {
  return unwrap(client.GET("/api/v1/task-launches/{launch_id}", { params: { path: { launch_id: launchId } } }));
}

export function createTaskLaunch(
  client: StudioClient,
  projectId: string,
  body: TaskLaunchCreate,
  idempotencyKey: string,
): Promise<TaskLaunch> {
  return unwrap(
    client.POST("/api/v1/projects/{project_id}/task-launches", {
      params: { path: { project_id: projectId }, header: { "Idempotency-Key": idempotencyKey } },
      body,
    }),
  );
}

export function cancelTaskLaunch(
  client: StudioClient,
  launchId: string,
  expectedVersion: number,
): Promise<TaskLaunch> {
  return unwrap(
    client.POST("/api/v1/task-launches/{launch_id}/cancel", {
      params: { path: { launch_id: launchId } },
      body: { expected_version: expectedVersion },
    }),
  );
}
