import { describe, expect, it } from "vitest";
import { parseGraphPage } from "./model";
import { nodeKindsBySource } from "./model";

const modules = import.meta.glob("../../../contracts/local/fixtures/valid/graph.*.json", {
  eager: true,
}) as Record<string, { data: unknown }>;

const pageFixtures = Object.entries(modules).filter(([path]) => !path.includes(".request."));

describe("the canonical provider fixtures feed the viewers", () => {
  it("exposes at least one knowledge and one code page fixture", () => {
    const names = pageFixtures.map(([path]) => path);
    expect(names.some((name) => name.includes("graph.knowledge."))).toBe(true);
    expect(names.some((name) => name.includes("graph.code."))).toBe(true);
    expect(names.some((name) => name.includes("graph.projection."))).toBe(true);
  });

  it.each(pageFixtures.map(([path, module]) => [path.split("/").pop()!, module.data] as const))(
    "%s is a valid page for its source kind",
    (_name, data) => {
      const page = parseGraphPage(structuredClone(data));
      const allowed = nodeKindsBySource[page.source.kind];
      for (const node of page.nodes ?? []) expect(allowed).toContain(node.kind);
      expect(page.counts.nodes).toBe((page.nodes ?? []).length);
      expect(page.counts.edges).toBe((page.edges ?? []).length);
    },
  );
});
