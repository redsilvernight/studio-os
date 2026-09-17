/**
 * P12 — canonical Runtime Registry client (P7/DEC-0071, DEC-0070).
 *
 * `harness_ref`/`provider_ref`/`model_ref` are open strings end-to-end: the UI
 * never proposes a closed vendor catalog (DEC-0070). Updates are guarded by
 * `expected_version`; a stale write surfaces the server `409`.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import { newIdempotencyKey } from "./claimsApi";
import type { components } from "./openapi-schema";

export type RuntimeRegistration = components["schemas"]["RuntimeRegistration"];
export type RuntimeRegistrationCreate = components["schemas"]["RuntimeRegistrationCreate"];
export type RuntimeRegistrationUpdate = components["schemas"]["RuntimeRegistrationUpdate"];
export type RuntimeRegistrationUpdateRequest = components["schemas"]["RuntimeRegistrationUpdateRequest"];
export type RuntimeStatus = components["schemas"]["RuntimeStatus"];

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export interface RuntimeListQuery {
  status?: RuntimeStatus;
  includeRevoked?: boolean;
}

export function listRuntimes(client: StudioClient, query: RuntimeListQuery = {}): Promise<RuntimeRegistration[]> {
  const params: { status?: RuntimeStatus; include_revoked?: boolean } = {};
  if (query.status !== undefined) params.status = query.status;
  if (query.includeRevoked !== undefined) params.include_revoked = query.includeRevoked;
  return unwrap(client.GET("/api/v1/runtimes", { params: { query: params } }));
}

export function getRuntime(client: StudioClient, runtimeId: string): Promise<RuntimeRegistration> {
  return unwrap(client.GET("/api/v1/runtimes/{runtime_id}", { params: { path: { runtime_id: runtimeId } } }));
}

export function registerRuntime(
  client: StudioClient,
  input: RuntimeRegistrationCreate,
  key: string = newIdempotencyKey(),
): Promise<RuntimeRegistration> {
  return unwrap(
    client.POST("/api/v1/runtimes", { params: { header: { "Idempotency-Key": key } }, body: input }),
  );
}

export function updateRuntime(
  client: StudioClient,
  runtimeId: string,
  input: RuntimeRegistrationUpdateRequest,
  key: string = newIdempotencyKey(),
): Promise<RuntimeRegistration> {
  return unwrap(
    client.PATCH("/api/v1/runtimes/{runtime_id}", {
      params: { path: { runtime_id: runtimeId }, header: { "Idempotency-Key": key } },
      body: input,
    }),
  );
}

export function revokeRuntime(client: StudioClient, runtimeId: string): Promise<RuntimeRegistration> {
  return unwrap(
    client.POST("/api/v1/runtimes/{runtime_id}/revoke", { params: { path: { runtime_id: runtimeId } } }),
  );
}
