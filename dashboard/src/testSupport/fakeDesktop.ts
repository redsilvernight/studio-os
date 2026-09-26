import type { BridgeAnswer } from "../platform/contracts";
import type { DaemonRunState, PeerInfo } from "../platform/generated/local-contracts.generated";
import type { BridgeCommand } from "../platform/contracts";
import type { DesktopDiagnostics, Platform, ServerOriginState } from "../platform";

/** A Desktop `PeerInfo` shaped like the Rust one (health optional, never required). */
export const PEER = {
  role: "desktop",
  protocol_id: "studio.local",
  protocol: { minimum: { major: 1, minor: 0 }, maximum: { major: 1, minor: 0 } },
  component_version: "0.1.0",
  server_origin: null,
  capabilities: [
    "daemon.control",
    "identity.view",
    "daemon.health",
    "workspace.config",
    "knowledge.read",
    "knowledge.graph",
    "knowledge.index",
    "knowledge.init",
    "code_graph.read",
    "code_graph.graph",
    "code_graph.index",
    "harness.read",
    "harness.plan",
    "harness.apply",
  ],
  required_capabilities: ["daemon.control", "identity.view"],
  optional_capabilities: [
    "daemon.health",
    "workspace.config",
    "knowledge.read",
    "knowledge.graph",
    "knowledge.index",
    "knowledge.init",
    "code_graph.read",
    "code_graph.graph",
    "code_graph.index",
    "harness.read",
    "harness.plan",
    "harness.apply",
  ],
  optional_components: [],
} as unknown as PeerInfo;

export const INFO = {
  product: "Studi'OS Desktop",
  desktop_version: "0.1.0",
  mode: "desktop" as const,
  protocol: "studio.local/v1",
  peer: PEER,
  sidecar: { state: "not_started" as const },
};
export const DIAGNOSTICS: DesktopDiagnostics = {
  desktop_version: "0.1.0",
  protocol: "studio.local/v1",
  os: "windows",
  arch: "x86_64",
  sidecar: {
    state: { state: "not_started" },
    present: true,
    manifest: { daemon_version: "0.1.0", desktop_version: "0.1.0", protocol: "studio.local/v1" },
    compat: "compatible",
  },
  server_origin: "https://studio.example.com",
  updates_configured: false,
  locations: {
    daemon_data_dir: "~\\AppData\\Roaming\\StudioOS",
    logs_dir: "~\\AppData\\Roaming\\StudioOS\\logs",
    shell_settings_dir: "~\\AppData\\Roaming\\dev.studio-os.desktop",
    install_dir: "~\\AppData\\Local\\Programs\\Studio OS Desktop",
    data_format: { state: "supported", format: 1 },
    logs: [{ name: "daemon.log", bytes: 2048 }],
  },
};
export const notSupported = { ok: false, error: { code: "not_supported" } } as unknown as BridgeAnswer;

export function fakeDesktop(over: Partial<Platform> = {}, origin: ServerOriginState | null = null): Platform {
  return {
    mode: "desktop",
    native: { serverOrigin: true, pickers: true, diagnostics: true, updates: true },
    desktopInfo: async () => INFO,
    request: async () => notSupported,
    serverOrigin: async () => origin ?? { configured: null, applied: null, restart_required: false },
    setServerOrigin: async () => ({ ok: false, reason: "failed" }),
    restartDesktop: async () => true,
    chooseFolder: async () => ({ status: "cancelled" }),
    chooseFile: async () => ({ status: "cancelled" }),
    diagnostics: async () => DIAGNOSTICS,
    exportDiagnostics: async () => ({ ok: true, file: "~\\AppData\\Roaming\\StudioOS\\diagnostics\\diagnostics-1.json" }),
    openDataFolder: async () => true,
    checkForUpdate: async () => ({ ok: true, status: { state: "not_configured" } }),
    installUpdate: async () => ({ ok: false, code: "not_configured" }),
    ...over,
  };
}


const ok = (command: BridgeCommand, payload: unknown): BridgeAnswer =>
  ({ ok: true, command, response: { payload } }) as unknown as BridgeAnswer;
const fail = (code: string): BridgeAnswer => ({ ok: false, error: { code } }) as unknown as BridgeAnswer;

export interface FakeDaemonOptions {
  state?: DaemonRunState;
  /** Capabilities the daemon offers (a P2-only daemon has no `daemon.health`). */
  offers?: string[];
  /** Refuse the handshake with this outcome (e.g. `protocol_incompatible`). */
  refuse?: string;
  git_watchers?: { condition: string }[];
}

/**
 * A daemon that behaves like the P4 `BridgeService`: a command whose capability
 * was not negotiated answers `capability_missing`, and the grant is forgotten
 * by `restart()`. `calls` records every command in order.
 */
export function fakeDaemon(options: FakeDaemonOptions = {}) {
  const offers = options.offers ?? ["daemon.control", "daemon.health", "identity.view"];
  let granted = new Set<string>();
  const calls: BridgeCommand[] = [];
  const request = async (command: BridgeCommand): Promise<BridgeAnswer> => {
    calls.push(command);
    if (command === "runtime.handshake") {
      if (options.refuse) {
        return ok(command, { outcome: options.refuse, daemon: {}, granted_capabilities: [] });
      }
      granted = new Set(offers.filter((c) => PEER.capabilities?.includes(c)));
      const complete = offers.includes("daemon.health");
      return ok(command, {
        outcome: complete ? "compatible" : "compatible_degraded",
        daemon: {},
        granted_capabilities: [...granted],
        // Same rule as the P1 `negotiate`: an optional capability the daemon
        // does not know at all means an older daemon to update.
        missing_optional: complete ? [] : ["daemon.health"],
        remediation: complete ? "none" : "update_daemon",
      });
    }
    const needs = command === "daemon.health" ? "daemon.health" : "daemon.control";
    if (!granted.has(needs)) return fail("capability_missing");
    if (command === "daemon.status") return ok(command, { action: "status", outcome: "ok", status: { state: options.state ?? "running" } });
    if (command === "daemon.health") {
      const svc = (service: string, condition = "healthy") => ({ service, condition, state: "ready" });
      return ok(command, {
        status: { state: options.state ?? "running" },
        heartbeat: svc("heartbeat"),
        outbox_replay: svc("outbox_replay"),
        git_watchers: (options.git_watchers ?? []).map((w) => svc("git_watcher", w.condition)),
        observed_at: "2026-09-21T10:00:00Z",
      });
    }
    return fail("not_supported");
  };
  return { request, calls, restart: () => (granted = new Set()) };
}
