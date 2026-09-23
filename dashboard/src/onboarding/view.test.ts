// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from "vitest";
import type { BridgeAnswer } from "../platform/contracts";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import { webPlatform } from "../platform/web";
import { ONBOARDING_STORAGE_KEY } from "./state";
import { emptySession, newWorkspaceId, onboardingWebHtml, renderOnboarding, revalidate } from "./view";

const WS = "11111111-1111-4111-8111-111111111111";

const ok = (payload: unknown): BridgeAnswer => ({ ok: true, response: { payload } }) as unknown as BridgeAnswer;
const refused = (code: string): BridgeAnswer =>
  ({ ok: false, error: { code, component: "workspace", message: "x", retryable: false, correlation_id: null, details: {} } }) as unknown as BridgeAnswer;

function rig(validate: BridgeAnswer = refused("workspace_config_missing")) {
  const calls: string[] = [];
  const platform = fakeDesktop(
    {
      request: (async (command: string) => {
        calls.push(command);
        if (command === "workspace.validate") return validate;
        if (command === "identity.get_view") {
          return ok({ profile: { profile_id: "main", server_origin: "https://studio.example" }, secrets: [] });
        }
        return refused("not_supported");
      }) as never,
    },
    { configured: "https://studio.example", applied: "https://studio.example", restart_required: false },
  );
  return { platform, calls };
}

beforeEach(() => {
  document.body.innerHTML = "";
  globalThis.localStorage.removeItem(ONBOARDING_STORAGE_KEY);
});

