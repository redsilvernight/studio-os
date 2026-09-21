/**
 * One simple Desktop status, with details on demand.
 *
 * The shell shows a single pill (« Connecté », « Serveur injoignable »…) and
 * leaves the detail to Settings › Application. This module only summarises
 * states the contracts already define; it never invents a daemon or provider
 * state. Priority (first match wins): protocol incompatible, server
 * unreachable, session expired, daemon unavailable, restart pending, connected.
 */
import type { BridgeAnswer } from "./platform/contracts";
import type { DaemonRunState } from "./platform/generated/local-contracts.generated";
import type { ConnectionSnapshot } from "./connection";
import { esc } from "./ui";

export type CompatibilityState = "ok" | "incompatible" | "unknown";

/** What the local daemon reported (P1 `daemon.status`), or why it could not. */
export type DaemonSummary =
  | { kind: "unknown" }
  | { kind: "state"; state: DaemonRunState }
  | { kind: "error"; code: string };

export type StatusLevel = "ok" | "info" | "warn" | "error";
export type StatusReason =
  | "protocol_incompatible"
  | "server_unreachable"
  | "auth_expired"
  | "daemon_unavailable"
  | "restart_required"
  | "connecting"
  | "connected";

export interface ShellStatus {
  level: StatusLevel;
  reason: StatusReason;
  label: string;
}

export interface ShellStatusInput {
  connection: ConnectionSnapshot;
  daemon: DaemonSummary;
  compatibility: CompatibilityState;
  restartRequired: boolean;
}

const DAEMON_STATE_LABEL: Record<DaemonRunState, string> = {
  stopped: "Arrêté",
  starting: "Démarrage",
  running: "En marche",
  stopping: "Arrêt en cours",
  recovering: "Reprise en cours",
  crashed: "Arrêté de façon inattendue",
  unavailable: "Indisponible",
  incompatible: "Version incompatible",
};

export function summarizeDaemonAnswer(answer: BridgeAnswer): DaemonSummary {
  if (!answer.ok) return { kind: "error", code: answer.error.code };
  const payload = answer.response.payload as { state?: unknown };
  const state = payload.state;
  if (typeof state === "string" && state in DAEMON_STATE_LABEL) {
    return { kind: "state", state: state as DaemonRunState };
  }
  return { kind: "unknown" };
}

export function daemonLabel(daemon: DaemonSummary): string {
  switch (daemon.kind) {
    case "state":
      return DAEMON_STATE_LABEL[daemon.state];
    case "error":
      if (daemon.code === "not_supported") return "Non disponible dans cette version";
      if (daemon.code === "daemon_unavailable") return "Indisponible";
      if (daemon.code === "daemon_crashed") return "Arrêté de façon inattendue";
      if (daemon.code === "protocol_incompatible") return "Version incompatible";
      if (daemon.code === "feature_disabled") return "Désactivé";
      return "Erreur";
    default:
      return "Inconnu";
  }
}

/** Does the daemon summary deserve the user's attention? `not_supported` does not. */
export function daemonNeedsAttention(daemon: DaemonSummary): boolean {
  if (daemon.kind === "state") {
    return daemon.state === "unavailable" || daemon.state === "crashed" || daemon.state === "incompatible";
  }
  if (daemon.kind === "error") return daemon.code !== "not_supported" && daemon.code !== "feature_disabled";
  return false;
}

function daemonIncompatible(daemon: DaemonSummary): boolean {
  return (
    (daemon.kind === "state" && daemon.state === "incompatible") ||
    (daemon.kind === "error" && daemon.code === "protocol_incompatible")
  );
}

export function summarizeShellStatus(input: ShellStatusInput): ShellStatus {
  if (input.compatibility === "incompatible" || daemonIncompatible(input.daemon)) {
    return { level: "error", reason: "protocol_incompatible", label: "Version incompatible" };
  }
  if (input.connection.state === "unreachable") {
    return { level: "error", reason: "server_unreachable", label: "Serveur injoignable" };
  }
  if (input.connection.state === "auth_expired") {
    return { level: "warn", reason: "auth_expired", label: "Session expirée" };
  }
  if (daemonNeedsAttention(input.daemon)) {
    return { level: "warn", reason: "daemon_unavailable", label: "Assistant local indisponible" };
  }
  if (input.restartRequired) {
    return { level: "info", reason: "restart_required", label: "Redémarrage requis" };
  }
  if (input.connection.state === "connected") {
    return { level: "ok", reason: "connected", label: "Connecté" };
  }
  return { level: "info", reason: "connecting", label: "Connexion…" };
}

/** The pill: a link to the detail page, never an alarm bell. */
export function shellStatusHtml(status: ShellStatus): string {
  return (
    `<a class="app-status app-status--${status.level}" id="shell-status" data-testid="shell-status" ` +
    `data-reason="${status.reason}" href="#/configuration/application" role="status">` +
    `<span class="app-status-dot" aria-hidden="true"></span>${esc(status.label)}</a>`
  );
}

export function serverStateLabel(connection: ConnectionSnapshot): string {
  switch (connection.state) {
    case "connected":
      return "Joignable";
    case "unreachable":
      return connection.detail && connection.detail.startsWith("http_")
        ? `Réponse inattendue (${connection.detail.slice(5)})`
        : "Injoignable";
    case "auth_expired":
      return "Joignable · session expirée";
    case "connecting":
      return "Vérification…";
    default:
      return "Non vérifié";
  }
}
