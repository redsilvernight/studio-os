/**
 * P14 — client Vault canonique (API livrée : tree paginé, notes CRUD avec
 * `expected_version`, versions/historique, search).
 *
 * Enveloppes fines sur les routes canoniques, sans logique métier : après
 * chaque mutation l'appelant recharge ; le serveur reste la seule vérité.
 * Un écriture périmée donne `409 version_conflict` (avec `server_version`),
 * jamais un écrasement silencieux.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";

export type VaultNote = components["schemas"]["VaultNote"];
export type VaultNoteSummary = components["schemas"]["VaultNoteSummary"];
export type VaultNoteUpdate = components["schemas"]["VaultNoteUpdate"];
export type VaultNoteVersion = components["schemas"]["VaultNoteVersion"];
export type VaultScope = components["schemas"]["VaultScope"];
export type VaultNoteType = components["schemas"]["VaultNoteType"];
export type VaultNoteStatus = components["schemas"]["VaultNoteStatus"];
export type VaultTreePage = components["schemas"]["VaultTreePage"];
export type VaultSearchResult = components["schemas"]["VaultSearchResult"];
export type VaultVersionPage = components["schemas"]["VaultVersionPage"];

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export interface VaultTreeQuery {
  scope?: VaultScope;
  projectId?: string;
  status?: VaultNoteStatus;
  includeArchived?: boolean;
  limit?: number;
  cursor?: string;
}

export function listVaultTree(client: StudioClient, query: VaultTreeQuery = {}): Promise<VaultTreePage> {
  return unwrap(
    client.GET("/api/v1/vault/tree", {
      params: {
        query: {
          ...(query.scope !== undefined ? { scope: query.scope } : {}),
          ...(query.projectId !== undefined ? { project_id: query.projectId } : {}),
          ...(query.status !== undefined ? { status: query.status } : {}),
          ...(query.includeArchived !== undefined ? { include_archived: query.includeArchived } : {}),
          ...(query.limit !== undefined ? { limit: query.limit } : {}),
          ...(query.cursor !== undefined ? { cursor: query.cursor } : {}),
        },
      },
    }),
  );
}

export interface VaultSearchQuery {
  q?: string;
  scope?: VaultScope;
  projectId?: string;
  noteTypes?: VaultNoteType[];
  statuses?: VaultNoteStatus[];
  limit?: number;
}

export function searchVault(client: StudioClient, query: VaultSearchQuery): Promise<VaultSearchResult> {
  return unwrap(
    client.GET("/api/v1/vault/search", {
      params: {
        query: {
          ...(query.q !== undefined ? { q: query.q } : {}),
          ...(query.scope !== undefined ? { scope: query.scope } : {}),
          ...(query.projectId !== undefined ? { project_id: query.projectId } : {}),
          ...(query.noteTypes !== undefined && query.noteTypes.length > 0 ? { note_type: query.noteTypes } : {}),
          ...(query.statuses !== undefined && query.statuses.length > 0 ? { status: query.statuses } : {}),
          ...(query.limit !== undefined ? { limit: query.limit } : {}),
        },
      },
    }),
  );
}

export function getVaultNote(client: StudioClient, noteId: string): Promise<VaultNote> {
  return unwrap(
    client.GET("/api/v1/vault/notes/{note_id}", { params: { path: { note_id: noteId } } }),
  );
}

/** `update.expected_version` est obligatoire : version périmée → `409 version_conflict`. */
export function updateVaultNote(
  client: StudioClient,
  noteId: string,
  update: VaultNoteUpdate,
): Promise<VaultNote> {
  return unwrap(
    client.PATCH("/api/v1/vault/notes/{note_id}", {
      params: { path: { note_id: noteId } },
      body: update,
    }),
  );
}

export function listVaultVersions(
  client: StudioClient,
  noteId: string,
  opts: { limit?: number; cursor?: string } = {},
): Promise<VaultVersionPage> {
  return unwrap(
    client.GET("/api/v1/vault/notes/{note_id}/versions", {
      params: {
        path: { note_id: noteId },
        query: {
          ...(opts.limit !== undefined ? { limit: opts.limit } : {}),
          ...(opts.cursor !== undefined ? { cursor: opts.cursor } : {}),
        },
      },
    }),
  );
}

export function getVaultVersion(
  client: StudioClient,
  noteId: string,
  version: number,
): Promise<VaultNoteVersion> {
  return unwrap(
    client.GET("/api/v1/vault/notes/{note_id}/versions/{version}", {
      params: { path: { note_id: noteId, version } },
    }),
  );
}
