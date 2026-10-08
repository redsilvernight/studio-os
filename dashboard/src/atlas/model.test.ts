import { describe, expect, it } from "vitest";
import type { VaultNoteSummary } from "../vaultApi";
import { applyFilters, buildAtlasGraph, defaultFilters, layoutAtlas, normalizeText, parseAnchor } from "./model";
import { ATLAS_CLUSTER_THRESHOLD } from "./types";

const STAMP = "2026-10-08T10:00:00Z";

function note(id: string, overrides: Partial<VaultNoteSummary> = {}): VaultNoteSummary {
  return {
    id,
    scope: "studio",
    project_id: null,
    slug: id,
    readable_id: null,
    note_type: "note",
    title: `Note ${id}`,
    summary: "",
    status: "validated",
    tags: [],
    links: [],
    anchors: [],
    version: 1,
    created_at: STAMP,
    updated_at: STAMP,
    ...overrides,
  } as VaultNoteSummary;
}

const NOTES = [
  note("old", { note_type: "decision", readable_id: "DEC-0001", title: "Cache local", status: "superseded" }),
  note("new", {
    note_type: "decision",
    readable_id: "DEC-0002",
    title: "Stratégie de cache Redis",
    links: [
      { target_note_id: "old", kind: "supersedes" },
      { target_note_id: "rule", kind: "relates_to" },
      { target_note_id: "absent", kind: "links_to" },
    ],
    anchors: ["task:t-1", "path:src/cache.ts", "src/cache.ts"],
  }),
  note("rule", { note_type: "rule", title: "Pas de secret", anchors: ["task:t-1"] }),
  note("proj", { scope: "project", project_id: "p1", note_type: "procedure", title: "Release", status: "proposed" }),
];

