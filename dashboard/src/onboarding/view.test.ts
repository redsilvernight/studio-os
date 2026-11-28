// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from "vitest";
import type { BridgeAnswer } from "../platform/contracts";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import { webPlatform } from "../platform/web";
import { ONBOARDING_STORAGE_KEY } from "./state";
import { emptySession, onboardingWebHtml, renderOnboarding, revalidate } from "./view";

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
    await renderOnboarding(root, platform, emptySession({ schema: 1, status: "in_progress", current: "verification" }));
    const current = root.querySelector('[aria-current="step"]');
    expect(current?.textContent).toContain("Vérification");
    expect(root.querySelector("[data-testid=onboarding-progress]")).not.toBeNull();
    expect(root.textContent).not.toMatch(/Projet|Dossier|Mémoire|Assistant IA/);
  });

  it("revalidate is a no-op: the workstation-only journey keeps its persisted step", async () => {
    const { platform } = rig(ok({ workspace_id: WS, health: "valid", action: "none", config: { workspace_id: WS } }));
    const session = emptySession({ schema: 1, status: "in_progress", current: "final", workspaceId: WS, folderName: "Mon jeu" });
    await revalidate(session, platform);
    expect(session.state.current).toBe("final");
    expect(session.error).toBeNull();
    expect(session.state.workspaceId).toBe(WS);
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

  it("the ready screen finishes without a project or folder and points at Workspaces", async () => {
    const { platform } = rig();
    const root = document.createElement("main");
    document.body.append(root);
    await renderOnboarding(root, platform, emptySession({ schema: 1, status: "in_progress", current: "final" }));
    expect(root.textContent).toContain("Votre poste est prêt");
    expect(root.querySelector("[data-testid=onboarding-error]")).toBeNull();
    // No obligation: finish is enabled with no folder, and Workspaces is one click away.
    expect(root.querySelector<HTMLButtonElement>("[data-action=finish]")!.disabled).toBe(false);
    expect(root.querySelector("[data-testid=onboarding-to-workspaces]")?.getAttribute("href")).toBe("#/reglages/dossiers");
    expect(root.innerHTML).not.toContain(WS);
    root.querySelector<HTMLButtonElement>("[data-action=finish]")!.click();
    expect(JSON.parse(globalThis.localStorage.getItem(ONBOARDING_STORAGE_KEY)!)).toMatchObject({
      status: "completed",
      current: "termine",
    });
  });

  it("the done screen links to the dashboard and to Workspaces", async () => {
    const { platform } = rig();
    const root = document.createElement("main");
    await renderOnboarding(root, platform, emptySession({ schema: 1, status: "completed", current: "termine" }));
    expect(root.textContent).toContain("Votre poste est prêt");
    expect(root.querySelector('a[href="#/"]')).not.toBeNull();
    expect(root.querySelector('a[href="#/reglages/dossiers"]')).not.toBeNull();
  });
});
