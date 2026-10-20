// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import { fetchAgentProjects } from "../agentsApi";
import { listLibraryResources } from "../libraryApi";
import { postResolution } from "../resolutionApi";
import { uiState } from "../store";
import { renderInspector } from "./inspector";

vi.mock("../agentsApi", () => ({ fetchAgentProjects: vi.fn() }));
vi.mock("../libraryApi", () => ({ listLibraryResources: vi.fn() }));
vi.mock("../resolutionApi", async (original) => ({
  ...await original<typeof import("../resolutionApi")>(), postResolution: vi.fn(),
}));

const projects = [{ id: "p1", name: "Studio" }, { id: "p2", name: "Second projet" }];
const ctx = { client: {} as StudioClient, authed: true, stableKey: null };
let root: HTMLDivElement;

beforeEach(() => {
  vi.clearAllMocks();
  uiState.selectedProjectId = "p2";
  root = document.createElement("div");
  document.body.append(root);
  vi.mocked(fetchAgentProjects).mockResolvedValue(projects as Awaited<ReturnType<typeof fetchAgentProjects>>);
  vi.mocked(listLibraryResources).mockResolvedValue([]);
  vi.mocked(postResolution).mockRejectedValue(new Error("Resolution unavailable"));
});

afterEach(() => { root.remove(); uiState.selectedProjectId = null; });

describe("Inspector project selection", () => {
  it("shows project loading before rendering authorized project names", async () => {
    let finish!: (value: Awaited<ReturnType<typeof fetchAgentProjects>>) => void;
    vi.mocked(fetchAgentProjects).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const rendering = renderInspector(root, ctx);
    expect(root.textContent).toContain("Chargement en cours");
    finish(projects as Awaited<ReturnType<typeof fetchAgentProjects>>);
    await rendering;
    const select = root.querySelector<HTMLSelectElement>('[name="project_id"]')!;
    expect(select.value).toBe("p2");
    expect(select.selectedOptions[0]!.textContent).toBe("Second projet");
    expect(root.querySelector('input[name="project_id"]')).toBeNull();
  });

  it("submits the selected internal id without asking the user for an UUID", async () => {
    await renderInspector(root, ctx);
    root.querySelector<HTMLInputElement>('[name="stable_key"]')!.value = "review-helper";
    root.querySelector<HTMLSelectElement>('[name="project_id"]')!.value = "p1";
    root.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(postResolution).toHaveBeenCalledWith(ctx.client, expect.objectContaining({ project_id: "p1", stable_key: "review-helper" })));
  });

  it("handles no accessible projects and does not preserve a stale project id", async () => {
    vi.mocked(fetchAgentProjects).mockResolvedValue([]);
    await renderInspector(root, ctx);
    expect(root.textContent).toContain("Aucun projet accessible");
    expect(root.querySelector<HTMLSelectElement>('[name="project_id"]')!.value).toBe("");
  });

  it("shows project access errors, retries, and does not auto-inspect a wrong context", async () => {
    vi.mocked(fetchAgentProjects).mockRejectedValueOnce(new Error("Access denied"));
    await renderInspector(root, { ...ctx, stableKey: "review-helper" });
    expect(root.querySelector('[role="alert"]')!.textContent).toContain("Impossible de charger les projets");
    expect(postResolution).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>("[data-projects-retry]")!.click();
    await vi.waitFor(() => expect(root.querySelector<HTMLSelectElement>('[name="project_id"]')?.value).toBe("p2"));
    expect(fetchAgentProjects).toHaveBeenCalledTimes(2);
  });
});
