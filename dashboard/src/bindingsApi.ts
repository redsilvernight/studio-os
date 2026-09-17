/**
 * P12 — canonical Runtime Binding client (P7/DEC-0071, DEC-0068).
 *
 * Bindings are stored runtime choices keyed by `(target_kind, stable_key)`.
 * `session` is never a stored level — it is ephemeral resolution context sent to
 * `POST /resolutions` only; the create form deliberately omits it.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import { newIdempotencyKey } from "./claimsApi";
import type { components } from "./openapi-schema";
import type { LibraryKind } from "./libraryFormat";

export type RuntimeBinding = components["schemas"]["RuntimeBinding"];
export type RuntimeBindingCreate = components["schemas"]["RuntimeBindingCreate"];
export type RuntimeLevel = components["schemas"]["RuntimeLevel"];

/** Stored levels only (`session` is ephemeral and rejected server-side). */
export const STORED_RUNTIME_LEVELS = ["user", "project_override", "project_default", "studio_default"] as const;
export type StoredRuntimeLevel = (typeof STORED_RUNTIME_LEVELS)[number];

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export interface BindingListQuery {
  level?: RuntimeLevel;
  projectId?: string;
  kind?: LibraryKind;
  stableKey?: string;
}

export function listRuntimeBindings(client: StudioClient, query: BindingListQuery = {}): Promise<RuntimeBinding[]> {
  const params: { level?: RuntimeLevel; project_id?: string; kind?: LibraryKind; stable_key?: string } = {};
  if (query.level !== undefined) params.level = query.level;
  if (query.projectId !== undefined) params.project_id = query.projectId;
  if (query.kind !== undefined) params.kind = query.kind;
  if (query.stableKey !== undefined) params.stable_key = query.stableKey;
  return unwrap(client.GET("/api/v1/runtime-bindings", { params: { query: params } }));
}

export function getRuntimeBinding(client: StudioClient, bindingId: string): Promise<RuntimeBinding> {
  return unwrap(
    client.GET("/api/v1/runtime-bindings/{binding_id}", { params: { path: { binding_id: bindingId } } }),
  );
}

export function createRuntimeBinding(
  client: StudioClient,
  input: RuntimeBindingCreate,
  key: string = newIdempotencyKey(),
): Promise<RuntimeBinding> {
  return unwrap(
    client.POST("/api/v1/runtime-bindings", {
      params: { header: { "Idempotency-Key": key } },
      body: input,
    }),
  );
}

export function deleteRuntimeBinding(client: StudioClient, bindingId: string): Promise<RuntimeBinding> {
  return unwrap(
    client.DELETE("/api/v1/runtime-bindings/{binding_id}", { params: { path: { binding_id: bindingId } } }),
  );
}
