import { describe, expect, it } from "vitest";
import type { BridgeAnswer } from "./platform/contracts";
import type { ConnectionSnapshot } from "./connection";
import {
  daemonLabel,
  daemonNeedsAttention,
  serverStateLabel,
  shellConnectionView,
  shellStatusHtml,
  statusAction,
  statusDetail,
  summarizeDaemonAnswer,
  summarizeShellStatus,
  type DaemonSummary,
} from "./shellStatus";

const conn = (state: ConnectionSnapshot["state"], detail: string | null = null): ConnectionSnapshot => ({ state, detail });
const unknownDaemon: DaemonSummary = { kind: "unknown" };
const base = { connection: conn("connected"), daemon: unknownDaemon, compatibility: "ok" as const, restartRequired: false };

describe("summarizeShellStatus", () => {
  it("connected is the simple happy path", () => {
    expect(summarizeShellStatus(base)).toMatchObject({ reason: "connected", level: "ok", label: "Connecté" });
  });

  it("covers connecting, unreachable, expired, daemon unavailable, incompatible, restart", () => {
    expect(summarizeShellStatus({ ...base, connection: conn("connecting") }).reason).toBe("connecting");
    expect(summarizeShellStatus({ ...base, connection: conn("unknown") }).reason).toBe("connecting");
    expect(summarizeShellStatus({ ...base, connection: conn("unreachable", "network") }).reason).toBe("server_unreachable");
    expect(summarizeShellStatus({ ...base, connection: conn("auth_expired") }).reason).toBe("auth_expired");
    expect(summarizeShellStatus({ ...base, daemon: { kind: "error", code: "daemon_unavailable" } }).reason).toBe(
      "daemon_unavailable",
    );
    expect(summarizeShellStatus({ ...base, compatibility: "incompatible" }).reason).toBe("protocol_incompatible");
    expect(summarizeShellStatus({ ...base, restartRequired: true }).reason).toBe("restart_required");
  });

  it("priority: incompatible > unreachable > expired > daemon > restart > connected", () => {
    const everything = {
      connection: conn("unreachable", "network"),
      daemon: { kind: "error", code: "daemon_crashed" } as DaemonSummary,
      compatibility: "incompatible" as const,
      restartRequired: true,
    };
    expect(summarizeShellStatus(everything).reason).toBe("protocol_incompatible");
    expect(summarizeShellStatus({ ...everything, compatibility: "ok" }).reason).toBe("server_unreachable");
    expect(summarizeShellStatus({ ...everything, compatibility: "ok", connection: conn("auth_expired") }).reason).toBe(
      "auth_expired",
    );
    expect(summarizeShellStatus({ ...everything, compatibility: "ok", connection: conn("connected") }).reason).toBe(
      "daemon_unavailable",
    );
  });

  it("a daemon that reports an incompatible protocol counts as incompatible", () => {
    expect(summarizeShellStatus({ ...base, daemon: { kind: "state", state: "incompatible" } }).reason).toBe(
      "protocol_incompatible",
    );
    expect(summarizeShellStatus({ ...base, daemon: { kind: "error", code: "protocol_incompatible" } }).reason).toBe(
      "protocol_incompatible",
    );
  });

  it("`not_supported` (daemon not shipped yet) is not an alarm", () => {
    const daemon: DaemonSummary = { kind: "error", code: "not_supported" };
    expect(daemonNeedsAttention(daemon)).toBe(false);
    expect(daemonLabel(daemon)).toBe("Non disponible dans cette version");
    expect(summarizeShellStatus({ ...base, daemon }).reason).toBe("connected");
  });
});

