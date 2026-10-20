import { describe, expect, it } from "vitest";
import { applyFilters, buildAtlasGraph, defaultFilters, layoutAtlas } from "../atlas/model";
import type { VaultNoteSummary } from "../vaultApi";
import {
  ATLAS_MODE_STORAGE_KEY,
  atlasDetailHtml,
  atlasPageHtml,
  atlasPerfText,
  atlasRegionsHtml,
  atlasStatusLine,
  atlasVisibleListHtml,
  readAtlasMode,
  toggleAtlasMode,
  writeAtlasMode,
} from "./vaultAtlas";

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

  it("exposes zones, communities and neighbour emphasis", () => {
    layoutAtlas(graph);
    const view = applyFilters(graph, { ...defaultFilters(), showSatellites: true });
    expect(view.groups.length).toBeGreaterThan(0);
    expect(view.communities).toHaveLength(1);
    expect(view.communities[0]?.members.sort()).toEqual(["a", "b"]);
    const status = atlasStatusLine(view, graph, "a");
    expect(status).toContain("zone(s)");
    expect(status).toContain("communauté(s)");
    expect(status).toContain("voisin(s) surligné(s)");
    const list = atlasVisibleListHtml(view, "a", graph);
    expect(list).toContain("is-neighbor");
    expect(list).toContain("voisin");
    const regions = atlasRegionsHtml(view);
    expect(regions).toContain("Zones (");
    expect(regions).toContain("Communautés (1)");
    expect(regions).toContain("Studio ·");
    expect(regions).toContain("Communauté 1");
    expect(regions).toContain("data-zone-color=");
    expect(regions).toContain("data-community-color=");
    expect(regions).toContain('data-atlas-pick="a"');
  });

  it("switches 2D/3D in markup and hint text", () => {
    const flat = atlasPageHtml(defaultFilters(), [], null, "2d");
    expect(flat).toContain('data-atlas-mode="2d"');
    expect(flat).toContain("Vue 2D");
    expect(flat).toContain('aria-pressed="true"');
    expect(flat).not.toContain("pivoter");
    expect(atlasPageHtml(defaultFilters(), [], null, "3d")).toContain("pivoter");
  });
});

describe("atlas projection persistence and performance", () => {
  const makeStorage = (): Storage => {
    const data = new Map<string, string>();
    return {
      get length() {
        return data.size;
      },
      clear: () => data.clear(),
      getItem: (key: string) => data.get(key) ?? null,
      key: (index: number) => [...data.keys()][index] ?? null,
      removeItem: (key: string) => void data.delete(key),
      setItem: (key: string, value: string) => void data.set(key, value),
    };
  };

  it("persists the mode across renders and defaults to 3D", () => {
    const storage = makeStorage();
    expect(readAtlasMode(storage)).toBe("3d");
    writeAtlasMode("2d", storage);
    expect(storage.getItem(ATLAS_MODE_STORAGE_KEY)).toBe("2d");
    expect(readAtlasMode(storage)).toBe("2d");
    expect(toggleAtlasMode("2d")).toBe("3d");
    expect(toggleAtlasMode("3d")).toBe("2d");
  });

  it("tolerates a throwing storage", () => {
    const hostile = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    } as unknown as Storage;
    expect(readAtlasMode(hostile)).toBe("3d");
    expect(() => writeAtlasMode("2d", hostile)).not.toThrow();
  });

  it("formats the render timing for the dev status line", () => {
    const text = atlasPerfText(2000, 3200, { buildMs: 12.3, layoutMs: 45.6, filterMs: 1.2, drawMs: 8.9 });
    expect(text).toContain("2000 note(s)");
    expect(text).toContain("construction 12.3 ms");
    expect(text).toContain("disposition 45.6 ms");
    expect(text).toContain("dessin 8.9 ms");
  });
});
