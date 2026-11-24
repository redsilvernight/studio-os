// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Platform } from "../platform";
import { webPlatform } from "../platform/web";
import { parseRoute } from "../router";
import { shellHtml, shellNavGroups } from "../shell";
import type { StudioClient } from "../api";
import { clearToken, setToken } from "../auth";
import { resetIdentityCache } from "../identityApi";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import {
  canLinkDetected,
  detectedReasonLabel,
  detectedSectionHtml,
  pickWorkspaceFolder,
  renderWorkspaces,
  toFolderOutcome,
  workspacesPageHtml,
  type PageState,
} from "./workspacesPage";

const flush = async (ticks = 40): Promise<void> => {
  for (let i = 0; i < ticks; i += 1) await Promise.resolve();
};

afterEach(() => {
  clearToken();
  resetIdentityCache();
});

const PROJECT = { id: "22222222-2222-4222-8222-222222222222", name: "Mon jeu", slug: "mon-jeu", archived: false };
const PROFILE = { profile_id: "default", server_origin: "https://studio.example.test" };
const DETECTED_ROOT = "C:/Projects/untracked-game";

function pageState(over: Partial<PageState> = {}): PageState {
  return {
    items: [],
    detected: [],
    projects: [],
    identity: null,
    role: null,
    outcome: null,
    selectedProject: "",
    error: "",
    notice: "",
    busy: false,
    linking: null,
    editing: null,
    ...over,
  };
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
    const base = fakeDesktop();
    const platform = { ...base, chooseFolder: vi.fn(async () => { throw new Error("boom"); }) } as Platform;
    expect(await pickWorkspaceFolder(platform)).toEqual({ kind: "error", code: "picker_failed" });
  });

  it("the web build has no picker and renders a notice only", async () => {
    const root = document.createElement("div");
    await renderWorkspaces(root, webPlatform);
    expect(root.querySelector('[data-testid="workspaces-web"]')).not.toBeNull();
    expect(root.querySelector("#workspace-add")).toBeNull();
    expect(root.querySelector('[data-testid="detected-repos"]')).toBeNull();
    expect(await pickWorkspaceFolder(webPlatform)).toEqual({ kind: "unavailable" });
  });

  it("a selection never claims the association is done and never shows the raw path", () => {
    const html = workspacesPageHtml("desktop", { kind: "selected", path: "C:\\Secret\\dir", displayName: "dir" }, pageState());
    expect(html).toContain("Confirmez son association");
    expect(html).not.toContain("C:\\Secret");
  });
});

describe("P3-detected section", () => {
  const entry = {
    root: DETECTED_ROOT,
    remotes: ["github.com/org/untracked-game"],
    reason: "not_found",
    last_seen_at: "2026-11-10T09:00:00+00:00",
  };

  it("shows the folder name, the normalized remote and the reason, never the raw path", () => {
    const html = detectedSectionHtml(pageState({ detected: [entry], projects: [PROJECT], selectedProject: PROJECT.id, role: "admin" }), null);
    expect(html).toContain("Dépôts détectés non suivis");
    expect(html).toContain("untracked-game");
    expect(html).toContain("github.com/org/untracked-game");
    expect(html).not.toContain(DETECTED_ROOT);
  });

  it("offers Lier to admin and developer, manual link without remote, nothing to viewer", () => {
    const admin = detectedSectionHtml(pageState({ detected: [entry], projects: [PROJECT], selectedProject: PROJECT.id, role: "admin" }), null);
    expect(admin).toContain("Lier à un projet");
    const developer = detectedSectionHtml(pageState({ detected: [entry], projects: [PROJECT], selectedProject: PROJECT.id, role: "developer" }), null);
    expect(developer).toContain("Lier à un projet");
    const remoteLess = detectedSectionHtml(pageState({ detected: [{ ...entry, remotes: [] }], projects: [PROJECT], selectedProject: PROJECT.id, role: "developer" }), null);
    expect(remoteLess).toContain("Lier manuellement");
    const viewer = detectedSectionHtml(pageState({ detected: [entry], projects: [PROJECT], selectedProject: PROJECT.id, role: "viewer" }), null);
    expect(viewer).not.toContain("data-detected-link");
    expect(viewer).toContain("Demander l'accès");
  });

  it("is empty with an explicit message and asks to connect without projects", () => {
    expect(detectedSectionHtml(pageState({ role: "admin" }), null)).toContain("Aucun dépôt détecté non suivi");
    expect(detectedSectionHtml(pageState({ role: null }), null)).toContain("Connectez-vous");
  });

  it("gates the gesture on admin/developer roles only", () => {
    expect(canLinkDetected("admin")).toBe(true);
    expect(canLinkDetected("developer")).toBe(true);
    expect(canLinkDetected("viewer")).toBe(false);
    expect(canLinkDetected("agent")).toBe(false);
    expect(canLinkDetected(null)).toBe(false);
  });

  it("labels known detection reasons in French", () => {
    expect(detectedReasonLabel("not_found")).toContain("inconnu");
    expect(detectedReasonLabel("ambiguous")).toContain("plusieurs projets");
    expect(detectedReasonLabel("anything-else")).toBe("Dépôt non suivi");
  });
});

