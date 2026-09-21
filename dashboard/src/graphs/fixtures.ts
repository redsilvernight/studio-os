import knowledgeFixture from "../../../contracts/local/fixtures/valid/graph.knowledge.small.json";
import codeFixture from "../../../contracts/local/fixtures/valid/graph.code.small.json";
import partialFixture from "../../../contracts/local/fixtures/valid/graph.code.partial.json";
import projectionFixture from "../../../contracts/local/fixtures/valid/graph.projection.cross_source.json";
import type { GraphNode, GraphEdge, GraphPage, GraphNodeRef, ComponentState } from "../platform/generated/local-contracts.generated";
import { nodeRef, parseGraphPage } from "./model";
import type { GraphDataSource, GraphKind } from "./provider";

export type FixtureSize = "small" | "medium" | "large" | "empty" | "partial";
export const FIXTURE_SIZES: Record<FixtureSize, string> = {
  small: "Petit exemple", medium: "1 000 nœuds", large: "30 000 nœuds", empty: "Graphe vide", partial: "Graphe partiel",
};

export function fixturePages(kind: GraphKind): GraphPage[] {
  const pages = kind === "project" ? [knowledgeFixture.data, codeFixture.data, projectionFixture.data] : [kind === "knowledge" ? knowledgeFixture.data : codeFixture.data];
  return pages.map((page) => parseGraphPage(structuredClone(page)));
}

function cursorOffset(cursor?: string | null): number {
  if (!cursor) return 0;
  if (!/^offset-\d+$/.test(cursor)) throw new Error("Curseur de démonstration invalide.");
  return Number(cursor.slice(7));
}

export function createFixtureGraphSource(kind: "knowledge" | "code", size: FixtureSize, state: ComponentState = "ready"): GraphDataSource {
  const base = fixturePages(kind)[0]!;
  const total = size === "large" ? 30000 : size === "medium" ? 1000 : size === "empty" ? 0 : (base.nodes ?? []).length;
  const synthetic = size === "large" || size === "medium";
  const source = base.source;
  const refAt = (i: number): GraphNodeRef => ({ source_id: source.source_id, node_id: synthetic ? `fixture-${i}` : base.nodes![i]!.node_id });
  function nodeAt(i: number): GraphNode {
    if (!synthetic) return base.nodes![i]!;
    return { node_id: `fixture-${i}`, label: `${kind === "code" ? "function" : "Document"} ${i.toString().padStart(5, "0")}`, kind: kind === "code" ? "function" : "document", provenance: { source_id: source.source_id, extractor: "fixture", confidence: "declared" } };
  }
  function slice(start: number, limit: number): GraphPage {
    const end = Math.min(total, start + limit);
    const nodes = Array.from({ length: Math.max(0, end - start) }, (_, i) => nodeAt(start + i));
    const edges: GraphEdge[] = synthetic ? nodes.flatMap((node, i) => start + i + 1 < total ? [{
      edge_id: `edge-${start + i}`, kind: "contains" as const, source: nodeRef(node), target: refAt(start + i + 1),
      provenance: { source_id: source.source_id, extractor: "fixture", confidence: "declared" as const },
    }] : []) : total ? base.edges ?? [] : [];
    const frontier = synthetic && end < total ? [refAt(end)] : [];
    return parseGraphPage({ source, nodes, edges, frontier, next_cursor: end < total ? `offset-${end}` : null, truncated: end < total, counts: { nodes: nodes.length, edges: edges.length, total_nodes: total } });
  }
  function partialExpansion(): GraphPage {
    return parseGraphPage({ source, nodes: [{ node_id: "fn-physics-step", kind: "function", label: "physics.step (exemple)", provenance: { source_id: source.source_id, extractor: "fixture", confidence: "declared" } }], counts: { nodes: 1, edges: 0 } });
  }
  return {
    label: kind === "knowledge" ? "Connaissances · démonstration" : "Code · démonstration",
    async status() { return { state, progress: state === "indexing" ? 45 : null }; },
    async page(cursor = null) {
      if (size === "partial" && kind === "code" && !cursor) return parseGraphPage(structuredClone(partialFixture.data));
      if (size === "partial" && kind === "code" && cursor === "cursor-2") return partialExpansion();
      return slice(cursorOffset(cursor), 100);
    },
    async expand(ref, cursor = null) {
      if (ref.source_id !== source.source_id) throw new Error("Source inconnue.");
      if (size === "partial" && kind === "code" && ref.node_id === "fn-physics-step") return partialExpansion();
      if (cursor) return slice(cursorOffset(cursor), 100);
      const i = synthetic ? Number(ref.node_id.replace(/^fixture-/, "")) : (base.nodes ?? []).findIndex((node) => node.node_id === ref.node_id);
      if (!Number.isInteger(i) || i < 0 || i >= total) throw new Error("Référence absente de cette démonstration.");
      return slice(synthetic ? i : 0, 100);
    },
    async search(query, cursor = null) {
      const hits = [];
      let i = cursorOffset(cursor);
      for (; i < total && hits.length < 30; i++) {
        const node = nodeAt(i);
        if (node.label.toLocaleLowerCase().includes(query.toLocaleLowerCase())) hits.push({ label: node.label, uri: node.uri ?? "", ref: refAt(i) });
      }
      return { hits, partial: i < total, nextCursor: i < total ? `offset-${i}` : null };
    },
  };
}

export function projectionFixturePage(): GraphPage { return fixturePages("project")[2]!; }
