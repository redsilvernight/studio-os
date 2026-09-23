// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { mountGraphPage } from "../views/graphs";
import { createFixtureGraphSource, fixturePages, projectionFixturePage } from "./fixtures";
import { parseGraphPage } from "./model";
import { webPlatform } from "../platform/web";

const active: ReturnType<typeof mountGraphPage>[] = [];
function mount(...args: Parameters<typeof mountGraphPage> extends [HTMLElement, ...infer R] ? R : never) {
  const root = document.createElement("main");
  document.body.append(root);
  const controller = mountGraphPage(root, ...args);
  active.push(controller);
  return { root, ...controller };
}
afterEach(() => {
  active.splice(0).forEach((controller) => controller.dispose());
  document.body.replaceChildren();
});

describe("wave 2 project graph is a projection, never a source", () => {
  it("E: two real sources with no explicit reference stay unconnected", async () => {
    const knowledge = fixturePages("knowledge")[0]!;
    const code = fixturePages("code")[0]!;
    const intraSourceEdges = (knowledge.edges ?? []).length + (code.edges ?? []).length;

    const view = mount("project", {
      sources: [createFixtureGraphSource("knowledge", "small"), createFixtureGraphSource("code", "small")],
    });
    await view.ready;

    expect(view.root.querySelectorAll("line")).toHaveLength(intraSourceEdges);
    expect(view.root.querySelectorAll(".graph-node")).toHaveLength(
      (knowledge.nodes ?? []).length + (code.nodes ?? []).length,
    );
    expect(view.root.textContent).toContain("référence explicite");
  });

  it("F: the declared projection adds exactly one cross-source relation with evidence", async () => {
    const knowledge = fixturePages("knowledge")[0]!;
    const code = fixturePages("code")[0]!;
    const intraSourceEdges = (knowledge.edges ?? []).length + (code.edges ?? []).length;

    const projection = projectionFixturePage();
    expect(projection.source.kind).toBe("projection");
    expect(projection.source.member_sources).toEqual(["knowledge-main", "code-main"]);
    expect(projection.edges).toHaveLength(1);
    const edge = projection.edges![0]!;
    expect(edge.kind).toBe("documents");
    expect(edge.source.source_id).not.toBe(edge.target.source_id);
    expect(edge.provenance.confidence).toBe("declared");
    expect(edge.provenance.evidence).toMatch(/^studio-local:\/\/knowledge\//);

    const view = mount("project", {
      sources: [createFixtureGraphSource("knowledge", "small"), createFixtureGraphSource("code", "small")],
      projectionPages: [projection],
    });
    await view.ready;
    expect(view.root.querySelectorAll("line")).toHaveLength(intraSourceEdges + 1);
  });

  it("refuses a relation that is not an explicit, well-formed cross-source fact", () => {
    const projection = projectionFixturePage();
    const edge = projection.edges![0]!;
    expect(() =>
      parseGraphPage({ ...projection, edges: [{ ...edge, target: { ...edge.target, source_id: "knowledge-main" } }] }),
    ).toThrow();
    expect(() => parseGraphPage({ ...projection, edges: [{ ...edge, kind: "links_to" }] })).toThrow();

    const knowledge = fixturePages("knowledge")[0]!;
    const mislabelled = {
      ...knowledge,
      source: { ...knowledge.source, kind: "projection" as const, member_sources: ["knowledge-main", "code-main"] },
    };
    expect(() => parseGraphPage(mislabelled)).toThrow();
  });
});

describe("wave 2 web stays autonomous", () => {
  it.each(["knowledge", "code", "project"] as const)(
    "J: %s renders a clean desktop-only message with no native attempt",
    async (kind) => {
      const request = vi.fn(webPlatform.request);
      const view = mount(kind, { platform: { ...webPlatform, request } });
      await view.ready;
      expect(view.root.textContent).toContain("Disponible dans Studi’OS Desktop");
      expect(request).not.toHaveBeenCalled();
      expect(view.root.querySelector("svg")).toBeNull();
      expect(document.body.textContent).not.toContain("graphify");
      expect(document.body.textContent).not.toContain("Obsidian");
    },
  );
});
