/**
 * A3 — Account administration (TECH/02 « Administration des comptes »).
 * Admin-only on the server: a non-admin gets 403 before any lookup, and
 * targeting your own account is `403 self_modification_forbidden`.
 *
 * - POST /users/{id}/disable|enable|revoke-sessions return the updated User.
 * - GET /users/{id}/memberships lists the projects the User can access.
 * After every mutation the caller refetches; the server stays the truth.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { DirectoryUser, ProjectMember } from "./membersApi";

export type AccountAction = "disable" | "enable" | "revoke-sessions";

export async function applyAccountAction(
  client: StudioClient,
  userId: string,
  action: AccountAction,
): Promise<DirectoryUser> {
  const params = { params: { path: { user_id: userId } } };
  const result =
    action === "disable"
      ? await client.POST("/api/v1/users/{user_id}/disable", params)
      : action === "enable"
        ? await client.POST("/api/v1/users/{user_id}/enable", params)
        : await client.POST("/api/v1/users/{user_id}/revoke-sessions", params);
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export async function listUserMemberships(client: StudioClient, userId: string): Promise<ProjectMember[]> {
  const result = await client.GET("/api/v1/users/{user_id}/memberships", {
    params: { path: { user_id: userId } },
  });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}
