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
    expect(toFolderOutcome({ status: "selected", path: "C:\Work\game", display_name: "game" })).toEqual({
      kind: "selected",
      path: "C:\Work\game",
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
    [{ status: "selected", path: "C:\Work\game", display_name: "game" } as PickResult, "selected", "Dossier choisi : game"],
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
    const html = workspacesPageHtml("desktop", { kind: "selected", path: "C:\Secret\dir", displayName: "dir" });
    expect(html).toContain("pas encore disponible");
    expect(html).not.toContain("C:\Secret");
  });
});

describe("Dossiers navigation", () => {
  it("routes #/workspaces", () => {
    expect(parseRoute("#/workspaces")).toEqual({ name: "workspaces" });
    expect(parseRoute("#/workspaces/x").name).toBe("notFound");
  });

  it("is desktop-only: the web navigation is unchanged", () => {
    const web = shellNavGroups({ name: "dashboard" }).flatMap((g) => g.items.map((i) => i.href));
    expect(web).not.toContain("#/workspaces");
    expect(shellHtml({ name: "dashboard" }, true)).not.toContain("Dossiers");
    const desktop = shellNavGroups({ name: "workspaces" }, true).flatMap((g) => g.items);
    expect(desktop.filter((i) => i.href === "#/workspaces" && i.active)).toHaveLength(1);
    expect(shellHtml({ name: "dashboard" }, true, true)).toContain("Dossiers");
  });
});
