/**
 * Chargement de l'atlas : pages de `GET /vault/tree` (200 max) suivies par
 * curseur jusqu'à `ATLAS_MAX_NOTES`. Sans `projectId`, le serveur renvoie les
 * notes studio et celles des projets accessibles.
 */
import type { StudioClient } from "../api";
import { listVaultTree, type VaultNoteSummary } from "../vaultApi";
import { ATLAS_MAX_NOTES } from "./types";

const PAGE_SIZE = 200;

export interface AtlasLoadOptions {
  projectId?: string | null;
  max?: number;
}

export interface AtlasLoadResult {
  notes: VaultNoteSummary[];
  truncated: boolean;
}

export async function loadAtlasNotes(client: StudioClient, opts: AtlasLoadOptions = {}): Promise<AtlasLoadResult> {
  const max = opts.max ?? ATLAS_MAX_NOTES;
  const notes: VaultNoteSummary[] = [];
  let cursor: string | undefined;
  for (;;) {
    const page = await listVaultTree(client, {
      ...(opts.projectId ? { projectId: opts.projectId } : {}),
      limit: Math.min(PAGE_SIZE, max - notes.length),
      ...(cursor !== undefined ? { cursor } : {}),
    });
    notes.push(...page.items);
    const next = page.next_cursor ?? null;
    if (notes.length >= max) return { notes: notes.slice(0, max), truncated: next !== null || notes.length > max };
    if (next === null || page.items.length === 0) return { notes, truncated: false };
    cursor = next;
  }
}
