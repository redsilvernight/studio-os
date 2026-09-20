import type { BridgeAnswer } from "./contracts";
import type { Platform } from "./types";

/** Browser build: no Desktop, no local bridge, no pretending otherwise. */
export const webPlatform: Platform = {
  mode: "web",
  async desktopInfo() {
    return null;
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
