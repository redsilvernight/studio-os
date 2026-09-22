import type { BridgeAnswer } from "./contracts";
import type { Platform, SetServerOriginResult } from "./types";

/** Browser build: no Desktop, no local bridge, no pretending otherwise. */
export const webPlatform: Platform = {
  mode: "web",
  native: { serverOrigin: false, pickers: false, diagnostics: false, updates: false },
  async desktopInfo() {
    return null;
  },
  async serverOrigin() {
    return null;
  },
  async setServerOrigin(): Promise<SetServerOriginResult> {
    return { ok: false, reason: "unavailable" };
  },
  async restartDesktop() {
    return false;
  },
  async chooseFolder() {
    return { status: "unavailable" };
  },
  async chooseFile() {
    return { status: "unavailable" };
  },
  async diagnostics() {
    return null;
  },
  async exportDiagnostics() {
    return { ok: false, code: "unavailable" };
  },
  async openDataFolder() {
    return false;
  },
  async checkForUpdate() {
    return { ok: false, code: "not_configured" };
  },
  async installUpdate() {
    return { ok: false, code: "not_configured" };
  },
  async request(): Promise<BridgeAnswer> {
    return {
      ok: false,
      error: {
        code: "not_supported",
        component: "desktop",
        message: "The local bridge is only available in Studi'OS Desktop.",
        retryable: false,
        correlation_id: null,
        details: {},
      },
    };
  },
};