describe("onboarding view", () => {
  it("stays standalone on the web: no local bridge, no picker, no daemon", async () => {
    const root = document.createElement("main");
    await renderOnboarding(root, webPlatform);
    expect(root.textContent).toContain("Studi'OS Desktop");
    expect(onboardingWebHtml()).toContain("autonome");
  });

  it("welcomes a fresh install with a single start action", async () => {
    const { platform } = rig();
    const root = document.createElement("main");
    document.body.append(root);
    await renderOnboarding(root, platform, emptySession({ schema: 1, status: "not_started", current: "bienvenue" }));
    expect(root.textContent).toContain("Bienvenue dans Studi'OS");
    expect(root.querySelector("[data-action=start]")).not.toBeNull();
    // Technical vocabulary stays out of the main journey.
    expect(root.textContent).not.toMatch(/MCP|démon|Graphify|Vault|UUID|sidecar/i);
  });

  it("marks progress without relying on color alone", async () => {
    const { platform } = rig();
    const root = document.createElement("main");
    await renderOnboarding(root, platform, emptySession({ schema: 1, status: "in_progress", current: "projet" }));
    const current = root.querySelector('[aria-current="step"]');
    expect(current?.textContent).toContain("Projet");
    expect(root.querySelector("[data-testid=onboarding-progress]")).not.toBeNull();
  });

  it("detects an already-configured install instead of forcing the wizard", async () => {
    const { platform } = rig(
      ok({ workspace_id: WS, health: "valid", action: "none", config: { workspace_id: WS } }),
    );
    const root = document.createElement("main");
    document.body.append(root);
    await renderOnboarding(
      root,
      platform,
      emptySession({ schema: 1, status: "in_progress", current: "bienvenue", workspaceId: WS }),
    );
    expect(root.textContent).toContain("déjà détectée");
    expect(root.querySelector("[data-action=finish-detected]")).not.toBeNull();
  });

  it("revalidates on resume: a moved folder sends the user back to the folder step", async () => {
    const { platform } = rig(ok({ workspace_id: WS, health: "moved", action: "confirm_relocation" }));
    const session = emptySession({ schema: 1, status: "in_progress", current: "assistant", workspaceId: WS, folderName: "Mon jeu" });
    await revalidate(session, platform);
    expect(session.state.current).toBe("dossier");
    expect(session.error).toContain("dossier");
  });

  it("forgets a workspace the daemon no longer knows", async () => {
    const { platform } = rig();
    const session = emptySession({ schema: 1, status: "in_progress", current: "final", workspaceId: WS });
    await revalidate(session, platform);
    expect(session.state.current).toBe("dossier");
    expect(session.state.workspaceId).toBeUndefined();
  });

  it("never prints a workspace id in the folder step", async () => {
    const { platform } = rig();
    const root = document.createElement("main");
    await renderOnboarding(
      root,
      platform,
      emptySession({ schema: 1, status: "in_progress", current: "dossier", projectId: "22222222-2222-4222-8222-222222222222" }),
    );
    expect(root.innerHTML).not.toContain(WS);
    expect(root.querySelector("[data-action=pick]")).not.toBeNull();
  });

  it("mints workspace ids in UUID shape", () => {
    expect(newWorkspaceId()).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it("offers an explicit restart once a new server address needs one to apply", async () => {
    const { platform } = rig();
    let restarted = false;
    const withRestart = {
      ...platform,
      setServerOrigin: async () => ({ ok: true as const, state: { configured: "https://new.example", applied: null, restart_required: true } }),
      restartDesktop: async () => {
        restarted = true;
        return true;
      },
    };
    const root = document.createElement("main");
    document.body.append(root);
    await renderOnboarding(root, withRestart, emptySession({ schema: 1, status: "in_progress", current: "connexion" }));
    root.querySelector<HTMLInputElement>("#server-origin-input")!.value = "https://new.example";
    root.querySelector("[data-testid=server-origin-form]")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await new Promise((r) => setTimeout(r, 0));
    const restartButton = root.querySelector<HTMLButtonElement>("[data-action=restart-desktop]");
    expect(restartButton).not.toBeNull();
    expect(root.textContent).toContain("Redémarrez l'application");
    restartButton!.click();
    await new Promise((r) => setTimeout(r, 0));
    expect(restarted).toBe(true);
  });

  it("initializes and indexes a new memory folder from the wizard", async () => {
    const calls: Array<{ command: string; payload: Record<string, unknown> }> = [];
    let ready = false;
    const platform = fakeDesktop({
      request: (async (command: string, payload: Record<string, unknown>) => {
        calls.push({ command, payload });
        if (command === "knowledge.status") {
          return ok({
            workspace_id: WS,
            state: ready ? "ready" : "unavailable",
            canonical_source: "markdown_files",
            index: { state: ready ? "ready" : "absent", derived: true, rebuildable: true },
            integrations: [],
          });
        }
        if (command === "workspace.get_config") {
          return ok({
            schema_version: 1,
            workspace_id: WS,
            project_id: "22222222-2222-4222-8222-222222222222",
            project_slug: "demo",
            profile: { profile_id: "main", server_origin: "https://studio.example" },
            roots: { workspace_root: "C:\\Projects\\demo", repo_roots: [] },
            features: {},
            created_at: "2026-09-22T00:00:00Z",
            updated_at: "2026-09-22T00:00:00Z",
          });
        }
        if (command === "workspace.save_config") return ok(payload.config);
        if (command === "knowledge.init_vault") {
          return ok({ workspace_id: WS, state_before: "missing", created: ["README.md"], skipped: [] });
        }
        if (command === "knowledge.reindex") {
          ready = true;
          return ok({ accepted: true, operation_id: "op-init", state: "indexing" });
        }
        return refused("not_supported");
      }) as never,
    });
    const root = document.createElement("main");
    document.body.append(root);
    await renderOnboarding(
      root,
      platform,
      emptySession({ schema: 1, status: "in_progress", current: "memoire", workspaceId: WS }),
    );
    root.querySelector<HTMLFormElement>("[data-testid=memory-folder-form]")?.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(calls.find((call) => call.command === "knowledge.init_vault")?.payload).toEqual({
      workspace_id: WS,
      confirmed: true,
    });
    const commands = calls.map((call) => call.command);
    expect(commands.indexOf("knowledge.init_vault")).toBeLessThan(
      commands.indexOf("knowledge.reindex"),
    );
    expect(root.textContent).toContain("Mémoire activée et préparée");
  });

  it("enables the code graph with the associated folder as its repository", async () => {
    const calls: Array<{ command: string; payload: Record<string, unknown> }> = [];
    let enabled = false;
    const platform = fakeDesktop({
      request: (async (command: string, payload: Record<string, unknown>) => {
        calls.push({ command, payload });
        if (command === "code_graph.status") return ok({ workspace_id: WS, state: enabled ? "indexing" : "disabled" });
        if (command === "workspace.git_status") return ok({ state: "valid", branch: "master" });
        if (command === "workspace.get_config") {
          return ok({
            schema_version: 1,
            workspace_id: WS,
            roots: { workspace_root: "C:\\Projects\\demo", repo_roots: [] },
            features: { knowledge: true },
            updated_at: "2026-09-22T00:00:00Z",
          });
        }
        if (command === "workspace.confirm_roots") return ok({ root_confirmation_id: "rc-1" });
        if (command === "workspace.save_config") {
          enabled = true;
          return ok(payload.config);
        }
        if (command === "code_graph.reindex") return ok({ accepted: true, operation_id: "op-1", state: "indexing" });
        return refused("not_supported");
      }) as never,
    });
    const root = document.createElement("main");
    document.body.append(root);
    await renderOnboarding(
      root,
      platform,
      emptySession({ schema: 1, status: "in_progress", current: "environnement", workspaceId: WS }),
    );
    root.querySelector<HTMLButtonElement>("[data-action=enable-code]")!.click();
    await new Promise((resolve) => setTimeout(resolve, 20));
    const confirm = calls.find((call) => call.command === "workspace.confirm_roots")?.payload;
    expect(confirm).toEqual({
      roots: { workspace_root: "C:\\Projects\\demo", repo_roots: [{ name: "main", path: "C:\\Projects\\demo" }] },
    });
    const save = calls.find((call) => call.command === "workspace.save_config")?.payload as {
      config: { features: Record<string, boolean>; code_graph: { provider_id: string } };
      root_confirmation_id: string;
    };
    expect(save.root_confirmation_id).toBe("rc-1");
    expect(save.config.features).toEqual({ knowledge: true, code_graph: true });
    expect(save.config.code_graph.provider_id).toBe("graphify");
    expect(root.textContent).toContain("Analyse du code activée");
    expect(root.querySelector("[data-action=enable-code]")).toBeNull();
  });

  it("locks the memory button while enabling and surfaces a thrown failure", async () => {
    let release: () => void = () => undefined;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    const platform = fakeDesktop({
      request: (async (command: string) => {
        if (command === "knowledge.status") {
          return ok({ workspace_id: WS, state: "disabled", canonical_source: "markdown_files", integrations: [] });
        }
        if (command === "workspace.get_config") {
          await pending;
          throw new Error("bridge down");
        }
        return refused("not_supported");
      }) as never,
    });
    const root = document.createElement("main");
    document.body.append(root);
    await renderOnboarding(
      root,
      platform,
      emptySession({ schema: 1, status: "in_progress", current: "memoire", workspaceId: WS }),
    );
    const form = root.querySelector<HTMLFormElement>("[data-testid=memory-folder-form]")!;
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]")!;
    expect(submit.disabled).toBe(true);
    expect(submit.textContent).toContain("Activation en cours");
    release();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(root.textContent).toContain("L'activation de la mémoire a échoué");
  });
});
