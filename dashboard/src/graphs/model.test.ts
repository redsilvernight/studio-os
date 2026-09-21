import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { GraphCollection, parseGraphPage } from "./model";
import { createFixtureGraphSource, fixturePages } from "./fixtures";
import type { GraphPage } from "../platform/generated/local-contracts.generated";

describe("P1 graph pages and project projection", () => {
  it("accepts all canonical graph fixtures and rejects every invalid graph fixture", () => {
    for (const group of ["valid", "invalid"]) {
      const directory = new URL(`../../../contracts/local/fixtures/${group}/`, import.meta.url);
      for (const name of readdirSync(directory).filter((name) => name.startsWith("graph."))) {
        const fixture = JSON.parse(readFileSync(new URL(name, directory), "utf8"));
        if (fixture.model !== "GraphPage") continue;
        if (group === "valid") expect(() => parseGraphPage(fixture.data), name).not.toThrow();
        else expect(() => parseGraphPage(fixture.data), name).toThrow();
      }
    }
  });
  it("projects only supplied edges, with namespace-safe node IDs", () => {
    const [knowledge, code, projection] = fixturePages("project") as [GraphPage, GraphPage, GraphPage];
    const graph = new GraphCollection();
    graph.add(knowledge); graph.add(code);
    expect(graph.snapshot().edges).toHaveLength(7);
    graph.add(projection);
    const result = graph.snapshot();
    expect(result.edges).toHaveLength(8);
    expect(result.nodes).toHaveLength(8);
    expect(result.sources).toHaveLength(3);
    expect(result.edges.filter((edge) => edge.source.source_id !== edge.target.source_id)).toEqual(projection.edges);
    const duplicateId = structuredClone(code);
    duplicateId.nodes = [{ ...code.nodes![0]!, node_id: knowledge.nodes![0]!.node_id }];
    duplicateId.edges = []; duplicateId.counts = { nodes: 1, edges: 0 };
    graph.add(duplicateId);
    expect(graph.snapshot().nodes).toHaveLength(9);
  });
  it("keeps missing projection endpoints explicit and never invents nodes", () => {
    const graph = new GraphCollection();
    graph.add(fixturePages("project")[2]);
    expect(graph.snapshot().nodes).toEqual([]);
    expect(graph.snapshot().frontier).toHaveLength(2);
    expect(graph.snapshot().partial).toBe(true);
  });
  it("rejects semantic corruption independently of JSON schema", () => {
    const base = fixturePages("code")[0]!;
    const corruptions: ((page: GraphPage) => void)[] = [
      (p) => { p.counts.nodes++; },
      (p) => { p.nodes!.push(p.nodes![0]!); p.counts.nodes++; },
      (p) => { p.edges!.push(p.edges![0]!); p.counts.edges++; },
      (p) => { p.nodes![0]!.provenance.source_id = "other"; },
      (p) => { p.nodes![0]!.kind = "document"; },
      (p) => { p.edges![0]!.kind = "documents"; },
      (p) => { p.edges![0]!.target.source_id = "other"; },
      (p) => { p.edges![0]!.target.node_id = "missing"; },
      (p) => { p.edges![2]!.provenance.evidence = null; },
      (p) => { p.source.member_sources = ["a", "b"]; },
      (p) => { p.truncated = true; p.next_cursor = null; },
      (p) => { p.nodes![0]!.label = "x".repeat(100000); },
      (p) => { p.nodes![0]!.uri = "javascript:alert(1)"; },
    ];
    for (const corrupt of corruptions) {
      const page = structuredClone(base); corrupt(page);
      expect(() => parseGraphPage(page)).toThrow();
    }
  });
  it("refuses mixed workspaces and changed index generations without altering accepted data", () => {
    const graph = new GraphCollection(); const page = fixturePages("code")[0]!;
    graph.add(page);
    for (const field of ["workspace_id", "index_fingerprint", "generated_at"] as const) {
      const changed = structuredClone(page);
      changed.source[field] = field === "workspace_id" ? "22222222-2222-4222-8222-222222222222" : field === "generated_at" ? "2026-09-21T00:00:00Z" : "f".repeat(64);
      expect(() => graph.add(changed)).toThrow();
    }
    expect(graph.snapshot().nodes).toHaveLength(4);
  });
  it("pages through a medium fixture and expands the partial fixture", async () => {
    const source = createFixtureGraphSource("code", "medium");
    const graph = new GraphCollection();
    let cursor: string | null = null;
    do { const page = await source.page(cursor); graph.add(page); cursor = page.next_cursor ?? null; } while (cursor);
    expect(graph.snapshot().nodes).toHaveLength(1000);
    expect(graph.snapshot().edges).toHaveLength(999);
    expect(graph.snapshot().partial).toBe(false);
    const partial = createFixtureGraphSource("code", "partial");
    const page = await partial.page();
    const partialGraph = new GraphCollection(); partialGraph.add(page);
    partialGraph.add(await partial.expand(page.frontier![0]!));
    expect(partialGraph.snapshot().frontier).toHaveLength(0);
    expect(partialGraph.snapshot().partial).toBe(true);
  });
  it("searches a 30k fixture without loading it and bounds retained memory", async () => {
    const source = createFixtureGraphSource("code", "large");
    const result = await source.search("29999");
    expect(result.hits[0]?.label).toContain("29999");
    const graph = new GraphCollection();
    for (let i = 0; i < 50; i++) graph.add(await source.page(i ? `offset-${i * 100}` : null));
    expect(graph.snapshot().nodes).toHaveLength(5000);
    expect(() => graph.add({})).toThrow();
    const overflow = await source.page("offset-5000");
    expect(() => graph.add(overflow)).toThrow(/mémoire/);
    expect(graph.snapshot().nodes).toHaveLength(5000);
  });
});
