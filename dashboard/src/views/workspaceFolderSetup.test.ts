// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import type { BridgeAnswer } from "../platform/contracts";
import { fakeDesktop } from "../testSupport/fakeDesktop";
import { renderFolderSetup } from "./workspaceFolderSetup";

const WS = "11111111-1111-4111-8111-111111111111";

const ok = (payload: unknown): BridgeAnswer => ({ ok: true, response: { payload } }) as unknown as BridgeAnswer;
const refused = (code: string): BridgeAnswer =>
  ({ ok: false, error: { code, component: "workspace", message: "x", retryable: false, correlation_id: null, details: {} } }) as unknown as BridgeAnswer;

describe("workspace folder setup", () => {
  it("initializes and indexes a new memory folder from the folder config", async () => {
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
    const root = document.createElement("div");
    document.body.append(root);
    await renderFolderSetup(root, platform, WS);
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
    const save = calls.find((call) => call.command === "workspace.save_config")?.payload as {
      config: { knowledge: { content_root: string } };
    };
    expect(save.config.knowledge.content_root).toBe("vault");
  });

  it("asks for no memory path and keeps an existing folder memory", async () => {
    const calls: Array<{ command: string; payload: Record<string, unknown> }> = [];
    const platform = fakeDesktop({
      request: (async (command: string, payload: Record<string, unknown>) => {
        calls.push({ command, payload });
        if (command === "knowledge.status") {
          return ok({ workspace_id: WS, state: "unavailable", canonical_source: "markdown_files", integrations: [] });
        }
        if (command === "workspace.get_config") {
          return ok({
            schema_version: 1,
            workspace_id: WS,
            roots: { workspace_root: "C:\\Projects\\demo", repo_roots: [] },
            features: {},
            knowledge: { provider_id: "markdown-files", content_root: "notes/memoire" },
            updated_at: "2026-09-22T00:00:00Z",
          });
        }
        if (command === "workspace.save_config") return ok(payload.config);
        if (command === "knowledge.init_vault") {
          return ok({ workspace_id: WS, state_before: "ready", created: [], skipped: [] });
        }
        if (command === "knowledge.reindex") return ok({ accepted: true, operation_id: "op-2", state: "indexing" });
        return refused("not_supported");
      }) as never,
    });
    const root = document.createElement("div");
    document.body.append(root);
    await renderFolderSetup(root, platform, WS);
    const form = root.querySelector<HTMLFormElement>("[data-testid=memory-folder-form]")!;
    expect(form.querySelector("input")).toBeNull();
    expect(root.textContent).not.toMatch(/MCP|démon|Graphify|Vault|UUID|sidecar|chemin/i);
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 20));
    const save = calls.find((call) => call.command === "workspace.save_config")?.payload as {
      config: { knowledge: { content_root: string } };
    };
    expect(save.config.knowledge.content_root).toBe("notes/memoire");
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
    const root = document.createElement("div");
    document.body.append(root);
    await renderFolderSetup(root, platform, WS);
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
    const root = document.createElement("div");
    document.body.append(root);
    await renderFolderSetup(root, platform, WS);
    const form = root.querySelector<HTMLFormElement>("[data-testid=memory-folder-form]")!;
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]")!;
    expect(submit.disabled).toBe(true);
    expect(submit.textContent).toContain("Activation en cours");
    release();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(root.textContent).toContain("L'activation de la mémoire a échoué");
  });

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
          await new Promise((resolve) => setTimeout(resolve, 5));
          configured = true;
          return ok({ state: "configured", error: null });
        }
        return refused("not_supported");
      }) as never,
    });
    const root = document.createElement("div");
    document.body.append(root);
    await renderFolderSetup(root, platform, WS);
    root.querySelector<HTMLButtonElement>("[data-action=preview]")!.click();
    await new Promise((resolve) => setTimeout(resolve, 10));
    const apply = root.querySelector<HTMLButtonElement>("[data-action=apply-plan]")!;
    apply.click();
    apply.click();
    expect(apply.disabled).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(commands.filter((c) => c === "harness.apply")).toHaveLength(1);
    expect(root.textContent).toContain("Configuration appliquée");
    expect(root.querySelector('[data-harness="claude-code"]')?.getAttribute("data-state")).toBe("configured");
  });
});
