/**
 * Resource-claim workflows (DASH-2).
 *
 * Backend facts (routers/claims.py, services/claims.py):
 * - Claims are SOFT locks: an overlap still returns 201 and emits a
 *   `resource.conflict` event — never a 409. The UI must not invent one.
 *   Overlap visibility via REST does not exist; DASH-3 surfaces the event.
 * - POST /claims accepts `Idempotency-Key`: one fresh UUID per logical
 *   creation attempt, generated client-side, never reused across attempts.
 * - renew = holder-or-admin; release = DELETE → 204, holder-or-admin.
 * After every mutation the caller refetches; the server stays the truth.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";
import { newUuid } from "./ui";

export type ResourceClaim = components["schemas"]["ResourceClaim"];
export type ResourceClaimCreate = components["schemas"]["ResourceClaimCreate"];

/** One fresh key per logical creation attempt. */
export function newIdempotencyKey(): string {
  return newUuid();
}

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export function listClaims(client: StudioClient, projectId?: string): Promise<ResourceClaim[]> {
  return unwrap(
    client.GET("/api/v1/claims", {
      params: { query: projectId !== undefined ? { project_id: projectId } : {} },
    }),
  );
}

export function createClaim(
  client: StudioClient,
  input: ResourceClaimCreate,
  idempotencyKey: string = newIdempotencyKey(),
): Promise<ResourceClaim> {
  return unwrap(
    client.POST("/api/v1/claims", {
      params: { header: { "Idempotency-Key": idempotencyKey } },
      body: input,
    }),
  );
}

export function renewClaim(client: StudioClient, claimId: string): Promise<ResourceClaim> {
  return unwrap(client.POST("/api/v1/claims/{claim_id}/renew", { params: { path: { claim_id: claimId } } }));
}

export async function releaseClaim(client: StudioClient, claimId: string): Promise<void> {
  const result = await client.DELETE("/api/v1/claims/{claim_id}", { params: { path: { claim_id: claimId } } });
  if (!result.response.ok) {
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
}
