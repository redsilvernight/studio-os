// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { buildRequest } from "../platform/contracts";
import type { BridgeAnswer } from "../platform/contracts";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import {
  confirmRoots,
  gitStatusMessage,
  saveWorkspaceConfig,
  validateWorkspace,
  workspaceErrorMessage,
  workspaceGitStatus,
  workspaceHealthMessage,
} from "./workspaceApi";

const WS = "11111111-1111-4111-8111-111111111111";

const ok = (payload: unknown): BridgeAnswer => ({ ok: true, response: { payload } }) as unknown as BridgeAnswer;
const refused = (code: string): BridgeAnswer =>
  ({ ok: false, error: { code, component: "workspace", message: "x", retryable: false, correlation_id: null, details: {} } }) as unknown as BridgeAnswer;

function rig(handler: (command: string, payload: Record<string, unknown>) => BridgeAnswer) {
  const calls: { command: string; payload: Record<string, unknown> }[] = [];
  const platform = fakeDesktop({
    request: (async (command: string, payload: Record<string, unknown> = {}) => {
      calls.push({ command, payload });
      return handler(command, payload);
    }) as never,
  });
  return { platform, calls };
}

describe("workspaceApi", () => {
  it("builds payloads the bundled P1 schemas accept", () => {
    buildRequest("workspace.validate", { workspace_id: WS });
    buildRequest("workspace.confirm_roots", { roots: { workspace_root: "C:/Work/game", repo_roots: [] } });
    buildRequest("workspace.git_status", { workspace_id: WS });
    buildRequest("workspace.save_config", {
      config: {
        schema_version: 1,
        workspace_id: WS,
        profile: { profile_id: "main", server_origin: "https://studio.example" },
        project_id: "22222222-2222-4222-8222-222222222222",
        roots: { workspace_root: "C:/Work/game", repo_roots: [] },
        created_at: "2026-09-22T10:00:00Z",
        updated_at: "2026-09-22T10:00:00Z",
      },
      current_roots: null,
      root_confirmation_id: "rc-abc",
    });
  });

  it("validates, confirms, probes git and saves through the documented commands", async () => {
    const { platform, calls } = rig((command) => {
      if (command === "workspace.validate") return ok({ workspace_id: WS, health: "valid", action: "none", config: {} });
      if (command === "workspace.confirm_roots") return ok({ root_confirmation_id: "rc-1", expires_in_s: 600 });
      if (command === "workspace.git_status") return ok({ workspace_id: WS, state: "valid", branch: "main", detached: false });
      return ok({ workspace_id: WS });
    });
    expect((await validateWorkspace(platform, WS)).ok).toBe(true);
    const confirmed = await confirmRoots(platform, { workspace_root: "C:/Work/game" });
    expect(confirmed.ok && confirmed.value.root_confirmation_id).toBe("rc-1");
    const git = await workspaceGitStatus(platform, WS);
    expect(git.ok && gitStatusMessage(git.ok ? git.value : null)).toContain("branche main");
    const saved = await saveWorkspaceConfig(platform, { config: { workspace_id: WS }, current_roots: null, root_confirmation_id: "rc-1" });
    expect(saved.ok).toBe(true);
    expect(calls.map((c) => c.command)).toEqual([
      "workspace.validate",
      "workspace.confirm_roots",
      "workspace.git_status",
      "workspace.save_config",
    ]);
  });

  it("renegotiates once when the daemon forgot its grants", async () => {
    let granted = false;
    const seen: string[] = [];
    const { platform } = rig((command) => {
      seen.push(command);
      if (command === "runtime.handshake") {
        granted = true;
        return ok({ outcome: "compatible", granted_capabilities: ["workspace.config"] });
      }
      return granted ? ok({ workspace_id: WS, health: "valid", action: "none", config: {} }) : refused("capability_missing");
    });
    const outcome = await validateWorkspace(platform, WS);
    expect(outcome.ok).toBe(true);
    expect(seen).toEqual(["workspace.validate", "runtime.handshake", "workspace.validate"]);
  });

  it("words every state in French without echoing paths", () => {
    expect(workspaceHealthMessage({ health: "moved", action: "confirm_relocation" } as never)).toContain("déplacé");
    expect(workspaceHealthMessage(null)).toContain("inconnu");
    expect(gitStatusMessage({ state: "git_absent" } as never)).toContain("pas installé");
    expect(gitStatusMessage(null)).toContain("inconnu");
    expect(workspaceErrorMessage({ code: "workspace_inaccessible", message: "C:\\secret", details: {} } as never)).not.toContain("C:");
    expect(workspaceErrorMessage({ code: "workspace_moved", message: "x", details: {} } as never)).toContain("déplacé");
    expect(workspaceErrorMessage(null).length).toBeGreaterThan(5);
  });
});
