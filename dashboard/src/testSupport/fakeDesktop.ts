import type { BridgeAnswer } from "../platform/contracts";
import type { Platform, ServerOriginState } from "../platform";

export const INFO = {
  product: "Studi'OS Desktop",
  desktop_version: "0.1.0",
  mode: "desktop" as const,
  protocol: "studio.local/v1",
  sidecar: { state: "not_started" as const },
};
export const notSupported = { ok: false, error: { code: "not_supported" } } as unknown as BridgeAnswer;

export function fakeDesktop(over: Partial<Platform> = {}, origin: ServerOriginState | null = null): Platform {
  return {
    mode: "desktop",
    native: { serverOrigin: true, pickers: true },
    desktopInfo: async () => INFO,
    request: async () => notSupported,
    serverOrigin: async () => origin ?? { configured: null, applied: null, restart_required: false },
    setServerOrigin: async () => ({ ok: false, reason: "failed" }),
    restartDesktop: async () => true,
    chooseFolder: async () => ({ status: "cancelled" }),
    chooseFile: async () => ({ status: "cancelled" }),
    ...over,
  };
}

