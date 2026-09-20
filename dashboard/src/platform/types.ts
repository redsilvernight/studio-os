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

export interface Platform {
  readonly mode: PlatformMode;
  /** `null` in web mode: there is no Desktop to describe. */
  desktopInfo(): Promise<DesktopInfo | null>;
  /** Typed local bridge. Web mode answers `not_supported`, never a fake success. */
  request(command: BridgeCommand, payload?: Record<string, unknown>): Promise<BridgeAnswer>;
}

export type { DaemonStatus, IdentityView };
