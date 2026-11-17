// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import type { PickResult, Platform } from "../platform";
import { webPlatform } from "../platform/web";
import { parseRoute } from "../router";
import { shellHtml, shellNavGroups } from "../shell";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import { pickWorkspaceFolder, renderWorkspaces, toFolderOutcome, workspacesPageHtml } from "./workspacesPage";

const flush = async (): Promise<void> => {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
};

function platformPicking(result: PickResult | Error): Platform {
  const base = fakeDesktop();
  return {
    ...base,
    chooseFolder: vi.fn(async () => {
      if (result instanceof Error) throw result;
      return result;
    }),
  } as Platform;
}

describe("P3 x P5 native folder pick", () => {
  it("maps a selection, cancel, unavailable and error to closed outcomes", () => {
    expect(toFolderOutcome({ status: "selected", path: "C:\\Work\\game", display_name: "game" })).toEqual({
      kind: "selected",
      path: "C:\\Work\\game",
      displayName: "game",
    });
    expect(toFolderOutcome({ status: "cancelled" })).toEqual({ kind: "cancelled" });
    expect(toFolderOutcome({ status: "unavailable" })).toEqual({ kind: "unavailable" });
    expect(toFolderOutcome({ status: "error", code: "picker_failed" })).toEqual({ kind: "error", code: "picker_failed" });
  });

  it("never turns an empty selected path into a selection", () => {
    expect(toFolderOutcome({ status: "selected", path: "", display_name: "" }).kind).toBe("error");
  });

  it("a thrown picker is an error outcome, not a crash", async () => {
    expect(await pickWorkspaceFolder(platformPicking(new Error("boom")))).toEqual({ kind: "error", code: "picker_failed" });
  });

  it("the web build has no picker and renders a notice only", async () => {
    const root = document.createElement("div");
    await renderWorkspaces(root, webPlatform);
    expect(root.querySelector('[data-testid="workspaces-web"]')).not.toBeNull();
    expect(root.querySelector("#workspace-add")).toBeNull();
    expect(await pickWorkspaceFolder(webPlatform)).toEqual({ kind: "unavailable" });
  });

  it.each([
    [{ status: "selected", path: "C:\\Work\\game", display_name: "game" } as PickResult, "selected", "Dossier choisi : game"],
    [{ status: "cancelled" } as PickResult, "cancelled", "Sélection annulée"],
    [{ status: "error", code: "x" } as PickResult, "error", "n'a pas pu être sélectionné"],
  ])("desktop click shows the %#th outcome honestly", async (result, kind, text) => {
    const root = document.createElement("div");
    await renderWorkspaces(root, platformPicking(result));
    root.querySelector<HTMLButtonElement>("#workspace-add")?.click();
    await flush();
    const out = root.querySelector('[data-testid="workspaces-outcome"]');
    expect(out?.getAttribute("data-outcome")).toBe(kind);
    expect(out?.textContent).toContain(text);
  });

  it("a selection never claims the association is done and never shows the raw path", () => {
    const html = workspacesPageHtml("desktop", { kind: "selected", path: "C:\\Secret\\dir", displayName: "dir" });
    expect(html).toContain("Confirmez son association");
    expect(html).not.toContain("C:\\Secret");
  });
});

describe("Espaces de travail navigation", () => {
  it("routes #/workspaces", () => {
    expect(parseRoute("#/workspaces")).toEqual({ name: "workspaces" });
    expect(parseRoute("#/workspaces/x").name).toBe("notFound");
  });

  it("is visible on web and desktop: one Administration entry", () => {
    const web = shellNavGroups({ name: "dashboard" }).flatMap((g) => g.items.map((i) => i.href));
    expect(web).toContain("#/workspaces");
    expect(shellHtml({ name: "dashboard" }, true)).toContain("Espaces de travail");
    const desktop = shellNavGroups({ name: "workspaces" }, true).flatMap((g) => g.items);
    expect(desktop.filter((i) => i.href === "#/workspaces" && i.active)).toHaveLength(1);
    expect(shellHtml({ name: "dashboard" }, true, true)).toContain("Espaces de travail");
  });

  it("titles the page Espaces de travail with a folded technical block", () => {
    expect(workspacesPageHtml("desktop", null)).toContain("Espaces de travail");
    expect(workspacesPageHtml("desktop", null)).toContain("Administration / Espaces de travail");
    expect(workspacesPageHtml("desktop", null)).toContain("Détails techniques");
    expect(workspacesPageHtml("web", null)).toContain("Studi'OS Desktop");
  });

  it("mounts the per-folder setup (memory, environment, harness) when configuring a folder", async () => {
    const ws = "11111111-1111-4111-8111-111111111111";
    const at = "2026-09-22T10:00:00Z";
    const config = {
      schema_version: 1,
      workspace_id: ws,
      profile: { profile_id: "main", server_origin: "https://studio.example" },
      project_id: "22222222-2222-4222-8222-222222222222",
      project_slug: "mon-jeu",
      roots: { workspace_root: "C:\\Work\\game", repo_roots: [] },
      features: {},
      created_at: at,
      updated_at: at,
    };
    const base = fakeDesktop({
      request: (async (command: string) => {
        if (command === "workspace.list") return { ok: true, response: { payload: { items: [{ workspace_id: ws, health: "valid", action: "none", config }] } } };
        if (command === "identity.get_view") {
          return { ok: true, response: { payload: { profile: config.profile, machine: { machine_name: "PC Bureau" }, secrets: [{ status: "present" }] } } };
        }
        if (command === "knowledge.status") return { ok: true, response: { payload: { workspace_id: ws, state: "disabled" } } };
        if (command === "workspace.git_status") return { ok: true, response: { payload: { state: "valid" } } };
        if (command === "code_graph.status") return { ok: true, response: { payload: { workspace_id: ws, state: "disabled" } } };
        if (command === "harness.detect") return { ok: true, response: { payload: { harnesses: [] } } };
        return { ok: false, error: { code: "not_supported" } };
      }) as never,
    });
    const ctx = {
      authed: true,
      client: { GET: async () => ({ response: { ok: true }, data: [{ id: config.project_id, name: "Mon jeu", slug: "mon-jeu" }] }) },
    } as never;
    const root = document.createElement("div");
    await renderWorkspaces(root, base, ctx);
    root.querySelector<HTMLButtonElement>("[data-workspace-edit]")!.click();
    await flush();
    // Minimal branch: the dedicated folder-setup module is mounted in place.
    expect(root.querySelector("[data-folder-setup]")).not.toBeNull();
    for (let i = 0; i < 20 && !root.querySelector('[data-testid="folder-setup"]'); i += 1) {
      await flush();
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    expect(root.querySelector('[data-testid="folder-setup-memory"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="folder-setup-environment"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="folder-setup-harness"]')).not.toBeNull();
  });
});
