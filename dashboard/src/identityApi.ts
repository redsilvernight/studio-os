/**
 * Caller identity (DEC-0110 / DEC-0121): `GET /auth/me` replaces the `email`
 * and `role` claims the dashboard JWT no longer carries. The role is a UI
 * hint only (which buttons to show); the server re-checks it on every write.
 * Cached per token, so a new login or a token change refetches it.
 */
import type { StudioClient } from "./api";
import { getToken } from "./auth";
import type { components } from "./openapi-schema";

export type AuthIdentity = components["schemas"]["AuthIdentity"];

let cached: { token: string; identity: Promise<AuthIdentity | null> } | null = null;

export function fetchIdentity(client: StudioClient): Promise<AuthIdentity | null> {
  const token = getToken();
  if (token === null) return Promise.resolve(null);
  if (cached !== null && cached.token === token) return cached.identity;
  const identity = client
    .GET("/api/v1/auth/me")
    .then((result) => (result.response.ok && result.data !== undefined ? result.data : null))
    .catch(() => null);
  cached = { token, identity };
  return identity;
}

export async function isAdminIdentity(client: StudioClient): Promise<boolean> {
  return (await fetchIdentity(client))?.role === "admin";
}

export function resetIdentityCache(): void {
  cached = null;
}
