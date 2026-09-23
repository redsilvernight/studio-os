/**
 * Desktop shell UX (P3): server origin, connection state, daemon summary.
 *
 * Everything here runs only when the platform adapter is `desktop`
 * (`prepareDesktop` is a no-op otherwise), so the web Dashboard keeps its
 * exact behaviour. It consumes the P1 `studio.local/v1` contract through the
 * `Platform` adapter and owns no daemon lifecycle (P4) and no workspace
 * concept (P5): it only *shows* what the contracts report.
 */
import { apiBaseUrl } from "./api";
import { setApiObserver } from "./apiEvents";
import { joinUrl } from "./config";
import { createConnectionMonitor, type ConnectionMonitor, type ConnectionSnapshot } from "./connection";
import type { DesktopInfo, Platform, ServerOriginState } from "./platform";
import { setServerOriginOverride } from "./runtimeConfig";
import type { HandshakeResponse } from "./platform/generated/local-contracts.generated";
import {
  DAEMON_ABANDONED,
  DAEMON_RECOVERING,
  shellStatusHtml,
  summarizeDaemonAnswer,
  summarizeHealth,
  summarizeShellStatus,
  type CompatibilityState,
  type DaemonSummary,
  type ShellStatus,
} from "./shellStatus";

const DEFAULT_PROFILE_ID = "default";
const PROBE_TIMEOUT_MS = 5000;

export interface DesktopShellHooks {
  /** Repaint the current view (the server came back). */
  rerender(): void;
  /** The signed-in session was refused: leave the app for the login screen. */
  authExpired(): void;
}

export interface DesktopShell {
  readonly platform: Platform;
  readonly monitor: ConnectionMonitor;
  info: DesktopInfo | null;
  infoFailure: string | null;
  compatibility: CompatibilityState;
  origin: ServerOriginState | null;
  daemon: DaemonSummary;
  hooks: DesktopShellHooks | null;
}

let shell: DesktopShell | null = null;

/** The Desktop shell, or `null` on the web / before `prepareDesktop`. */
export function getDesktopShell(): DesktopShell | null {
  return shell;
}

export function setDesktopHooks(hooks: DesktopShellHooks): void {
  if (shell) shell.hooks = hooks;
}

async function probeHealth(): Promise<number> {
  // Without a server address a relative URL would hit the Desktop origin
  // itself (tauri.localhost), which is never a server: report it as unreachable.
  if (apiBaseUrl() === "") throw new TypeError("no server address configured");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const response = await globalThis.fetch(joinUrl(apiBaseUrl(), "/healthz"), {
      method: "GET",
      cache: "no-store",
      signal: controller.signal,
    });
    return response.status;
  } finally {
    clearTimeout(timer);
  }
}

/** Load identity, compatibility and the user server origin. Never throws. */
async function loadIdentity(target: DesktopShell): Promise<void> {
  try {
    target.info = await target.platform.desktopInfo();
    target.infoFailure = null;
    target.compatibility = "ok";
  } catch (error) {
    target.info = null;
    target.infoFailure = error instanceof Error ? error.message : "identité illisible";
    // The only thing desktopInfo() refuses on purpose is a protocol mismatch.
    target.compatibility = /expects/.test(target.infoFailure) ? "incompatible" : "unknown";
  }
  try {
    target.origin = await target.platform.serverOrigin();
  } catch {
    target.origin = null;
  }
  // Only the origin this process allowed in its CSP is callable now.
  setServerOriginOverride(target.origin?.applied ?? null);
}

/**
 * Negotiate the local protocol with the daemon. The daemon forgets granted
 * capabilities when it restarts, so this runs before every read instead of
 * being cached: a stale grant would turn into `capability_missing`.
 */
async function negotiate(target: DesktopShell): Promise<
  { ok: true; granted: Set<string> } | { ok: false; summary: DaemonSummary }
> {
  const peer = target.info?.peer;
  if (!peer) return { ok: false, summary: { kind: "unknown" } };
  const answer = await target.platform.request("runtime.handshake", { peer });
  if (!answer.ok) return { ok: false, summary: summarizeDaemonAnswer(answer) };
  const reply = answer.response.payload as unknown as HandshakeResponse;
  if (reply.outcome !== "compatible" && reply.outcome !== "compatible_degraded") {
    // A refused handshake is a version/capability incompatibility, shown as such.
    return { ok: false, summary: { kind: "error", code: "protocol_incompatible" } };
  }
  return { ok: true, granted: new Set(reply.granted_capabilities ?? []) };
}

/** The supervisor's own view, used when the daemon cannot answer. */
function supervisorSummary(target: DesktopShell, code: string): DaemonSummary {
  const sidecar = target.info?.sidecar.state;
  if (sidecar === "abandoned") return { kind: "error", code: DAEMON_ABANDONED };
  if (sidecar === "recovering") return { kind: "error", code: DAEMON_RECOVERING };
  return { kind: "error", code };
}

