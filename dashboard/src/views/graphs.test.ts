// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { mountGraphPage } from "./graphs";
import { createFixtureGraphSource, fixturePages } from "../graphs/fixtures";
import { webPlatform } from "../platform/web";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import type { ComponentState } from "../platform/generated/local-contracts.generated";
import { parseRoute } from "../router";
import { INITIAL_ONBOARDING_STATE, ONBOARDING_STORAGE_KEY } from "../onboarding/state";

const active: ReturnType<typeof mountGraphPage>[] = [];
function mount(...args: Parameters<typeof mountGraphPage> extends [HTMLElement, ...infer R] ? R : never) {
  const root = document.createElement("main"); document.body.append(root);
  const controller = mountGraphPage(root, ...args); active.push(controller);
  return { root, ...controller };
}
afterEach(() => { active.splice(0).forEach((controller) => controller.dispose()); document.body.replaceChildren(); });

describe("graph pages", () => {
  it("offers explicit source unavailable in web and no workspace in Desktop", async () => {
    const request = vi.fn(webPlatform.request);
    const web = mount("knowledge", { platform: { ...webPlatform, request } }); await web.ready;
    expect(web.root.textContent).toContain("Disponible dans Studi’OS Desktop");
    expect(request).not.toHaveBeenCalled();
    const desktop = mount("code", { platform: fakeDesktop() }); await desktop.ready;
    expect(desktop.root.textContent).toContain("Aucun dossier actif");
    expect(desktop.root.querySelector("svg")).toBeNull();
  });
  it("falls back to the workspace remembered by onboarding in Desktop", async () => {
    const id = "11111111-1111-4111-8111-111111111111";
    localStorage.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({ ...INITIAL_ONBOARDING_STATE, workspaceId: id }));
    try {
      const view = mount("knowledge", { platform: fakeDesktop() }); await view.ready;
      expect(view.root.textContent).not.toContain("Aucun dossier actif");
      expect(view.root.querySelector<HTMLAnchorElement>('a[href^="#/graphs/code"]')?.getAttribute("href")).toBe(`#/graphs/code/${id}`);
    } finally { localStorage.removeItem(ONBOARDING_STORAGE_KEY); }
  });
  it.each(["ready", "stale", "indexing", "error", "unavailable", "permission_denied", "disabled", "not_installed", "incompatible"] as ComponentState[])("displays %s explicitly", async (state) => {
    const source = createFixtureGraphSource("knowledge", "small", state);
    const page = vi.spyOn(source, "page");
    const view = mount("knowledge", { sources: [source] }); await view.ready;
    expect(view.root.querySelector(`[data-state="${state}"]`)).not.toBeNull();
    if (state === "ready" || state === "stale") expect(page).toHaveBeenCalledOnce();
    else expect(page).not.toHaveBeenCalled();
  });
  it("shows loading then rejects stale completions on source switch", async () => {
    let finish!: (value: { state: "ready" }) => void;
    const source = createFixtureGraphSource("knowledge", "small");
    source.status = () => new Promise((resolve) => { finish = resolve; });
    const view = mount("knowledge", { sources: [source] });
    expect(view.root.textContent).toContain("Chargement du graphe");
    const select = view.root.querySelector<HTMLSelectElement>("[data-graph-demo]")!;
    select.value = "empty"; select.dispatchEvent(new Event("change"));
    await vi.waitFor(() => expect(view.root.textContent).toContain("Aucun nœud"));
    finish({ state: "ready" }); await view.ready;
    expect(view.root.querySelectorAll(".graph-node")).toHaveLength(0);
  });
  it("project displays only supplied cross-source edges and tolerates an unavailable member", async () => {
    const view = mount("project", { sources: [createFixtureGraphSource("knowledge", "small"), createFixtureGraphSource("code", "small")], projectionPages: [fixturePages("project")[2]!] });
    await view.ready;
    expect(view.root.querySelectorAll(".graph-node")).toHaveLength(8);
    expect(view.root.querySelectorAll("line")).toHaveLength(8);
    const degraded = mount("project", { sources: [createFixtureGraphSource("knowledge", "small"), createFixtureGraphSource("code", "small", "unavailable")] });
    await degraded.ready;
    expect(degraded.root.querySelectorAll(".graph-node")).toHaveLength(4);
    expect(degraded.root.textContent).toContain("Source indisponible");
  });
  it("source search retrieves an unloaded node from 30k and expands it", async () => {
    const source = createFixtureGraphSource("code", "large");
    const search = vi.spyOn(source, "search");
    const view = mount("code", { sources: [source] }); await view.ready;
    const form = view.root.querySelector<HTMLFormElement>("[data-source-search]")!;
    form.querySelector<HTMLInputElement>("input")!.value = "29999";
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(view.root.querySelector("[data-source-results]")!.textContent).toContain("29999"));
    expect(search).toHaveBeenCalledWith("29999", undefined);
    view.root.querySelector<HTMLButtonElement>("[data-source-results] button")!.click();
    await vi.waitFor(() => expect(view.root.querySelector(".graph-viewer")!.textContent).toContain("101 en mémoire"));
    expect(view.root.querySelectorAll(".graph-node").length).toBeLessThanOrEqual(80);
  });
  it("escapes search labels, error messages and treats URI as non-navigable text", async () => {
    const source = createFixtureGraphSource("knowledge", "small");
    source.search = async () => ({ hits: [{ label: "<script>alert(1)</script>", uri: "javascript:alert(1)" }], partial: true, nextCursor: null });
    const view = mount("knowledge", { sources: [source] }); await view.ready;
    const form = view.root.querySelector<HTMLFormElement>("form")!;
    form.querySelector<HTMLInputElement>("input")!.value = "malicious";
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(view.root.querySelector("[data-source-results]")!.textContent).toContain("<script>"));
    expect(view.root.querySelector("[data-source-results] script, [data-source-results] a")).toBeNull();
    source.status = async () => { throw new Error("<img src=x onerror=alert(1)>"); };
    view.root.querySelector<HTMLButtonElement>("[data-reload]")!.click();
    await vi.waitFor(() => expect(view.root.querySelector("[data-state=error]")!.textContent).toContain("<img"));
    expect(view.root.querySelector("img")).toBeNull();
  });
  it("routes only supported views and validated workspace ids", () => {
    expect(parseRoute("#/graphs/code")).toEqual({ name: "graphs", kind: "code" });
    expect(parseRoute("#/graphs/project/11111111-1111-4111-8111-111111111111")).toEqual({ name: "graphs", kind: "project", workspaceId: "11111111-1111-4111-8111-111111111111" });
    for (const hash of ["#/graphs/vault", "#/graphs/code/file:///etc", "#/graphs/code/javascript:alert(1)"]) expect(parseRoute(hash).name).toBe("notFound");
  });
});
