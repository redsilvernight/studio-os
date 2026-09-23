// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from "vitest";
import { buildRequest } from "../platform/contracts";
import type { BridgeAnswer } from "../platform/contracts";
import type { HarnessState } from "../platform/generated/local-contracts.generated";
import { webPlatform } from "../platform/web";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import { applyHarness, detectHarnesses, harnessErrorMessage, latestRollbackId, previewHarness, rollbackHarness } from "../harnessApi";
import { integrationsHtml, renderIntegrations } from "./integrations";

const WS = "11111111-2222-4333-8444-555555555555";
const flush = async (): Promise<void> => {
  for (let i = 0; i < 12; i += 1) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
};

const ok = (payload: unknown): BridgeAnswer => ({ ok: true, response: { payload } }) as unknown as BridgeAnswer;
const refused = (code: string, reason?: string): BridgeAnswer =>
  ({ ok: false, error: { code, component: "harness", message: "x", retryable: false, correlation_id: null, details: reason ? { reason } : {} } }) as unknown as BridgeAnswer;

const status = (adapter_id: string, state: HarnessState, extra: Record<string, unknown> = {}) => ({
  adapter_id,
  harness_id: adapter_id,
  display_name: adapter_id === "claude-code" ? "Claude Code" : "OpenCode",
  state,
  detected_version: state === "not_detected" ? null : "2.1.272",
  managed_files: state === "configured" ? [adapter_id === "claude-code" ? ".mcp.json" : "opencode.json"] : [],
  capabilities: [],
  ...extra,
});
const plan = (adapter_id: string, changes: unknown[] = [{ change_id: "c1", kind: "create", target: ".mcp.json", summary: "Ajoute le serveur studio-os" }]) => ({
  plan_id: "plan-1",
  plan_hash: "a".repeat(64),
  workspace_id: WS,
  adapter_id,
  created_at: "2026-09-22T10:00:00Z",
  expires_at: "2026-09-22T10:10:00Z",
  changes,
  requires_confirmation: true,
});

interface Rig {
  calls: { command: string; payload: Record<string, unknown> }[];
  states: Record<string, HarnessState>;
  onApply: () => BridgeAnswer;
  onRollback: () => BridgeAnswer;
  onPreview?: () => BridgeAnswer;
}

function rig(): { platform: ReturnType<typeof fakeDesktop>; state: Rig } {
  const state: Rig = {
    calls: [],
    states: { "claude-code": "detected", opencode: "not_detected" },
    onApply: () => {
      state.states["claude-code"] = "configured";
      return ok({ plan_id: "plan-1", state: "configured", applied: ["c1"], rollback_id: "rb-" + "a".repeat(32) });
    },
    onRollback: () => {
      state.states["claude-code"] = "detected";
      return ok({ rollback_id: "rb-" + "a".repeat(32), state: "detected", restored: [".mcp.json"] });
    },
  };
  const platform = fakeDesktop({
    request: (async (command: string, payload: Record<string, unknown> = {}) => {
      state.calls.push({ command, payload });
      if (command === "harness.detect") {
        return ok({ harnesses: Object.entries(state.states).map(([id, s]) => status(id, s)) });
      }
      if (command === "harness.preview") return state.onPreview ? state.onPreview() : ok(plan(String(payload["adapter_id"])));
      if (command === "harness.apply") return state.onApply();
      if (command === "harness.rollback") return state.onRollback();
      return refused("not_supported");
    }) as never,
  });
  return { platform, state };
}

