/**
 * AIB R2/R4 — lancements de tâche à distance (modèle pull).
 *
 * Enveloppes minces sur les routes canoniques : aucune logique métier. La
 * création est rejouable (`Idempotency-Key` fourni par l'appelant, une clé par
 * tentative logique) ; après toute mutation l'appelant relit, le serveur reste
 * la seule vérité. La machine cible seule rapporte l'exécution.
 *
 * Le snapshot d'exécution est une exception volontaire : il ne décrit pas un
 * état courant mais une trace figée d'une tentative, lue telle quelle.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";

export type TaskLaunch = components["schemas"]["TaskLaunch"];
export type TaskLaunchCreate = components["schemas"]["TaskLaunchCreate"];

/**
 * Délai avant expiration d'un lancement (tâche 63a909ea). Le serveur applique
 * `LAUNCH_DEFAULT_TTL_SECONDS` (2 h) quand le client n'envoie rien ; l'UI
 * propose un choix explicite plutôt que de coder une valeur en dur.
 */
export const LAUNCH_TTL_CHOICES: ReadonlyArray<{ seconds: number; label: string }> = [
  { seconds: 1800, label: "30 minutes" },
  { seconds: 3600, label: "1 heure" },
  { seconds: 7200, label: "2 heures (recommandé)" },
  { seconds: 14400, label: "4 heures" },
  { seconds: 28800, label: "8 heures" },
  { seconds: 86400, label: "24 heures (maximum)" },
];
export const DEFAULT_LAUNCH_TTL_SECONDS = 7200;
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
/**
 * Enregistrement immuable de la configuration effective d'une tentative
 * (DEC-0199). Références et empreintes seulement : le corps ne contient ni
 * contenu, ni chemin absolu, ni secret. `404` tant que la machine cible n'a
 * rien enregistré pour ce lancement : l'appelant traite alors l'absence
 * comme « pas encore capturé », jamais comme un snapshot vide.
 */
export type ExecutionSnapshot = components["schemas"]["ExecutionSnapshot"];
export type ExecutionSnapshotPayload = components["schemas"]["ExecutionSnapshotPayload"];
export type SnapshotResolution = components["schemas"]["SnapshotResolution"];
export type SnapshotAppliedParameters = components["schemas"]["SnapshotAppliedParameters"];
export type SnapshotCaptureError = components["schemas"]["SnapshotCaptureError"];
export type SnapshotCaptureStatus = components["schemas"]["SnapshotCaptureStatus"];
export type EligibleMachines = components["schemas"]["EligibleMachines"];
export type MachineEligibility = components["schemas"]["MachineEligibility"];
export type IneligibilityReason = components["schemas"]["IneligibilityReason"];
export type HarnessReport = components["schemas"]["HarnessReport"];
export type TaskLaunchReplayPreview = components["schemas"]["TaskLaunchReplayPreview"];
export type ReplayDifference = components["schemas"]["ReplayDifference"];
export type ReplayLimitation = components["schemas"]["ReplayLimitation"];

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

/**
 * Snapshot d'exécution du lancement : ce que la machine a réellement appliqué,
 * figé au moment du run. Un `404` remonte en `ApiError` (rien n'est encore
 * enregistré) ; le panneau traduit cette absence en « aucun snapshot » plutôt
 * que d'afficher un état par défaut.
 */
export function getTaskLaunchSnapshot(client: StudioClient, launchId: string): Promise<ExecutionSnapshot> {
  return unwrap(
    client.GET("/api/v1/task-launches/{launch_id}/snapshot", { params: { path: { launch_id: launchId } } }),
  );
}

/**
 * Aperçu de rejeu (P04, DEC-0214) : lecture seule, compare le snapshot du
 * lancement à ce qu'un retry utiliserait aujourd'hui. Rien n'est créé.
 */
export function getTaskLaunchReplayPreview(
  client: StudioClient,
  launchId: string,
): Promise<TaskLaunchReplayPreview> {
  return unwrap(
    client.GET("/api/v1/task-launches/{launch_id}/replay-preview", { params: { path: { launch_id: launchId } } }),
  );
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