describe("daemon summary consumes the P1 states without inventing any", () => {
  const ok = (state: string): BridgeAnswer =>
    ({ ok: true, command: "daemon.status", response: { payload: { action: "status", outcome: "ok", status: { state } } } }) as unknown as BridgeAnswer;

  it("keeps a P1 DaemonRunState and rejects anything else", () => {
    for (const s of ["stopped", "starting", "running", "stopping", "recovering", "crashed", "unavailable", "incompatible"]) {
      expect(summarizeDaemonAnswer(ok(s))).toEqual({ kind: "state", state: s });
    }
    expect(summarizeDaemonAnswer(ok("hovering"))).toEqual({ kind: "unknown" });
    for (const inherited of ["constructor", "toString", "__proto__", "hasOwnProperty", "valueOf"]) {
      expect(summarizeDaemonAnswer(ok(inherited)), inherited).toEqual({ kind: "unknown" });
    }
  });

  it("keeps the P1 error code of a failed answer", () => {
    const failed = { ok: false, error: { code: "daemon_unavailable" } } as unknown as BridgeAnswer;
    expect(summarizeDaemonAnswer(failed)).toEqual({ kind: "error", code: "daemon_unavailable" });
  });

  it("running and stopped need no attention; crashed does", () => {
    expect(daemonNeedsAttention({ kind: "state", state: "running" })).toBe(false);
    expect(daemonNeedsAttention({ kind: "state", state: "stopped" })).toBe(false);
    expect(daemonNeedsAttention({ kind: "state", state: "crashed" })).toBe(true);
  });
});

describe("rendering", () => {
  it("renders one accessible link to the details page, escaped", () => {
    const html = shellStatusHtml({ level: "warn", reason: "auth_expired", label: "Session <expirée>" });
    expect(html).toContain('href="#/configuration/application"');
    expect(html).toContain('role="status"');
    expect(html).toContain("&lt;expirée&gt;");
    expect(html).not.toContain("style=");
  });

  it("offers one explicit action per degraded state, none when it works or resolves alone", () => {
    expect(statusAction("server_unreachable")).toEqual({ kind: "retry", label: "Réessayer" });
    expect(statusAction("auth_expired")).toEqual({ kind: "reconnect", label: "Se reconnecter" });
    expect(statusAction("protocol_incompatible")?.kind).toBe("detail");
    expect(statusAction("daemon_unavailable")?.kind).toBe("detail");
    expect(statusAction("restart_required")?.kind).toBe("detail");
    expect(statusAction("connected")).toBeNull();
    expect(statusAction("connecting")).toBeNull();
    expect(statusAction("daemon_recovering")).toBeNull();
  });

  it("details server, local assistant and synchronisation separately", () => {
    const daemon: DaemonSummary = {
      kind: "state",
      state: "running",
      health: { heartbeat: "healthy", outboxReplay: "stale", gitWatchers: { total: 0, healthy: 0 }, observedAt: "x" },
    };
    expect(statusDetail(conn("connected"), daemon)).toBe(
      "Serveur : Joignable · Assistant local : En marche · Synchronisation : Données anciennes",
    );
    expect(statusDetail(conn("unreachable", "network"), unknownDaemon)).toBe(
      "Serveur : Injoignable · Assistant local : Inconnu",
    );
  });

  it("puts the detail in the tooltip and the action beside the status", () => {
    const status = { level: "error" as const, reason: "server_unreachable" as const, label: "Serveur injoignable" };
    const view = shellConnectionView(status, "Serveur : Injoignable");
    expect(view.title).toBe("Serveur injoignable — Serveur : Injoignable");
    const html = shellStatusHtml(status);
    expect(html).toContain('data-action="retry-status"');
    expect(html.match(/ id="connection-status"/g)).toHaveLength(1);
    expect(shellStatusHtml({ level: "ok", reason: "connected", label: "Connecté" })).not.toContain("connection-action");
  });

  it("words the server state", () => {
    expect(serverStateLabel(conn("connected"))).toBe("Joignable");
    expect(serverStateLabel(conn("unreachable", "network"))).toBe("Injoignable");
    expect(serverStateLabel(conn("unreachable", "http_503"))).toBe("Réponse inattendue (503)");
    expect(serverStateLabel(conn("auth_expired"))).toContain("session expirée");
  });
});
