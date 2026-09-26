/**
 * A0 — Project members (DEC-0103, TECH/02). Admin-only on the server:
 * a non-admin gets 403 on every call, whatever the project id.
 *
 * - GET /projects/{id}/members lists the memberships with each member's name
 *   and email; GET /users (admin directory) finds who to add.
 * - PUT /projects/{id}/members/{user_id}: 201 created, 200 already a member
 *   (the original grant is kept). No Idempotency-Key: the PUT is idempotent.
 * - DELETE: 204, idempotent; closes the user's open streams on the project.
 * After every mutation the caller refetches; the server stays the truth.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";

export type ProjectMember = components["schemas"]["ProjectMember"];
export type DirectoryUser = components["schemas"]["User"];

/** Admin directory: case-insensitive match on display name or email. */
export async function searchUsers(client: StudioClient, query: string, limit = 20): Promise<DirectoryUser[]> {
  const result = await client.GET("/api/v1/users", { params: { query: { q: query, limit } } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export async function listMembers(client: StudioClient, projectId: string): Promise<ProjectMember[]> {
  const result = await client.GET("/api/v1/projects/{project_id}/members", {
    params: { path: { project_id: projectId } },
  });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

/** Returns the membership and whether it was just created (201 vs 200). */
export async function grantMember(
  client: StudioClient,
  projectId: string,
  userId: string,
): Promise<{ member: ProjectMember; created: boolean }> {
  const result = await client.PUT("/api/v1/projects/{project_id}/members/{user_id}", {
    params: { path: { project_id: projectId, user_id: userId } },
  });
  if (result.response.ok && result.data !== undefined) {
    return { member: result.data, created: result.response.status === 201 };
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export async function revokeMember(client: StudioClient, projectId: string, userId: string): Promise<void> {
  const result = await client.DELETE("/api/v1/projects/{project_id}/members/{user_id}", {
    params: { path: { project_id: projectId, user_id: userId } },
  });
  if (!result.response.ok) throw new ApiError(parseErrorBody(result.response.status, result.error));
}
