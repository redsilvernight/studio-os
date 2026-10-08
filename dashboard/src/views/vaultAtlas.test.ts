import { describe, expect, it } from "vitest";
import { applyFilters, buildAtlasGraph, defaultFilters } from "../atlas/model";
import type { VaultNoteSummary } from "../vaultApi";
import { atlasDetailHtml, atlasPageHtml, atlasStatusLine, atlasVisibleListHtml } from "./vaultAtlas";

const STAMP = "2026-10-08T10:00:00Z";
const base = { scope: "studio", project_id: null, readable_id: null, summary: "", tags: [], links: [], anchors: [], version: 1, created_at: STAMP, updated_at: STAMP };
const NOTES = [
  { ...base, id: "a", slug: "a", note_type: "decision", readable_id: "DEC-0002", title: "Cache <Redis>", status: "validated", links: [{ target_note_id: "b", kind: "relates_to" }], anchors: ["task:t1"] },
  { ...base, id: "b", slug: "b", note_type: "rule", title: "Pas de secret", status: "validated" },
] as unknown as VaultNoteSummary[];

describe("vault atlas view", () => {
  const graph = buildAtlasGraph(NOTES, false);

  it("renders the mode switch, an accessible canvas and the keyboard list", () => {
    const html = atlasPageHtml(defaultFilters(), [], null);
    expect(html).toContain('href="#/vault/atlas" aria-current="page"');
    expect(html).toMatch(/<canvas id="atlas-canvas"[^>]*tabindex="0"[^>]*aria-label=/);
    expect(html).toContain('data-atlas-toggle="superseded"');
    expect(html).not.toContain("#/graphs");
  });

  it("escapes titles and lists matches first", () => {
    const view = applyFilters(graph, { ...defaultFilters(), query: "secret" });
    const list = atlasVisibleListHtml(view, null);
    expect(list.indexOf("Pas de secret")).toBeLessThan(list.indexOf("Cache &lt;Redis&gt;"));
    expect(list).not.toContain("<Redis>");
    expect(atlasStatusLine(view, graph)).toContain("1 correspondance");
  });

  it("details a note with neighbors, link kinds and an open link", () => {
    const html = atlasDetailHtml(graph, "a");
    expect(html).toContain("DEC-0002");
    expect(html).toContain('href="#/vault/a"');
    expect(html).toContain("Pas de secret");
    expect(html).toContain("en rapport");
    expect(html).toContain('data-atlas-pick="anchor:task:t1"');
  });

  it("links task satellites to the task page", () => {
    expect(atlasDetailHtml(graph, "anchor:task:t1")).toContain('href="#/tasks/t1"');
    expect(atlasDetailHtml(graph, null)).toContain("sélectionnez");
  });
});
