/**
 * Task mutations (DASH-2) — thin wrappers over the canonical endpoints.
 *
 * - PATCH /api/v1/tasks/{id} with REQUIRED `If-Match-Version` (the version
 *   last read). A stale version yields 409 {error_code: version_conflict,
 *   server_version} — surfaced with the live version, never auto-retried.
 * - POST .../claim (caller's machine, agent None, 409 already_claimed when
 *   another machine holds it, status → in_progress).
 * - POST .../release (holder-or-admin; status is left untouched server-side).
 * After every mutation the caller refetches; the server stays the truth.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";

export type Task = components["schemas"]["Task"];
export type TaskPatch = components["schemas"]["TaskUpdate"];

export const TASK_PAGE_LIMIT = 100;

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export function listTasks(
  client: StudioClient,
  opts: { projectId?: string; limit?: number; offset?: number } = {},
): Promise<Task[]> {
  return unwrap(
    client.GET("/api/v1/tasks", {
      params: {
        query: {
          ...(opts.projectId !== undefined ? { project_id: opts.projectId } : {}),
          limit: opts.limit ?? TASK_PAGE_LIMIT,
          offset: opts.offset ?? 0,
        },
      },
    }),
  );
}

export function getTask(client: StudioClient, taskId: string): Promise<Task> {
  return unwrap(client.GET("/api/v1/tasks/{task_id}", { params: { path: { task_id: taskId } } }));
}

export function patchTask(client: StudioClient, taskId: string, patch: TaskPatch, version: number): Promise<Task> {
  return unwrap(
    client.PATCH("/api/v1/tasks/{task_id}", {
      params: { path: { task_id: taskId }, header: { "If-Match-Version": version } },
      body: patch,
    }),
  );
}

export function claimTask(client: StudioClient, taskId: string): Promise<Task> {
  return unwrap(client.POST("/api/v1/tasks/{task_id}/claim", { params: { path: { task_id: taskId } } }));
}

export function releaseTask(client: StudioClient, taskId: string): Promise<Task> {
  return unwrap(client.POST("/api/v1/tasks/{task_id}/release", { params: { path: { task_id: taskId } } }));
}
