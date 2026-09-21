import { LOCAL_SCHEMAS, type GraphPage, type GraphNode, type GraphEdge, type GraphSource, type GraphNodeRef, type NodeKind, type RelationKind } from "../platform/generated/local-contracts.generated";
import { validateSchema } from "../platform/schemaValidator";

export interface ViewerData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  sources: GraphSource[];
  frontier: GraphNodeRef[];
  partial: boolean;
}

export const MAX_LOADED_NODES = 5000;
export const MAX_LOADED_EDGES = 10000;
export const nodeKey = (ref: GraphNodeRef): string => JSON.stringify([ref.source_id, ref.node_id]);
export const nodeRef = (node: GraphNode): GraphNodeRef => ({ source_id: node.provenance.source_id, node_id: node.node_id });

export const nodeKindsBySource: Record<GraphSource["kind"], readonly NodeKind[]> = {
  knowledge: ["document", "heading", "tag"],
  code: ["file", "package", "module", "class", "function"],
  projection: [],
};
const relations: Record<GraphSource["kind"], readonly RelationKind[]> = {
  knowledge: ["links_to", "tagged_with", "embeds", "contains"],
  code: ["imports", "calls", "defines", "inherits", "references", "contains"],
  projection: ["documents"],
};

function invalid(): never { throw new Error("Le graphe reçu ne respecte pas le contrat commun."); }

function checkLocalReference(uri: string | null | undefined): void {
  if (uri == null) return;
  const match = /^studio-local:\/\/(knowledge|code|harness)\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/([^#]*)(?:#L\d{1,7}(?:-L\d{1,7})?)?$/.exec(uri);
  if (!match || uri.length > 700) invalid();
  const path = match[2]!;
  if (path && (path.length > 512 || /[\\<>:"|?*%\x00-\x1f\x7f]/.test(path) || path.split("/").some((part) => !part || part === "." || part === ".."))) invalid();
}

export function parseGraphPage(raw: unknown): GraphPage {
  if (validateSchema(LOCAL_SCHEMAS.GraphPage, raw).length) invalid();
  const page = raw as GraphPage;
  const { source } = page;
  const nodes = page.nodes ?? [];
  const edges = page.edges ?? [];
  const frontier = new Set((page.frontier ?? []).map(nodeKey));
  const ids = new Set(nodes.map((node) => node.node_id));
  const members = new Set(source.member_sources ?? []);
  if (ids.size !== nodes.length || new Set(edges.map((edge) => edge.edge_id)).size !== edges.length) invalid();
  if (page.counts.nodes !== nodes.length || page.counts.edges !== edges.length) invalid();
  if (source.kind === "projection" ? members.size !== 2 : members.size !== 0) invalid();
  if (page.truncated && !page.next_cursor && frontier.size === 0) invalid();
  for (const node of nodes) {
    if (!nodeKindsBySource[source.kind].includes(node.kind) || node.provenance.source_id !== source.source_id) invalid();
    checkLocalReference(node.uri);
  }
  for (const item of [...nodes, ...edges]) {
    if (item.provenance.confidence === "inferred" && !item.provenance.evidence) invalid();
    checkLocalReference(item.provenance.evidence);
  }
  for (const edge of edges) {
    if (!relations[source.kind].includes(edge.kind) || edge.provenance.source_id !== source.source_id) invalid();
    if (source.kind === "projection") {
      if (edge.source.source_id === edge.target.source_id || !members.has(edge.source.source_id) || !members.has(edge.target.source_id)) invalid();
    } else {
      for (const end of [edge.source, edge.target]) {
        if (end.source_id !== source.source_id || (!ids.has(end.node_id) && !frontier.has(nodeKey(end)))) invalid();
      }
    }
  }
  return page;
}

export class GraphCollection {
  private nodes = new Map<string, GraphNode>();
  private edges = new Map<string, GraphEdge>();
  private sources = new Map<string, GraphSource>();
  private frontier = new Map<string, GraphNodeRef>();
  private incomplete = new Map<string, boolean>();
  private totals = new Map<string, number>();
  private workspace: string | null = null;

  add(raw: unknown, mode: "page" | "expand" = "page"): void {
    const page = parseGraphPage(raw);
    const source = page.source;
    if (this.workspace && this.workspace !== source.workspace_id) throw new Error("Le graphe appartient à un autre dossier.");
    const previous = this.sources.get(source.source_id);
    if (previous && (previous.kind !== source.kind || previous.provider_id !== source.provider_id ||
      previous.index_fingerprint !== source.index_fingerprint || previous.generated_at !== source.generated_at ||
      JSON.stringify(previous.member_sources ?? []) !== JSON.stringify(source.member_sources ?? []))) {
      throw new Error("L’index a changé. Rechargez le graphe avant de continuer.");
    }
    const freshNodes = (page.nodes ?? []).filter((node) => !this.nodes.has(nodeKey(nodeRef(node))));
    const freshEdges = (page.edges ?? []).filter((edge) => !this.edges.has(JSON.stringify([source.source_id, edge.edge_id])));
    if (this.nodes.size + freshNodes.length > MAX_LOADED_NODES || this.edges.size + freshEdges.length > MAX_LOADED_EDGES) {
      throw new Error("Limite de mémoire atteinte. Utilisez la recherche dans la source ou rechargez le graphe.");
    }
    this.workspace = source.workspace_id;
    this.sources.set(source.source_id, source);
    if (page.counts.total_nodes != null) this.totals.set(source.source_id, page.counts.total_nodes);
    for (const node of page.nodes ?? []) this.nodes.set(nodeKey(nodeRef(node)), node);
    for (const edge of page.edges ?? []) this.edges.set(JSON.stringify([source.source_id, edge.edge_id]), edge);
    for (const ref of page.frontier ?? []) this.frontier.set(nodeKey(ref), ref);
    for (const key of this.nodes.keys()) this.frontier.delete(key);
    this.incomplete.set(source.source_id, Boolean(page.truncated || page.next_cursor || (mode === "expand" && this.incomplete.get(source.source_id))));
  }

  snapshot(): ViewerData {
    const unresolved = new Map(this.frontier);
    const loaded = new Map<string, number>();
    for (const node of this.nodes.values()) loaded.set(node.provenance.source_id, (loaded.get(node.provenance.source_id) ?? 0) + 1);
    for (const edge of this.edges.values()) {
      for (const ref of [edge.source, edge.target]) if (!this.nodes.has(nodeKey(ref))) unresolved.set(nodeKey(ref), ref);
    }
    return {
      nodes: [...this.nodes.values()], edges: [...this.edges.values()], sources: [...this.sources.values()],
      frontier: [...unresolved.values()], partial: unresolved.size > 0 || [...this.incomplete.values()].some(Boolean) || [...this.totals].some(([id, count]) => (loaded.get(id) ?? 0) < count),
    };
  }
}
