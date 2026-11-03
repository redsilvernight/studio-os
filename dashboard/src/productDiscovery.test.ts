// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import { mountProductDiscovery, productDiscoveryHtml, type ProductDiscovery } from "./productDiscovery";

const result: ProductDiscovery = {
  format: "studio.capabilities/v1", intent: "overview", summary: "Capacités disponibles",
  capabilities: [{ key: "vault", title: "Vault natif", summary: "Connaissances du projet", state: "available", write_allowed: false, example: null, reason: null, prerequisites: [], restrictions: [] }],
  additional_available: 1, next_steps: [],
};

describe("découverte produit", () => {
  it("échappe les textes et explicite les droits", () => {
    const html = productDiscoveryHtml({ ...result, summary: "<script>bad</script>" });
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("Lecture seule");
    expect(html).toContain("Détail");
  });

  it("ne charge rien avant la demande puis permet le détail ciblé", async () => {
    const get = vi.fn(async (_path: string, _options: unknown) => ({ response: new Response(null, { status: 200 }), data: result }));
    const root = document.createElement("main");
    document.body.append(root);
    mountProductDiscovery(root, { GET: get } as unknown as StudioClient);
    expect(get).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>("[data-discovery-intent=overview]")!.click();
    await vi.waitFor(() => expect(root.textContent).toContain("Vault natif"));
    expect(get).toHaveBeenCalledWith("/api/v1/capabilities", { params: { query: { intent: "overview", key: undefined, limit: 6 } } });
    root.querySelector<HTMLButtonElement>("[data-discovery-key=vault]")!.click();
    await vi.waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(get.mock.calls[1]?.[1]).toEqual({ params: { query: { intent: "overview", key: "vault", limit: 6 } } });
    root.remove();
  });
});