async function mount(platform: ReturnType<typeof fakeDesktop>, workspaceId: string | null = WS) {
  const root = document.createElement("main");
  document.body.append(root);
  await renderIntegrations(root, workspaceId ?? undefined, platform);
  return root;
}
const click = async (root: HTMLElement, selector: string): Promise<void> => {
  root.querySelector<HTMLElement>(selector)?.click();
  await flush();
};
const card = (root: HTMLElement, id: string): HTMLElement => root.querySelector<HTMLElement>(`[data-harness="${id}"]`) as HTMLElement;

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("harnessApi", () => {
  it("builds payloads the bundled P1 schemas accept", () => {
    buildRequest("harness.detect", { workspace_id: WS });
    buildRequest("harness.preview", { workspace_id: WS, adapter_id: "claude-code" });
    buildRequest("harness.apply", { plan_id: "plan-1", plan_hash: "a".repeat(64), confirmed: true });
    buildRequest("harness.rollback", { rollback_id: latestRollbackId(WS, "claude-code"), confirmed: true });
  });

  it("sends the documented commands and nothing else", async () => {
    const { platform, state } = rig();
    await detectHarnesses(platform, WS);
    await previewHarness(platform, WS, "opencode");
    await applyHarness(platform, plan("opencode") as never);
    await rollbackHarness(platform, "rb-" + "b".repeat(32));
    expect(state.calls.map((c) => c.command)).toEqual(["harness.detect", "harness.preview", "harness.apply", "harness.rollback"]);
    expect(state.calls[2]?.payload).toEqual({ plan_id: "plan-1", plan_hash: "a".repeat(64), confirmed: true });
  });

  it("negotiates the local protocol again when the daemon forgot its grants, then retries once", async () => {
    let granted = false;
    const calls: string[] = [];
    const platform = fakeDesktop({
      request: (async (command: string) => {
        calls.push(command);
        if (command === "runtime.handshake") {
          granted = true;
          return ok({ outcome: "compatible", daemon: {}, granted_capabilities: ["harness.read"] });
        }
        return granted ? ok({ harnesses: [] }) : refused("capability_missing");
      }) as never,
    });
    const outcome = await detectHarnesses(platform, WS);
    expect(outcome.ok).toBe(true);
    expect(calls).toEqual(["harness.detect", "runtime.handshake", "harness.detect"]);
  });

  it("does not loop when the capability stays missing", async () => {
    const calls: string[] = [];
    const platform = fakeDesktop({
      request: (async (command: string) => {
        calls.push(command);
        return refused("capability_missing");
      }) as never,
    });
    const outcome = await detectHarnesses(platform, WS);
    expect(outcome.ok).toBe(false);
    expect(calls).toEqual(["harness.detect", "runtime.handshake", "harness.detect"]);
  });

  it("turns harness integrations on for the folder, then previews again once", async () => {
    let harnessOn = false;
    const calls: { command: string; payload: Record<string, unknown> }[] = [];
    const roots = { workspace_root: "C:/jeu", repo_roots: [] };
    const stored = { workspace_id: WS, roots, features: { knowledge: true, harness: false }, updated_at: "2026-09-22T10:00:00Z" };
    const platform = fakeDesktop({
      request: (async (command: string, payload: Record<string, unknown> = {}) => {
        calls.push({ command, payload });
        if (command === "harness.preview") return harnessOn ? ok(plan("claude-code")) : refused("feature_disabled", "feature_disabled");
        if (command === "workspace.get_config") return ok(stored);
        if (command === "workspace.save_config") {
          harnessOn = true;
          return ok(payload["config"]);
        }
        return refused("not_supported");
      }) as never,
    });
    const outcome = await previewHarness(platform, WS, "claude-code");
    expect(outcome.ok).toBe(true);
    expect(calls.map((c) => c.command)).toEqual(["harness.preview", "workspace.get_config", "workspace.save_config", "harness.preview"]);
    const save = calls[2]?.payload as { config: { features: Record<string, unknown> }; current_roots: unknown; expected_updated_at: string };
    expect(save.config.features).toEqual({ knowledge: true, harness: true });
    expect(save.current_roots).toEqual(roots);
    expect(save.expected_updated_at).toBe("2026-09-22T10:00:00Z");
    expect(calls.map((c) => c.command)).not.toContain("harness.apply");
  });

  it("does not loop when the feature stays disabled", async () => {
    const calls: string[] = [];
    const platform = fakeDesktop({
      request: (async (command: string, payload: Record<string, unknown> = {}) => {
        calls.push(command);
        if (command === "workspace.get_config") return ok({ workspace_id: WS, roots: {}, features: {} });
        if (command === "workspace.save_config") return ok(payload["config"]);
        return refused("feature_disabled", "feature_disabled");
      }) as never,
    });
    const outcome = await previewHarness(platform, WS, "claude-code");
    expect(outcome.ok).toBe(false);
    expect(calls).toEqual(["harness.preview", "workspace.get_config", "workspace.save_config", "harness.preview"]);
  });

  it("reports a refused config save without previewing again", async () => {
    const calls: string[] = [];
    const platform = fakeDesktop({
      request: (async (command: string) => {
        calls.push(command);
        if (command === "workspace.get_config") return ok({ workspace_id: WS, roots: {}, features: {} });
        if (command === "workspace.save_config") return refused("invalid_request");
        return refused("feature_disabled", "feature_disabled");
      }) as never,
    });
    const outcome = await previewHarness(platform, WS, "claude-code");
    expect(outcome.ok).toBe(false);
    expect(calls).toEqual(["harness.preview", "workspace.get_config", "workspace.save_config"]);
  });

  it("words refusals in French without echoing raw daemon text", () => {
    expect(harnessErrorMessage({ code: "invalid_request", message: "C:\\Users\\x secret", details: { reason: "rollback_conflict" } } as never)).toContain("modifié");
    expect(harnessErrorMessage({ code: "internal_error", message: "boom C:\\Users\\x", details: {} } as never)).not.toContain("C:");
    expect(harnessErrorMessage(null).length).toBeGreaterThan(5);
    expect(harnessErrorMessage({ code: "internal_error", message: "x", details: { reason: "restore_failed" } } as never)).toContain("Restaurer");
  });
});

