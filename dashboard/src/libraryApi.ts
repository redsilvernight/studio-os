/**
 * P12 — canonical Library client (P7/DEC-0071).
 *
 * Thin wrappers over the canonical HTTP routes; no business logic here. Every
 * replayable write sends a fresh client-generated `Idempotency-Key` (one per
 * logical attempt, never reused) and callers refetch after a mutation — the
 * server stays the only truth.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import { newIdempotencyKey } from "./claimsApi";
import type { components } from "./openapi-schema";
import type { LibraryKind } from "./libraryFormat";

export type LibraryResource = components["schemas"]["LibraryResource"];
export type LibraryResourceCreate = components["schemas"]["LibraryResourceCreate"];
export type LibraryVersion = components["schemas"]["LibraryVersion"];
export type LibraryVersionCreate = components["schemas"]["LibraryVersionCreate"];
export type LibraryActivate = components["schemas"]["LibraryActivate"];
export type LibraryDeprecate = components["schemas"]["LibraryDeprecate"];
export type LibraryProjectLock = components["schemas"]["LibraryProjectLock"];
export type LibraryLockCreate = components["schemas"]["LibraryLockCreate"];

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export interface LibraryListQuery {
  kind?: LibraryKind;
  scope?: components["schemas"]["LibraryScope"];
  projectId?: string;
  limit?: number;
  offset?: number;
}

export function listLibraryResources(client: StudioClient, query: LibraryListQuery = {}): Promise<LibraryResource[]> {
  const params: { kind?: string; scope?: string; project_id?: string; limit?: number; offset?: number } = {};
  if (query.kind !== undefined) params.kind = query.kind;
  if (query.scope !== undefined) params.scope = query.scope;
  if (query.projectId !== undefined) params.project_id = query.projectId;
  if (query.limit !== undefined) params.limit = query.limit;
  if (query.offset !== undefined) params.offset = query.offset;
  return unwrap(client.GET("/api/v1/library", { params: { query: params } }));
}

export function getLibraryResource(client: StudioClient, resourceId: string): Promise<LibraryResource> {
  return unwrap(client.GET("/api/v1/library/{resource_id}", { params: { path: { resource_id: resourceId } } }));
}

export function listLibraryVersions(client: StudioClient, resourceId: string): Promise<LibraryVersion[]> {
  return unwrap(
    client.GET("/api/v1/library/{resource_id}/versions", { params: { path: { resource_id: resourceId } } }),
  );
}

export function createLibraryResource(
  client: StudioClient,
  input: LibraryResourceCreate,
  key: string = newIdempotencyKey(),
): Promise<LibraryResource> {
  return unwrap(
    client.POST("/api/v1/library", { params: { header: { "Idempotency-Key": key } }, body: input }),
  );
}

export function createLibraryVersion(
  client: StudioClient,
  resourceId: string,
  input: LibraryVersionCreate,
  key: string = newIdempotencyKey(),
): Promise<LibraryVersion> {
  return unwrap(
    client.POST("/api/v1/library/{resource_id}/versions", {
      params: { path: { resource_id: resourceId }, header: { "Idempotency-Key": key } },
      body: input,
    }),
  );
}

export function activateLibraryVersion(
  client: StudioClient,
  resourceId: string,
  input: LibraryActivate,
  key: string = newIdempotencyKey(),
): Promise<LibraryResource> {
  return unwrap(
    client.POST("/api/v1/library/{resource_id}/activate", {
      params: { path: { resource_id: resourceId }, header: { "Idempotency-Key": key } },
      body: input,
    }),
  );
}

export function deprecateLibraryResource(
  client: StudioClient,
  resourceId: string,
  input: LibraryDeprecate,
  key: string = newIdempotencyKey(),
): Promise<LibraryResource> {
  return unwrap(
    client.POST("/api/v1/library/{resource_id}/deprecate", {
      params: { path: { resource_id: resourceId }, header: { "Idempotency-Key": key } },
      body: input,
    }),
  );
}

export function listLibraryLocks(client: StudioClient, projectId?: string): Promise<LibraryProjectLock[]> {
  return unwrap(
    client.GET("/api/v1/library-locks", {
      params: { query: projectId !== undefined ? { project_id: projectId } : {} },
    }),
  );
}

export function createLibraryLock(
  client: StudioClient,
  input: LibraryLockCreate,
  key: string = newIdempotencyKey(),
): Promise<LibraryProjectLock> {
  return unwrap(
    client.POST("/api/v1/library-locks", { params: { header: { "Idempotency-Key": key } }, body: input }),
  );
}

export function releaseLibraryLock(client: StudioClient, lockId: string): Promise<LibraryProjectLock> {
  return unwrap(
    client.DELETE("/api/v1/library-locks/{lock_id}", { params: { path: { lock_id: lockId } } }),
  );
}