/**
 * Read the P1 `daemon.status` and, when the daemon offers it, the additive P4
 * `daemon.health` (read-only). Skipped without an effective server origin.
 * `daemon.health` is only asked for when negotiated: an older daemon answers
 * `capability_missing` to it, which is a normal degraded state, not an error.
 */
export async function refreshDaemon(target: DesktopShell | null = shell): Promise<DaemonSummary> {
  if (!target || target.compatibility === "incompatible") return { kind: "unknown" };
  const serverOrigin = apiBaseUrl();
  if (serverOrigin === "") {
    target.daemon = { kind: "unknown" };
    return target.daemon;
  }
  const profile = { profile_id: DEFAULT_PROFILE_ID, server_origin: serverOrigin };
  try {
    target.info = await target.platform.desktopInfo();
  } catch {
    // Keep the previous identity: the supervisor state is a best effort here.
  }
  const negotiated = await negotiate(target);
  if (!negotiated.ok) {
    target.daemon =
      negotiated.summary.kind === "error" ? supervisorSummary(target, negotiated.summary.code) : negotiated.summary;
    paintShellStatus();
    return target.daemon;
  }
  const answer = await target.platform.request("daemon.status", { action: "status", profile });
  const summary = summarizeDaemonAnswer(answer);
  if (summary.kind === "error") {
    target.daemon = supervisorSummary(target, summary.code);
  } else if (summary.kind === "state" && negotiated.granted.has("daemon.health")) {
    const health = await target.platform.request("daemon.health", { profile });
    target.daemon = {
      ...summary,
      health: health.ok ? summarizeHealth(health.response.payload as never) : null,
    };
  } else {
    target.daemon = summary;
  }
  paintShellStatus();
  return target.daemon;
}

/**
 * Prepare the Desktop shell before the first render. Resolves quickly: the
 * first `/healthz` probe and the daemon read continue in the background.
 */
export async function prepareDesktop(platform: Platform): Promise<DesktopShell | null> {
  if (platform.mode !== "desktop") return null;
  const monitor = createConnectionMonitor({
    probe: probeHealth,
    schedule: (callback, delay) => {
      const id = setTimeout(callback, delay);
      return () => clearTimeout(id);
    },
  });
  const created: DesktopShell = {
    platform,
    monitor,
    info: null,
    infoFailure: null,
    compatibility: "unknown",
    origin: null,
    daemon: { kind: "unknown" },
    hooks: null,
  };
  shell = created;
  await loadIdentity(created);

  let previous = monitor.snapshot().state;
  monitor.subscribe((snapshot) => {
    const was = previous;
    previous = snapshot.state;
    paintShellStatus();
    if (snapshot.state === "auth_expired") created.hooks?.authExpired();
    if (was === "unreachable" && snapshot.state === "connected") {
      void refreshDaemon(created);
      created.hooks?.rerender();
    }
  });
  setApiObserver({
    // Desktop has no same-origin API. Decided on the effective server address,
    // not on the URL: a Request object already resolved a relative path
    // against tauri.localhost by the time it reaches us.
    refuse: () => apiBaseUrl() === "",
    reachable: () => monitor.reportReachable(),
    networkError: () => monitor.reportNetworkError(),
    unauthorized: () => monitor.reportUnauthorized(),
  });
  void monitor.check().then(() => refreshDaemon(created));
  return created;
}

export function currentStatus(target: DesktopShell | null = shell): ShellStatus | null {
  if (!target) return null;
  return summarizeShellStatus({
    connection: target.monitor.snapshot(),
    daemon: target.daemon,
    compatibility: target.compatibility,
    restartRequired: target.origin?.restart_required ?? false,
  });
}

/** (Re)paint the status pill next to the account state. Desktop only. */
export function paintShellStatus(root: ParentNode = document): void {
  const status = currentStatus();
  if (!status) return;
  const topbar = root.querySelector(".app-topbar");
  if (!topbar) return;
  const html = shellStatusHtml(status);
  const existing = topbar.querySelector("#shell-status");
  if (existing) {
    const holder = document.createElement("template");
    holder.innerHTML = html;
    const next = holder.content.firstElementChild;
    if (next) existing.replaceWith(next);
    return;
  }
  const anchor = topbar.querySelector("#token-state");
  const holder = document.createElement("template");
  holder.innerHTML = html;
  const pill = holder.content.firstElementChild;
  if (!pill) return;
  if (anchor) anchor.before(pill);
  else topbar.append(pill);
}

export function serverSnapshot(target: DesktopShell | null = shell): ConnectionSnapshot | null {
  return target ? target.monitor.snapshot() : null;
}

/** Test seam: forget the module state. */
export function resetDesktopShellForTests(): void {
  shell?.monitor.stop();
  shell = null;
  setApiObserver(null);
  setServerOriginOverride(null);
}
