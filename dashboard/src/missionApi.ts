/**
 * Mission Control — read model des exécutions d'un projet (P02-mission-ui).
 *
 * GET /api/v1/projects/{project_id}/mission : lecture seule, calculée à la
 * lecture côté serveur. Pagination par `cursor` opaque (`next_cursor`),
 * `limit` borné serveur (défaut 20, max 50). Le verdict renvoyé fait foi :
 * le client ne le re-dérive jamais. Une erreur garde son statut HTTP
 * (403 = accès refusé au projet, final).
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";

export type ProjectMission = components["schemas"]["ProjectMission"];
export type MissionRun = components["schemas"]["MissionRun"];

export async function fetchProjectMission(
  client: StudioClient,
  projectId: string,
  opts: { cursor?: string; limit?: number } = {},
): Promise<ProjectMission> {
  const query: { cursor?: string; limit?: number } = {};
  if (opts.cursor !== undefined) query.cursor = opts.cursor;
  if (opts.limit !== undefined) query.limit = opts.limit;
  const result = await client.GET("/api/v1/projects/{project_id}/mission", {
    params: { path: { project_id: projectId }, query },
  });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}
