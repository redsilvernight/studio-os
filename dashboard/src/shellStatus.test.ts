import { describe, expect, it } from "vitest";
import type { BridgeAnswer } from "./platform/contracts";
import type { ConnectionSnapshot } from "./connection";
import {
  daemonLabel,
  daemonNeedsAttention,
  serverStateLabel,
  shellStatusHtml,
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

  it("words the server state", () => {
    expect(serverStateLabel(conn("connected"))).toBe("Joignable");
    expect(serverStateLabel(conn("unreachable", "network"))).toBe("Injoignable");
    expect(serverStateLabel(conn("unreachable", "http_503"))).toBe("Réponse inattendue (503)");
    expect(serverStateLabel(conn("auth_expired"))).toContain("session expirée");
  });
});