describe("atlas model", () => {
  it("normalizes text and parses anchors", () => {
    expect(normalizeText("  Stratégie  ÉTÉ ")).toBe("strategie ete");
    expect(parseAnchor("task:abc")).toEqual({ anchorType: "task", label: "abc" });
    expect(parseAnchor("path:a/b.ts")).toEqual({ anchorType: "path", label: "a/b.ts" });
    expect(parseAnchor("a/b.ts")).toEqual({ anchorType: "path", label: "a/b.ts" });
    expect(parseAnchor(" ")).toBeNull();
  });

  it("builds notes, typed edges and shared satellites, ignoring unknown targets", () => {
    const graph = buildAtlasGraph(NOTES, false);
    expect(graph.nodes.filter((n) => n.kind === "note")).toHaveLength(4);
    // task:t-1 partagé, path:src/cache.ts dédoublonné (avec ou sans préfixe).
    expect(graph.nodes.filter((n) => n.kind === "satellite").map((n) => n.id).sort()).toEqual([
      "anchor:path:src/cache.ts",
      "anchor:task:t-1",
    ]);
    expect(graph.edges.find((e) => e.kind === "supersedes")).toEqual({ source: "new", target: "old", kind: "supersedes" });
    expect(graph.edges.some((e) => e.target === "absent")).toBe(false);
    expect([...(graph.neighbors.get("anchor:task:t-1") ?? [])].sort()).toEqual(["new", "rule"]);
  });

  it("lays out deterministically with finite positions", () => {
    const a = buildAtlasGraph(NOTES, false);
    const b = buildAtlasGraph([...NOTES].reverse(), false);
    layoutAtlas(a);
    layoutAtlas(b);
    for (const node of a.nodes) {
      const other = b.byId.get(node.id)!;
      expect(Number.isFinite(node.position.x + node.position.y + node.position.z)).toBe(true);
      expect(node.position.x).toBeCloseTo(other.position.x, 6);
      expect(node.radius).toBeGreaterThan(0);
    }
    const dec = a.byId.get("new")!;
    const plain = a.byId.get("proj")!;
    expect(dec.radius).toBeGreaterThan(plain.radius);
  });

  it("spaces notes and keeps group discs apart, with labelled groups", () => {
    const many = Array.from({ length: 240 }, (_, i) =>
      note(`n${i}`, { note_type: i % 3 === 0 ? "rule" : "decision", scope: i % 5 === 0 ? "project" : "studio", project_id: i % 5 === 0 ? "p1" : null }));
    const graph = buildAtlasGraph(many, false);
    layoutAtlas(graph);
    const notes = graph.nodes.filter((n) => n.kind === "note");
    let closest = Infinity;
    for (let i = 0; i < notes.length; i += 1) {
      for (let j = i + 1; j < notes.length; j += 1) {
        const a = notes[i]!.position;
        const b = notes[j]!.position;
        closest = Math.min(closest, Math.hypot(a.x - b.x, a.y - b.y));
      }
    }
    expect(closest).toBeGreaterThan(7);
    const view = applyFilters(graph, defaultFilters(), new Map([["p1", "Kartouche"]]));
    expect(view.groups).toHaveLength(4);
    for (const g of view.groups) {
      for (const h of view.groups) {
        if (g.id >= h.id) continue;
        expect(Math.hypot(g.center.x - h.center.x, g.center.y - h.center.y)).toBeGreaterThan(g.radius + h.radius);
      }
    }
    expect(view.groups.map((g) => g.label)).toContain("Kartouche · Règles (16)");
  });

  it("hides superseded by default and filters by type, scope and status", () => {
    const graph = buildAtlasGraph(NOTES, false);
    layoutAtlas(graph);
    const ids = (filters = defaultFilters()): string[] =>
      applyFilters(graph, filters).nodes.filter((n) => n.kind === "note").map((n) => n.id).sort();
    expect(ids()).toEqual(["new", "proj", "rule"]);
    expect(ids({ ...defaultFilters(), showSuperseded: true })).toEqual(["new", "old", "proj", "rule"]);
    expect(ids({ ...defaultFilters(), noteTypes: ["rule"] })).toEqual(["rule"]);
    expect(ids({ ...defaultFilters(), scopes: ["project"] })).toEqual(["proj"]);
    expect(ids({ ...defaultFilters(), statuses: ["proposed"] })).toEqual(["proj"]);
  });

  it("keeps edges and satellites only between visible nodes", () => {
    const graph = buildAtlasGraph(NOTES, false);
    const view = applyFilters(graph, { ...defaultFilters(), showSatellites: true });
    expect(view.edges.some((e) => e.kind === "supersedes")).toBe(false);
    expect(view.nodes.some((n) => n.id === "anchor:task:t-1")).toBe(true);
    const bare = applyFilters(graph, defaultFilters());
    expect(bare.nodes.some((n) => n.kind === "satellite")).toBe(false);
    expect(bare.edges.some((e) => e.kind === "anchor")).toBe(false);
  });

  it("matches every word of a multi-word query, accent-insensitive", () => {
    const graph = buildAtlasGraph(NOTES, false);
    expect([...applyFilters(graph, { ...defaultFilters(), query: "strategie REDIS" }).matches]).toEqual(["new"]);
    expect([...applyFilters(graph, { ...defaultFilters(), query: "dec-0002" }).matches]).toEqual(["new"]);
    expect(applyFilters(graph, { ...defaultFilters(), query: "redis absent" }).matches.size).toBe(0);
    expect(applyFilters(graph, { ...defaultFilters(), query: "  " }).matches.size).toBe(0);
  });

  it("folds into clusters above the threshold", () => {
    const many = Array.from({ length: ATLAS_CLUSTER_THRESHOLD + 1 }, (_, i) =>
      note(`n${i}`, { note_type: i % 2 === 0 ? "rule" : "lesson", title: i === 7 ? "Aiguille unique" : `Note ${i}` }));
    const graph = buildAtlasGraph(many, true);
    layoutAtlas(graph);
    const view = applyFilters(graph, { ...defaultFilters(), query: "aiguille" });
    expect(graph.truncated).toBe(true);
    expect(view.clusters.map((c) => c.id).sort()).toEqual(["cluster:studio:lesson", "cluster:studio:rule"]);
    expect(view.clusters.reduce((sum, c) => sum + c.count, 0)).toBe(many.length);
    expect(view.nodes.map((n) => n.id)).toEqual(["n7"]);
    expect(view.edges).toEqual([]);
  });
});
