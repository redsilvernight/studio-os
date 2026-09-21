/**
 * The Dashboard's only view of "where it runs". Views depend on this, never on
 * Tauri: a web build and a Desktop build differ only by which adapter answers.
 */
import type { BridgeCommand, BridgeAnswer } from "./contracts";
import type { DaemonStatus, IdentityView } from "./generated/local-contracts.generated";

export type PlatformMode = "web" | "desktop";

/** What the Rust shell reports about itself (`desktop_info`). */
export interface DesktopInfo {
  product: string;
  desktop_version: string;
  mode: "desktop";
  protocol: string;
  sidecar:
    | { state: "not_started" }
    | { state: "running"; pid: number }
    | { state: "exited"; code: number | null }
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

export interface Platform {
  readonly mode: PlatformMode;
  /** Which native controls this runtime really has (all false on the web). */
  readonly native: { readonly serverOrigin: boolean; readonly pickers: boolean };
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
}

export type { DaemonStatus, IdentityView };