describe("Settings › Intégrations IA (web)", () => {
  it("states this is a Desktop feature and calls nothing", async () => {
    const root = document.createElement("main");
    await renderIntegrations(root, WS, webPlatform);
    expect(root.textContent).toContain("Fonction de Studi'OS Desktop");
    expect(root.querySelector("[data-harness]")).toBeNull();
    expect(root.querySelector("form, [data-action], [role=alert]")).toBeNull();
    expect(root.textContent).not.toMatch(/bridge|pont|Tauri|introuvable|erreur/i);
  });
});

describe("Settings › Intégrations IA (Desktop)", () => {
  it("carries the remembered folder instead of asking for a workspace id", async () => {
    const { platform, state } = rig();
    globalThis.localStorage.setItem(
      "studio-os.onboarding.v1",
      JSON.stringify({ schema: 1, status: "in_progress", current: "assistant", workspaceId: WS, folderName: "Mon jeu" }),
    );
    try {
      const root = await mount(platform, null);
      expect(state.calls).toEqual([]);
      expect(root.querySelector("#workspace-id-input")).toBeNull();
      expect(root.querySelector("[data-testid=workspace-form]")).toBeNull();
      expect(root.textContent).toContain("Mon jeu");
      expect(root.querySelector<HTMLAnchorElement>("[data-testid=workspace-continue]")?.getAttribute("href")).toBe(
        `#/configuration/integrations/${WS}`,
      );
    } finally {
      globalThis.localStorage.removeItem("studio-os.onboarding.v1");
    }
  });

  it("points to the setup assistant when no folder is remembered", async () => {
    const { platform, state } = rig();
    globalThis.localStorage.removeItem("studio-os.onboarding.v1");
    const root = await mount(platform, null);
    expect(state.calls).toEqual([]);
    expect(root.querySelector("#workspace-id-input")).toBeNull();
    expect(root.textContent).toContain("Lancer l'assistant");
  });

  it("shows state, version and MCP state per harness, with the right actions", async () => {
    const { platform, state } = rig();
    state.states = { "claude-code": "configured", opencode: "detected" };
    const root = await mount(platform);
    const claude = card(root, "claude-code");
    expect(claude.textContent).toContain("Configuré");
    expect(claude.textContent).toContain("2.1.272");
    expect(claude.textContent).toContain(".mcp.json");
    expect(claude.querySelector("[data-action=preview]")?.textContent).toBe("Reconfigurer");
    expect(claude.querySelector("[data-action=restore]")).not.toBeNull();
    const opencode = card(root, "opencode");
    expect(opencode.querySelector("[data-action=preview]")?.textContent).toBe("Configurer");
    expect(opencode.querySelector("[data-action=restore]")).toBeNull();
  });

  it("offers no action for a harness that is absent or unsupported", async () => {
    const { platform, state } = rig();
    state.states = { "claude-code": "incompatible", opencode: "not_detected" };
    const root = await mount(platform);
    expect(root.querySelector("[data-action]")).toBeNull();
    expect(card(root, "claude-code").textContent).toContain("Version non prise en charge");
    expect(card(root, "opencode").textContent).toContain("Non installé");
  });

  it("previews before anything is applied, and applies only after confirmation", async () => {
    const { platform, state } = rig();
    const root = await mount(platform);
    await click(root, "[data-harness=claude-code] [data-action=preview]");
    expect(root.querySelector("[data-testid=plan]")?.textContent).toContain("Création");
    expect(root.querySelector("[data-testid=plan]")?.textContent).not.toContain("Ajoute le serveur");
    expect(root.querySelector("[data-testid=plan]")?.textContent).toContain(".mcp.json");
    expect(state.calls.map((c) => c.command)).not.toContain("harness.apply");
    expect(root.querySelector("[data-testid=notice]")).toBeNull();
    await click(root, "[data-action=apply-plan]");
    expect(state.calls.map((c) => c.command)).toEqual(["harness.detect", "harness.preview", "harness.detect", "harness.apply", "harness.detect"]);
    expect(root.querySelector("[data-testid=notice]")?.textContent).toContain("Configuration appliquée");
    expect(card(root, "claude-code").dataset["state"]).toBe("configured");
  });

  it("cancelling a preview applies nothing", async () => {
    const { platform, state } = rig();
    const root = await mount(platform);
    await click(root, "[data-action=preview]");
    await click(root, "[data-action=cancel-plan]");
    expect(root.querySelector("[data-testid=plan]")).toBeNull();
    expect(state.calls.map((c) => c.command)).not.toContain("harness.apply");
  });

  it("reports an already up-to-date harness without offering to apply", async () => {
    const { platform, state } = rig();
    state.onPreview = () => ok(plan("claude-code", []));
    const root = await mount(platform);
    await click(root, "[data-action=preview]");
    expect(root.querySelector("[data-testid=plan]")?.textContent).toContain("Déjà à jour");
    expect(root.querySelector("[data-action=apply-plan]")).toBeNull();
  });

  it("never shows a change as applied when the apply is refused", async () => {
    const { platform, state } = rig();
    state.onApply = () => refused("invalid_request", "changed_since_preview");
    const root = await mount(platform);
    await click(root, "[data-action=preview]");
    await click(root, "[data-action=apply-plan]");
    expect(root.querySelector("[data-testid=notice]")).toBeNull();
    expect(root.querySelector("[data-testid=error]")?.textContent).toContain("changé depuis l'aperçu");
    expect(card(root, "claude-code").dataset["state"]).toBe("detected");
  });

  it("never shows a change as applied when the daemon answers with an error result", async () => {
    const { platform, state } = rig();
    state.onApply = () => ok({ plan_id: "plan-1", state: "error", applied: [], error: { code: "internal_error", message: "x", details: { reason: "verify_failed" } } });
    const root = await mount(platform);
    await click(root, "[data-action=preview]");
    await click(root, "[data-action=apply-plan]");
    expect(root.querySelector("[data-testid=notice]")).toBeNull();
    expect(root.querySelector("[data-testid=error]")?.textContent).toContain("rétabli");
  });

  it("restores through the newest-backup alias, after a confirmation", async () => {
    const { platform, state } = rig();
    state.states["claude-code"] = "configured";
    const root = await mount(platform);
    await click(root, "[data-action=restore]");
    expect(root.querySelector("[data-testid=restore-confirm]")).not.toBeNull();
    expect(state.calls.map((c) => c.command)).not.toContain("harness.rollback");
    await click(root, "[data-action=confirm-restore]");
    const rollback = state.calls.find((c) => c.command === "harness.rollback");
    expect(rollback?.payload).toEqual({ rollback_id: `latest:${WS}:claude-code`, confirmed: true });
    expect(root.querySelector("[data-testid=notice]")?.textContent).toContain("restaurée");
    expect(card(root, "claude-code").dataset["state"]).toBe("detected");
  });

  it("surfaces a rollback conflict and claims no restoration", async () => {
    const { platform, state } = rig();
    state.states["claude-code"] = "configured";
    state.onRollback = () => refused("invalid_request", "rollback_conflict");
    const root = await mount(platform);
    await click(root, "[data-action=restore]");
    await click(root, "[data-action=confirm-restore]");
    expect(root.querySelector("[data-testid=notice]")).toBeNull();
    expect(root.querySelector("[data-testid=error]")?.textContent).toContain("restauration est refusée");
    expect(card(root, "claude-code").dataset["state"]).toBe("configured");
  });

  it("shows a clean error when the local assistant is unavailable", async () => {
    const platform = fakeDesktop({ request: (async () => refused("daemon_unavailable")) as never });
    const root = await mount(platform);
    expect(root.querySelector("[data-testid=error]")?.textContent).toContain("assistant local");
    expect(root.querySelector("[data-harness]")).toBeNull();
  });

  it("asks for no provider credential and names none", async () => {
    const html = integrationsHtml([status("claude-code", "detected") as never]);
    expect(html).not.toMatch(/<input/i);
    expect(html).not.toMatch(/ANTHROPIC|OPENAI|api_key|apikey/i);
  });

  it("escapes hostile text coming from the daemon", () => {
    const html = integrationsHtml([status("claude-code", "detected", { display_name: "<img src=x onerror=alert(1)>" }) as never]);
    expect(html).not.toContain("<img src=x");
  });
});
