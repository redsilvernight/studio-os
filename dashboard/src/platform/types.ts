/**
 * The Dashboard's only view of "where it runs". Views depend on this, never on
 * Tauri: a web build and a Desktop build differ only by which adapter answers.
 */
import type { BridgeCommand, BridgeAnswer } from "./contracts";
import type { DaemonStatus, IdentityView, PeerInfo } from "./generated/local-contracts.generated";

export type PlatformMode = "web" | "desktop";

/** What the Rust shell reports about itself (`desktop_info`). */
export interface DesktopInfo {
  product: string;
  desktop_version: string;
  mode: "desktop";
  protocol: string;
  /** The Desktop's P1 `PeerInfo`, sent verbatim in `runtime.handshake`. */
  peer?: PeerInfo;
  sidecar:
    | { state: "not_started" }
    | { state: "running"; pid: number }
    | { state: "exited"; code: number | null }
    | { state: "recovering"; attempts: number }
    | { state: "abandoned"; attempts: number }
    | { state: "unavailable" };
}

/** State of the user-configurable server origin (Desktop shell setting). */
export interface ServerOriginState {
  /** The user-configured origin; `null` when the build default applies. */
  configured: string | null;
  /** The user origin this process allowed at start; the only one callable now. */
  applied: string | null;
  /** The saved value is not the one this process allowed yet: relaunch to apply. */
  restart_required: boolean;
}

/** Why the shell refused a server origin (machine codes; the UI words them). */
export type ServerOriginRefusal =
  | "origin_empty"
  | "origin_too_long"
  | "origin_invalid"
  | "origin_unsupported_scheme"
  | "origin_credentials_not_allowed"
  | "origin_not_an_origin"
  | "origin_insecure_scheme"
  | "origin_is_desktop_origin"
  | "storage_unavailable"
  | "storage_failed"
  | "unavailable"
  | "failed";

export type SetServerOriginResult =
  | { ok: true; state: ServerOriginState }
  | { ok: false; reason: ServerOriginRefusal };

export interface PickerOptions {
  title?: string;
  /** File picker only: plain alphanumeric extensions, no wildcard. */
  filters?: { name: string; extensions: string[] }[];
}

/**
 * Outcome of a native selection. The renderer only ever receives what the user
 * explicitly chose (never file contents or a listing). `unavailable` = no
 * native picker in this runtime (web); it is never a fake selection.
 */
export type PickResult =
  | { status: "selected"; path: string; display_name: string }
  | { status: "cancelled" }
  | { status: "unavailable" }
  | { status: "error"; code: string };

/** Data-format marker state of the daemon data directory. */
export type DataFormatState =
  | { state: "unstamped" }
  | { state: "supported"; format: number }
  | { state: "too_new"; format: number; supported: number }
  | { state: "unreadable" };

/** What the shell reports about its installation (no secret, home directory masked). */
export interface DesktopDiagnostics {
  desktop_version: string;
  protocol: string;
  os: string;
  arch: string;
  sidecar: {
    state: DesktopInfo["sidecar"];
    present: boolean;
    manifest: { daemon_version: string; desktop_version: string; protocol: string } | null;
    compat: "compatible" | "version_drift" | "protocol_mismatch" | "unknown";
  };
  server_origin: string | null;
  updates_configured: boolean;
  locations: {
    daemon_data_dir: string | null;
    logs_dir: string | null;
    shell_settings_dir: string | null;
    install_dir: string | null;
    data_format: DataFormatState;
    logs: { name: string; bytes: number }[];
  };
}

export type DataFolder = "logs" | "diagnostics";

export type DiagnosticsExportResult = { ok: true; file: string } | { ok: false; code: string };

export type UpdateStatus =
  | { state: "not_configured" }
  | { state: "up_to_date"; current: string }
  | { state: "available"; current: string; version: string; notes: string | null };

export type UpdateErrorCode =
  | "not_configured"
  | "network"
  | "invalid_metadata"
  | "invalid_signature"
  | "install_failed"
  | "failed";

export type UpdateCheckResult = { ok: true; status: UpdateStatus } | { ok: false; code: UpdateErrorCode };

export interface Platform {
  readonly mode: PlatformMode;
  /** Which native controls this runtime really has (all false on the web). */
  readonly native: {
    readonly serverOrigin: boolean;
    readonly pickers: boolean;
    readonly diagnostics: boolean;
    readonly updates: boolean;
  };
  /** `null` in web mode: there is no Desktop to describe. */
  desktopInfo(): Promise<DesktopInfo | null>;
  /** Typed local bridge. Web mode answers `not_supported`, never a fake success. */
  request(command: BridgeCommand, payload?: Record<string, unknown>): Promise<BridgeAnswer>;
  /** The user-configured server origin. `null` in web mode (set at build time). */
  serverOrigin(): Promise<ServerOriginState | null>;
  /** Validate (in the shell) and save; `null` restores the build default. */
  setServerOrigin(origin: string | null): Promise<SetServerOriginResult>;
  /** Relaunch the Desktop app. Resolves `false` where it is not available. */
  restartDesktop(): Promise<boolean>;
  chooseFolder(options?: PickerOptions): Promise<PickResult>;
  chooseFile(options?: PickerOptions): Promise<PickResult>;
  /** Versions, sidecar state and data locations. `null` in web mode. */
  diagnostics(): Promise<DesktopDiagnostics | null>;
  /** Write the redacted diagnostics file; the shell chooses the destination. */
  exportDiagnostics(): Promise<DiagnosticsExportResult>;
  /** Reveal the logs or the exported diagnostics folder. Resolves `false` where unavailable. */
  openDataFolder(folder: DataFolder): Promise<boolean>;
  /** User-driven update check; nothing checks on its own. */
  checkForUpdate(): Promise<UpdateCheckResult>;
  /** Download the release found by `checkForUpdate`, verify it, install and restart. */
  installUpdate(): Promise<{ ok: true } | { ok: false; code: UpdateErrorCode }>;
}

export type { DaemonStatus, IdentityView };