describe("P3-detected link journey", () => {
  function harness(role: string, postRepositories?: (path: string, body: unknown) => { ok: boolean; status: number }) {
    setToken("e2e-token");
    const saved: Array<{ workspace_id: string; config: Record<string, unknown> }> = [];
    let detected: Array<{ root: string; remotes: string[]; reason: string; last_seen_at: string }> = [
      { root: DETECTED_ROOT, remotes: ["github.com/org/untracked-game"], reason: "not_found", last_seen_at: "2026-11-10T09:00:00+00:00" },
    ];
    const posts: Array<{ path: string; body: unknown }> = [];
    const bridge: string[] = [];
    const answer = (payload: unknown): unknown => ({ ok: true, response: { payload } });
    const base = fakeDesktop();
    const platform = {
      ...base,
      request: vi.fn(async (command: string, payload: Record<string, unknown>) => {
        bridge.push(command);
        if (command === "identity.get_view") return answer({ profile: PROFILE, machine: { machine_name: "poste-e2e" } });
        if (command === "workspace.list") {
          return answer({
            items: saved.map((entry) => ({ workspace_id: entry.workspace_id, health: "valid", action: "none", config: entry.config })),
          });
        }
        if (command === "workspace.list_detected") return answer({ items: detected });
        if (command === "workspace.confirm_roots") return answer({ root_confirmation_id: "rc-e2e", expires_in_s: 600 });
        if (command === "workspace.save_config") {
          const config = (payload as { config: Record<string, unknown> }).config;
          saved.push({ workspace_id: config["workspace_id"] as string, config });
          detected = detected.filter((item) => item.root !== (config["roots"] as { workspace_root: string }).workspace_root);
          return answer(config);
        }
        throw new Error(`unexpected bridge command ${command}`);
      }),
    } as unknown as Platform;
    const GET = vi.fn(async (path: string) => {
      if (path === "/api/v1/auth/me") {
        return { data: { user_id: "u1", display_name: "Op", email: "op@example.test", role, machine_id: "m1" }, response: { ok: true, status: 200 } };
      }
      if (path === "/api/v1/projects") return { data: [PROJECT], response: { ok: true, status: 200 } };
      throw new Error(`unexpected GET ${path}`);
    });
    const POST = vi.fn(async (path: string, options: { params: { path: { project_id: string } }; body: unknown }) => {
      posts.push({ path, body: options.body });
      if (postRepositories) {
        const outcome = postRepositories(path, options.body);
        return { data: outcome.ok ? {} : { detail: "refused" }, response: { ok: outcome.ok, status: outcome.status } };
      }
      return { data: {}, response: { ok: true, status: 201 } };
    });
    const client = { GET, POST } as unknown as StudioClient;
    return { platform, client, saved, posts, bridge, get detected() { return detected; } };
  }

  it("Lier rattache le dépôt au projet choisi : remote ajouté, dossier suivi, liste à jour", async () => {
    const h = harness("developer");
    const root = document.createElement("div");
    await renderWorkspaces(root, h.platform, { client: h.client, authed: true });
    await flush();
    const button = root.querySelector<HTMLButtonElement>("[data-detected-link]");
    expect(button).not.toBeNull();
    button?.click();
    await flush();
    expect(h.posts).toHaveLength(1);
    expect(h.posts[0]).toEqual({ path: "/api/v1/projects/{project_id}/repositories", body: { url: "github.com/org/untracked-game" } });
    expect(h.bridge).toContain("workspace.confirm_roots");
    expect(h.bridge).toContain("workspace.save_config");
    expect(h.saved).toHaveLength(1);
    expect(root.textContent).toContain("Dépôt lié au projet");
    expect(root.querySelector('[data-testid="detected-repos"]')?.textContent).toContain("Aucun dépôt détecté non suivi");
    expect(root.textContent).toContain("untracked-game");
  });

  it("a viewer never sees the link action, only the access request help", async () => {
    const h = harness("viewer");
    const root = document.createElement("div");
    await renderWorkspaces(root, h.platform, { client: h.client, authed: true });
    await flush();
    expect(root.querySelector("[data-detected-link]")).toBeNull();
    expect(root.querySelector('[data-testid="detected-repos"]')?.textContent).toContain("Demander l'accès");
    expect(h.posts).toHaveLength(0);
  });

  it("a conflicting remote reports honestly and tracks nothing", async () => {
    const h = harness("admin", () => ({ ok: false, status: 409 }));
    const root = document.createElement("div");
    await renderWorkspaces(root, h.platform, { client: h.client, authed: true });
    await flush();
    root.querySelector<HTMLButtonElement>("[data-detected-link]")?.click();
    await flush();
    expect(h.saved).toHaveLength(0);
    expect(root.textContent).toContain("déjà rattaché à un autre projet");
  });
});

describe("Dossiers du projet navigation", () => {
  it("routes #/workspaces", () => {
    expect(parseRoute("#/workspaces")).toEqual({ name: "workspaces" });
    expect(parseRoute("#/workspaces/x").name).toBe("notFound");
  });

  it("keeps legacy pages reachable with the closest Studio entry active", () => {
    const web = shellNavGroups({ name: "dashboard" }).flatMap((g) => g.items.map((i) => i.href));
    expect(web).toContain("#/administration");
    expect(shellHtml({ name: "dashboard" }, true)).toContain("Réglages");
    const desktop = shellNavGroups({ name: "workspaces" }, true).flatMap((g) => g.items);
    expect(desktop.filter((i) => i.href === "#/administration" && i.active)).toHaveLength(1);
    expect(shellHtml({ name: "dashboard" }, true, true)).toContain("Réglages");
  });

  it("titles the page Dossiers du projet with a folded technical block", () => {
    expect(workspacesPageHtml("desktop", null)).toContain("Dossiers du projet");
    expect(workspacesPageHtml("desktop", null)).toContain("Réglages / Dossiers du projet");
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
