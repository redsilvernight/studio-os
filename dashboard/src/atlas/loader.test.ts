import { describe, expect, it } from "vitest";
import type { StudioClient } from "../api";
import { loadAtlasNotes } from "./loader";

/** Faux client : `pages` successives de `/vault/tree`, requêtes enregistrées. */
function fakeClient(pages: { count: number; next: string | null }[]) {
  const queries: Record<string, unknown>[] = [];
  let index = 0;
  const client = {
    GET: async (_path: string, init: { params: { query: Record<string, unknown> } }) => {
      queries.push(init.params.query);
      const page = pages[index++] ?? { count: 0, next: null };
      const items = Array.from({ length: page.count }, (_, i) => ({ id: `n${index}-${i}` }));
      return { data: { items, next_cursor: page.next }, response: new Response(null, { status: 200 }) };
    },
  } as unknown as StudioClient;
  return { client, queries };
}

describe("loadAtlasNotes", () => {
  it("follows the cursor until the last page", async () => {
    const { client, queries } = fakeClient([{ count: 200, next: "c1" }, { count: 50, next: null }]);
    const result = await loadAtlasNotes(client);
    expect(result.notes).toHaveLength(250);
    expect(result.truncated).toBe(false);
    expect(queries[0]).toEqual({ limit: 200 });
    expect(queries[1]).toEqual({ limit: 200, cursor: "c1" });
  });

  it("stops at the cap and reports truncation", async () => {
    const { client, queries } = fakeClient([{ count: 200, next: "c1" }, { count: 100, next: "c2" }]);
    const result = await loadAtlasNotes(client, { max: 300, projectId: "p1" });
    expect(result.notes).toHaveLength(300);
    expect(result.truncated).toBe(true);
    expect(queries[1]).toEqual({ project_id: "p1", limit: 100, cursor: "c1" });
  });
});
