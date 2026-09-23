// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { mountGraphViewer, type ViewerData } from "./viewer";
import type { GraphNode } from "../platform/generated/local-contracts.generated";
const node = (i: number, source = "s"): GraphNode => ({
  node_id: `n${i}`,
  kind: i % 2 ? "function" : "file",
  label: `Node ${i}`,
  provenance: {
    source_id: source,
    extractor: "parser",
    confidence: "extracted",
    evidence: "local://proof",
  },
});
const data = (count: number): ViewerData => ({
  nodes: Array.from({ length: count }, (_, i) => node(i)),
  edges: [],
  sources: [
    {
      source_id: "s",
      kind: "code",
      provider_id: "code-provider",
      workspace_id: "w",
      generated_at: "2026-09-21T10:00:00Z",
    },
  ],
  frontier: [],
  partial: false,
});
function setup(
  d: ViewerData,
  options: Parameters<typeof mountGraphViewer>[2] = {},
) {
  const root = document.createElement("div");
  document.body.append(root);
  const viewer = mountGraphViewer(root, d, options);
  return { root, viewer };
}
function click(root: HTMLElement, label: string) {
  const b = [...root.querySelectorAll("button")].find(
    (e) => e.textContent === label,
  );
  expect(b).toBeTruthy();
  b!.click();
}
afterEach(() => document.body.replaceChildren());
describe("common graph viewer", () => {
  it("centers a selected node outside the drawing without exceeding the cap", () => {
    const { root } = setup(data(300));
    for (let i = 0; i < 3; i++) click(root, "Résultats suivants");
    root.querySelector<HTMLButtonElement>(".graph-results button")!.click();
    expect(root.querySelector("aside h3")!.textContent).toBe("Node 90");
    expect(
      [...root.querySelectorAll(".graph-node")].some(
        (n) => n.getAttribute("data-node-key") === '["s","n90"]',
      ),
    ).toBe(false);
    click(root, "Centrer la sélection");
    const selected = root.querySelector(".graph-node.is-selected")!;
    expect(selected.getAttribute("data-node-key")).toBe('["s","n90"]');
    expect(root.querySelectorAll(".graph-node")).toHaveLength(80);
    const position = selected
      .getAttribute("transform")!
      .match(/translate\(([^ ]+) ([^)]+)\)/)!;
    expect(root.querySelector("svg > g")!.getAttribute("transform")).toBe(
      `translate(${450 - Number(position[1])} ${300 - Number(position[2])}) scale(1)`,
    );
    expect(document.activeElement).toBe(root.querySelector("svg"));
  });
  it("retains keyboard focus through result and frontier pagination", () => {
    const d = data(95);
    d.frontier = Array.from({ length: 35 }, (_, i) => ({
      source_id: "s",
      node_id: `missing${i}`,
    }));
    const { root } = setup(d);
    const find = (label: string) =>
      [...root.querySelectorAll("button")].find(
        (b) => b.textContent === label,
      )!;
    find("Résultats suivants").focus();
    click(root, "Résultats suivants");
    expect(document.activeElement?.textContent).toBe("Résultats suivants");
    click(root, "Résultats suivants");
    click(root, "Résultats suivants");
    expect(document.activeElement?.textContent).toBe("Résultats précédents");
    find("Références suivantes").focus();
    click(root, "Références suivantes");
    expect(document.activeElement?.textContent).toBe("Références précédentes");
  });
  it("handles empty and partial data and disposes", () => {
    const { root, viewer } = setup({ ...data(0), partial: true });
    expect(root.textContent).toContain("Aucun nœud");
    expect(root.textContent).toContain("Vue partielle");
    viewer.dispose();
    expect(root.children.length).toBe(0);
    viewer.update(data(2));
    expect(root.children.length).toBe(0);
  });
  it("shows source and provenance safely, selecting without rebuilding the drawing", () => {
    const d = data(2);
    d.nodes[0]!.label = "<img src=x onerror=alert(1)>";
    d.nodes[0]!.uri = "javascript:alert(1)";
    d.edges = [
      {
        edge_id: "e",
        kind: "calls",
        source: { source_id: "s", node_id: "n0" },
        target: { source_id: "s", node_id: "n1" },
        provenance: d.nodes[0]!.provenance,
      },
    ];
    const { root } = setup(d),
      canvas = root.querySelector("svg"),
      first = root.querySelector(".graph-node");
    root.querySelector<HTMLButtonElement>(".graph-results button")!.click();
    expect(root.querySelector("svg")).toBe(canvas);
    expect(root.querySelector(".graph-node")).toBe(first);
    const details = root.querySelector("aside")!;
    expect(details.textContent).toContain("code-provider");
    expect(details.textContent).toContain("2026-09-21");
    expect(details.textContent).toContain("extracted");
    expect(details.textContent).toContain("local://proof");
    expect(details.textContent).toContain("javascript:alert(1)");
    expect(details.textContent).toContain("calls");
    expect(root.querySelector("img,a,script")).toBeNull();
    expect(root.querySelector("line")!.getAttribute("marker-end")).toContain(
      "graph-arrow",
    );
  });
  it("bounds a 30000-node collection and searches undisplayed nodes with retained focus", () => {
    const { root } = setup(data(30000));
    expect(root.querySelectorAll(".graph-node")).toHaveLength(80);
    expect(root.querySelectorAll(".graph-results button")).toHaveLength(30);
    for (let i = 0; i < 4; i++) click(root, "Afficher plus de nœuds");
    expect(root.querySelectorAll(".graph-node")).toHaveLength(200);
    expect(root.querySelectorAll("*").length).toBeLessThan(1000);
    const input = root.querySelector("input")!;
    input.focus();
    input.value = "Node 29999";
    input.dispatchEvent(new Event("input"));
    expect(document.activeElement).toBe(input);
    expect(root.querySelectorAll(".graph-node")).toHaveLength(1);
    expect(root.textContent).toContain("Node 29999");
    input.value = "no-match";
    input.dispatchEvent(new Event("input"));
    expect(root.textContent).toContain("Aucune correspondance");
  });
  it("filters type and source and paginates search results", () => {
    const d = data(100);
    d.nodes.push(node(100, "other"));
    const { root } = setup(d);
    click(root, "Résultats suivants");
    expect(root.querySelector(".graph-results")!.textContent).toContain(
      "Node 30",
    );
    const type = root.querySelector<HTMLSelectElement>(
      '[aria-label="Type de nœud"]',
    )!;
    type.focus();
    type.value = "function";
    type.dispatchEvent(new Event("change"));
    expect(document.activeElement).toBe(type);
    expect(root.querySelectorAll(".graph-node")).toHaveLength(50);
    type.value = "";
    type.dispatchEvent(new Event("change"));
    const source = root.querySelector<HTMLSelectElement>(
      '[aria-label="Source du nœud"]',
    )!;
    source.value = "other";
    source.dispatchEvent(new Event("change"));
    expect(root.querySelectorAll(".graph-node")).toHaveLength(1);
  });
  it("supports keyboard pan, zoom, reset and node activation", () => {
    const { root } = setup(data(2)),
      canvas = root.querySelector("svg")!,
      scene = canvas.querySelector("g")!;
    canvas.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
    );
    expect(scene.getAttribute("transform")).toContain("translate(30 0)");
    canvas.dispatchEvent(
      new KeyboardEvent("keydown", { key: "+", bubbles: true }),
    );
    expect(scene.getAttribute("transform")).toContain("scale(1.25)");
    canvas.dispatchEvent(
      new KeyboardEvent("keydown", { key: "0", bubbles: true }),
    );
    expect(scene.getAttribute("transform")).toBe("translate(0 0) scale(1)");
    root
      .querySelector(".graph-node")!
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    expect(root.querySelector("aside h3")!.textContent).toBe("Node 0");
  });
  it("caps edges and expands true frontier refs, with errors visible", async () => {
    const d = data(80);
    const r = { source_id: "s", node_id: "missing" };
    d.frontier = [r];
    d.partial = true;
    d.edges = Array.from({ length: 500 }, (_, i) => ({
      edge_id: `e${i}`,
      kind: "calls",
      source: { source_id: "s", node_id: "n0" },
      target: { source_id: "s", node_id: "n1" },
      provenance: d.nodes[0]!.provenance,
    }));
    const expand = vi.fn().mockResolvedValue(undefined),
      more = vi.fn().mockRejectedValue(new Error("offline"));
    const { root } = setup(d, { onExpand: expand, onMore: more });
    expect(root.querySelectorAll("line")).toHaveLength(400);
    click(root, "Charger s / missing");
    expect(expand).toHaveBeenCalledWith(r);
    click(root, "Charger la page suivante");
    await vi.waitFor(() =>
      expect(root.querySelector("[role=alert]")!.textContent).toBe("offline"),
    );
  });
  it("keeps duplicate node ids from separate sources distinct", () => {
    const d = data(1);
    d.nodes.push({ ...node(0, "other"), label: "Other node" });
    const { root } = setup(d);
    expect(
      new Set(
        [...root.querySelectorAll(".graph-node")].map((n) =>
          n.getAttribute("data-node-key"),
        ),
      ).size,
    ).toBe(2);
  });
});
