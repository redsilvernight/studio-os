// @vitest-environment happy-dom
/**
 * Réactivité des boutons de l'assistant : verrou anti double clic, erreur
 * affichée, relance après échec et reprise après redémarrage de l'app.
 * Le sélecteur de dossier natif n'est jamais ouvert : le dossier choisi est
 * injecté dans la session, comme le ferait `pickWorkspaceFolder`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BridgeAnswer } from "../platform/contracts";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import { ApiError } from "../api";
import { setToken } from "../auth";
import { ONBOARDING_STORAGE_KEY, saveOnboardingState } from "./state";
import { emptySession, projectSlugFromName, renderOnboarding, revalidate } from "./view";

const api = vi.hoisted(() => ({
  GET: vi.fn(),
  createProject: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, createApiClient: () => ({ GET: api.GET }) };
});

vi.mock("../creationsApi", async (importOriginal) => {
  const original = await importOriginal<typeof import("../creationsApi")>();
  return { ...original, createProject: api.createProject };
});

const WS = "11111111-1111-4111-8111-111111111111";
const PROJECT = "22222222-2222-4222-8222-222222222222";

const ok = (payload: unknown): BridgeAnswer => ({ ok: true, response: { payload } }) as unknown as BridgeAnswer;
const refused = (code: string): BridgeAnswer =>
  ({ ok: false, error: { code, component: "workspace", message: "x", retryable: false, correlation_id: null, details: {} } }) as unknown as BridgeAnswer;

const tick = (ms = 0): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function mount(): HTMLElement {
  const root = document.createElement("main");
  document.body.append(root);
  return root;
}

function apiError(status: number): ApiError {
  return new ApiError({ status, message: "x", errorCode: null, serverVersion: null } as never);
}

beforeEach(() => {
  document.body.innerHTML = "";
  globalThis.localStorage.removeItem(ONBOARDING_STORAGE_KEY);
  api.GET.mockReset();
  api.createProject.mockReset();
  setToken("session-token");
});

afterEach(() => {
  setToken("");
});

describe("projectSlugFromName", () => {
  it.each([
    ["Mon Jeu Phare", "mon-jeu-phare"],
    ["Élan d'été 2", "elan-d-ete-2"],
    ["2049", "projet-2049"],
    ["  --Studio--  ", "studio"],
    ["!!!", ""],
    ["日本", ""],
  ])("%s -> %s", (name, slug) => {
    expect(projectSlugFromName(name)).toBe(slug);
  });

  it("always satisfies the local bridge identifier pattern", () => {
    for (const name of ["a".repeat(200), "Ünïcödé ÷ ×", "x.y_z", "9 lives", "Été"]) {
      expect(projectSlugFromName(name)).toMatch(/^[a-z][a-z0-9_.-]{0,63}$/);
    }
  });
});

describe("step « Projet »", () => {
  it("creates a project with a slug, once, even on a double submit", async () => {
    api.GET.mockResolvedValue({ response: { ok: true }, data: [] });
    const pending = deferred<unknown>();
    api.createProject.mockReturnValue(pending.promise);
    const root = mount();
    await renderOnboarding(root, fakeDesktop(), emptySession({ schema: 1, status: "in_progress", current: "projet" }));
    root.querySelector<HTMLInputElement>("#project-name-input")!.value = "Jeu Phare";
    const form = root.querySelector<HTMLFormElement>("[data-testid=project-create-form]")!;
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]")!;
    expect(submit.disabled).toBe(true);
    expect(submit.textContent).toContain("Création en cours");
    expect(api.createProject).toHaveBeenCalledTimes(1);
    expect(api.createProject.mock.calls[0]![1]).toEqual({ slug: "jeu-phare", name: "Jeu Phare" });

    pending.resolve({ id: PROJECT, slug: "jeu-phare", name: "Jeu Phare" });
    await tick(10);
    expect(root.textContent).toContain("Projet créé.");
    expect(root.querySelector<HTMLButtonElement>("[data-action=next]")!.disabled).toBe(false);
    expect(JSON.parse(globalThis.localStorage.getItem(ONBOARDING_STORAGE_KEY)!)).toMatchObject({
      projectId: PROJECT,
      projectSlug: "jeu-phare",
    });
  });

  it("explains a slug conflict instead of blaming permissions, and unlocks the form", async () => {
    api.GET.mockResolvedValue({ response: { ok: true }, data: [] });
    api.createProject.mockRejectedValue(apiError(409));
    const root = mount();
    await renderOnboarding(root, fakeDesktop(), emptySession({ schema: 1, status: "in_progress", current: "projet" }));
    root.querySelector<HTMLInputElement>("#project-name-input")!.value = "Jeu Phare";
    root.querySelector("[data-testid=project-create-form]")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await tick(10);
    expect(root.querySelector("[data-testid=onboarding-error]")?.textContent).toContain("déjà ce nom");
    expect(root.querySelector<HTMLButtonElement>("[data-testid=project-create-form] button[type=submit]")!.disabled).toBe(false);
    // Conflict -> the list is fetched again so the existing project can be picked.
    expect(api.GET).toHaveBeenCalledTimes(2);
  });

  it("refuses a name without any letter or digit without calling the server", async () => {
    api.GET.mockResolvedValue({ response: { ok: true }, data: [] });
    const root = mount();
    await renderOnboarding(root, fakeDesktop(), emptySession({ schema: 1, status: "in_progress", current: "projet" }));
    root.querySelector<HTMLInputElement>("#project-name-input")!.value = "!!!";
    root.querySelector("[data-testid=project-create-form]")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await tick(10);
    expect(api.createProject).not.toHaveBeenCalled();
    expect(root.querySelector("[data-testid=onboarding-error]")).not.toBeNull();
  });

  it("reuses the idempotency key when the same project is retried after a lost answer", async () => {
    api.GET.mockResolvedValue({ response: { ok: true }, data: [] });
    api.createProject.mockRejectedValueOnce(new TypeError("network down")).mockRejectedValueOnce(new TypeError("network down"));
    const root = mount();
    await renderOnboarding(root, fakeDesktop(), emptySession({ schema: 1, status: "in_progress", current: "projet" }));
    const submit = async (name: string): Promise<void> => {
      root.querySelector<HTMLInputElement>("#project-name-input")!.value = name;
      root.querySelector("[data-testid=project-create-form]")!.dispatchEvent(new Event("submit", { cancelable: true }));
      await tick(10);
    };
    await submit("Jeu Phare");
    expect(root.querySelector("[data-testid=onboarding-error]")?.textContent).toContain("La création a échoué");
    await submit("Jeu Phare");
    api.createProject.mockResolvedValueOnce({ id: PROJECT, slug: "autre", name: "Autre" });
    await submit("Autre");
    const keys = api.createProject.mock.calls.map((call) => call[2]);
    expect(keys[0]).toBe(keys[1]);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("offers a retry after the project list failed, and shows the list once it answers", async () => {
    api.GET.mockRejectedValueOnce(new TypeError("network down")).mockResolvedValueOnce({
      response: { ok: true },
      data: [{ id: PROJECT, slug: "jeu", name: "Jeu" }],
    });
    const root = mount();
    await renderOnboarding(root, fakeDesktop(), emptySession({ schema: 1, status: "in_progress", current: "projet" }));
    expect(root.textContent).toContain("La liste des projets est indisponible");
    const reload = root.querySelector<HTMLButtonElement>("[data-action=reload-projects]");
    expect(reload).not.toBeNull();
    reload!.click();
    await tick(10);
    expect(root.querySelector("[data-testid=project-list]")?.textContent).toContain("Jeu");
    expect(root.querySelector("[data-testid=onboarding-error]")).toBeNull();
  });
});

describe("step « Dossier »", () => {
  it("associates a picked folder once, even on a double click", async () => {
    const commands: string[] = [];
    const confirm = deferred<BridgeAnswer>();
    const platform = fakeDesktop({
      request: (async (command: string, payload: Record<string, unknown>) => {
        commands.push(command);
        if (command === "identity.get_view") {
          return ok({ profile: { profile_id: "main", server_origin: "https://studio.example" }, secrets: [{ status: "present" }] });
        }
        if (command === "workspace.confirm_roots") return confirm.promise;
        if (command === "workspace.save_config") return ok(payload.config);
        return refused("not_supported");
      }) as never,
    });
    const session = emptySession({ schema: 1, status: "in_progress", current: "dossier", projectId: PROJECT, projectSlug: "jeu" });
    // Injected the way pickWorkspaceFolder reports a choice: no native dialog.
    session.folder = { kind: "selected", path: "C:\\Projets\\jeu", displayName: "jeu" };
    const root = mount();
    await renderOnboarding(root, platform, session);
    const associate = root.querySelector<HTMLButtonElement>("[data-action=associate]")!;
    expect(associate.disabled).toBe(false);
    associate.click();
    associate.click();
    expect(associate.disabled).toBe(true);
    expect(associate.textContent).toContain("Association en cours");
    await tick(10);
    confirm.resolve(ok({ root_confirmation_id: "rc-1" }));
    await tick(20);
    expect(commands.filter((c) => c === "workspace.confirm_roots")).toHaveLength(1);
    expect(commands.filter((c) => c === "workspace.save_config")).toHaveLength(1);
    expect(session.state.current).toBe("memoire");
    expect(session.state.folderName).toBe("jeu");
  });

  it("surfaces a refused association and lets the user try again", async () => {
    const platform = fakeDesktop({
      request: (async (command: string) => {
        if (command === "identity.get_view") {
          return ok({ profile: { profile_id: "main", server_origin: "https://studio.example" }, secrets: [{ status: "present" }] });
        }
        if (command === "workspace.confirm_roots") return refused("permission_denied");
        return refused("not_supported");
      }) as never,
    });
    const session = emptySession({ schema: 1, status: "in_progress", current: "dossier", projectId: PROJECT });
    session.folder = { kind: "selected", path: "C:\\Projets\\jeu", displayName: "jeu" };
    const root = mount();
    await renderOnboarding(root, platform, session);
    root.querySelector<HTMLButtonElement>("[data-action=associate]")!.click();
    await tick(20);
    expect(root.querySelector("[data-testid=onboarding-error]")?.textContent).toContain("Accès refusé");
    const again = root.querySelector<HTMLButtonElement>("[data-action=associate]")!;
    expect(again.disabled).toBe(false);
    expect(session.state.current).toBe("dossier");
  });
});

describe("step « Connexion »", () => {
  it("saves the server address once on a double submit", async () => {
    let calls = 0;
    const gate = deferred<void>();
    const platform = fakeDesktop({
      setServerOrigin: async () => {
        calls += 1;
        await gate.promise;
        return { ok: true as const, state: { configured: "https://new.example", applied: "https://new.example", restart_required: false } };
      },
    });
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
    const root = mount();
    await renderOnboarding(root, platform, emptySession({ schema: 1, status: "in_progress", current: "connexion" }));
    const form = root.querySelector<HTMLFormElement>("[data-testid=server-origin-form]")!;
    root.querySelector<HTMLInputElement>("#server-origin-input")!.value = "https://new.example";
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    expect(form.querySelector<HTMLButtonElement>("button[type=submit]")!.disabled).toBe(true);
    gate.resolve();
    await tick(20);
    expect(calls).toBe(1);
    expect(root.querySelector("[data-testid=onboarding-notice]")?.textContent).toContain("Adresse enregistrée");
    fetchSpy.mockRestore();
  });
});

describe("step « Assistant IA »", () => {
  it("applies a harness plan once on a double click and refreshes the card", async () => {
    const commands: string[] = [];
    let configured = false;
    const plan = { plan_id: "plan-1", plan_hash: "h", adapter_id: "claude-code", changes: [{ kind: "create", target: ".mcp.json" }] };
    const platform = fakeDesktop({
      request: (async (command: string) => {
        commands.push(command);
        if (command === "harness.detect") {
          return ok({
            harnesses: [
              {
                adapter_id: "claude-code",
                display_name: "Claude Code",
                state: configured ? "configured" : "detected",
                detected_version: "2.1.0",
              },
            ],
          });
        }
        if (command === "harness.preview") return ok(plan);
        if (command === "harness.apply") {
          await tick(5);
          configured = true;
          return ok({ state: "configured", error: null });
        }
        return refused("not_supported");
      }) as never,
    });
    const root = mount();
    await renderOnboarding(root, platform, emptySession({ schema: 1, status: "in_progress", current: "assistant", workspaceId: WS }));
    root.querySelector<HTMLButtonElement>("[data-action=preview]")!.click();
    await tick(10);
    const apply = root.querySelector<HTMLButtonElement>("[data-action=apply-plan]")!;
    apply.click();
    apply.click();
    expect(apply.disabled).toBe(true);
    await tick(30);
    expect(commands.filter((c) => c === "harness.apply")).toHaveLength(1);
    expect(root.textContent).toContain("Configuration appliquée");
    expect(root.querySelector('[data-harness="claude-code"]')?.getAttribute("data-state")).toBe("configured");
  });
});

describe("resume after an app restart", () => {
  it("keeps the associated folder when the local assistant is still starting", async () => {
    const platform = fakeDesktop({ request: (async () => refused("daemon_unavailable")) as never });
    const session = emptySession({ schema: 1, status: "in_progress", current: "memoire", workspaceId: WS, folderName: "jeu" });
    await revalidate(session, platform);
    expect(session.state.workspaceId).toBe(WS);
    expect(session.state.current).toBe("memoire");
    expect(session.error).toContain("non vérifiable");
  });

  it("reopens on the persisted step with the persisted choices", async () => {
    saveOnboardingState({ schema: 1, status: "in_progress", current: "memoire", workspaceId: WS, folderName: "jeu", projectId: PROJECT });
    const platform = fakeDesktop({
      request: (async (command: string) => {
        if (command === "workspace.validate") return ok({ workspace_id: WS, health: "valid", action: "none" });
        if (command === "knowledge.status") {
          return ok({ workspace_id: WS, state: "disabled", canonical_source: "markdown_files", integrations: [] });
        }
        return refused("not_supported");
      }) as never,
    });
    const root = mount();
    await renderOnboarding(root, platform);
    expect(root.querySelector("[data-testid=onboarding-step]")?.getAttribute("data-step")).toBe("memoire");
    expect(root.textContent).toContain("Mémoire désactivée");
    expect(root.querySelector("[data-testid=onboarding-error]")).toBeNull();
  });
});
