import type { Platform } from "../platform";
import type { BridgeCommand } from "../platform/contracts";
import { LOCAL_SCHEMAS, type ComponentState, type GraphPage, type GraphNodeRef, type KnowledgeStatus, type CodeGraphStatus, type KnowledgeSearchResult, type CodeSymbolResult } from "../platform/generated/local-contracts.generated";
import { validateSchema } from "../platform/schemaValidator";
import { parseGraphPage } from "./model";

export type GraphKind = "knowledge" | "code" | "project";
export interface SourceStatus { state: ComponentState; message?: string; progress?: number | null }
export interface SearchHit { label: string; uri: string; ref?: GraphNodeRef }
export interface SearchResults { hits: SearchHit[]; partial: boolean; nextCursor: string | null }
export interface GraphDataSource {
  readonly label: string;
  status(): Promise<SourceStatus>;
  page(cursor?: string | null): Promise<GraphPage>;
  expand(ref: GraphNodeRef, cursor?: string | null): Promise<GraphPage>;
  search(query: string, cursor?: string | null): Promise<SearchResults>;
}

export const STATE_LABELS: Record<ComponentState | "loading", string> = {
  loading: "Chargement du graphe…", ready: "Prêt", stale: "Index périmé : les données peuvent être anciennes.",
  indexing: "Indexation en cours…", disabled: "Source désactivée.", not_installed: "Source non installée.",
  unavailable: "Source indisponible.", starting: "Démarrage en cours…", stopping: "Arrêt en cours…",
  recovering: "Rétablissement en cours…", permission_denied: "Accès à la source refusé.",
  incompatible: "Source incompatible avec cette version.", error: "La source a rencontré une erreur.",
};

export function createLocalGraphSource(platform: Platform, kind: "knowledge" | "code", workspaceId: string): GraphDataSource {
  const prefix = kind === "code" ? "code_graph" : "knowledge";
  let sourceId: string | null = null;
  async function request<T>(command: BridgeCommand, payload: Record<string, unknown>, schema: string): Promise<T> {
    const answer = await platform.request(command, payload);
    if (!answer.ok) throw new Error(answer.error.message);
    if (validateSchema(LOCAL_SCHEMAS[schema], answer.response.payload).length) throw new Error("Réponse locale invalide.");
    return answer.response.payload as T;
  }
  function accept(raw: unknown): GraphPage {
    const page = parseGraphPage(raw);
    if (page.source.workspace_id !== workspaceId || page.source.kind !== kind) throw new Error("La source a répondu pour un autre graphe.");
    if (sourceId && sourceId !== page.source.source_id) throw new Error("La source a changé. Rechargez le graphe.");
    sourceId = page.source.source_id;
    return page;
  }
  return {
    label: kind === "knowledge" ? "Connaissances" : "Code",
    async status() {
      if (platform.mode === "web") return { state: "unavailable", message: "Disponible dans Studi’OS Desktop lorsque cette source locale est activée." };
      const status = await request<KnowledgeStatus | CodeGraphStatus>(`${prefix}.status`, { workspace_id: workspaceId }, kind === "knowledge" ? "KnowledgeStatus" : "CodeGraphStatus");
      if (status.workspace_id !== workspaceId) throw new Error("Le statut appartient à un autre dossier.");
      const indexState = status.index?.state;
      const state = status.state === "ready" && indexState !== "ready"
        ? indexState === "absent" ? "unavailable" : indexState === "corrupt" ? "error" : indexState ?? "unavailable"
        : status.state;
      return { state, message: status.error?.message, progress: status.index?.progress_percent };
    },
    async page(cursor = null) {
      return accept(await request<unknown>(`${prefix}.graph_page`, { workspace_id: workspaceId, cursor, limit: 100 }, "GraphPage"));
    },
    async expand(ref, cursor = null) {
      if (!sourceId || ref.source_id !== sourceId) throw new Error("Cette référence n’appartient pas à la source chargée.");
      return accept(await request<unknown>(`${prefix}.graph_expand`, { workspace_id: workspaceId, node: ref, cursor, limit: 100, depth: 1, direction: "both" }, "GraphPage"));
    },
    async search(query, cursor = null) {
      if (kind === "knowledge") {
        const result = await request<KnowledgeSearchResult>("knowledge.search", { workspace_id: workspaceId, query, cursor, limit: 30 }, "KnowledgeSearchResult");
        return { hits: (result.hits ?? []).map((hit) => ({ label: hit.document.title, uri: hit.document.uri })), partial: !result.complete || result.index_state !== "ready" || Boolean(result.next_cursor), nextCursor: result.next_cursor ?? null };
      }
      const result = await request<CodeSymbolResult>("code_graph.find_symbols", { workspace_id: workspaceId, name: query, cursor, limit: 30 }, "CodeSymbolResult");
      return { hits: (result.symbols ?? []).map((hit) => ({ label: hit.name, uri: hit.uri, ...(sourceId ? { ref: { source_id: sourceId, node_id: hit.node_id } } : {}) })), partial: !result.complete || result.index_state !== "ready" || Boolean(result.next_cursor), nextCursor: result.next_cursor ?? null };
    },
  };
}
