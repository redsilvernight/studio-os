/**
 * Desktop adapter — the ONLY module that touches the Tauri runtime.
 *
 * It reaches the two app commands the shell exposes (`desktop_info`,
 * `bridge_request`) through the global injected by Tauri; no `@tauri-apps/*`
 * package is imported, so the web bundle has no Tauri dependency at all.
 */
import { buildRequest, parseAnswer, type BridgeAnswer, type BridgeCommand } from "./contracts";
import { LOCAL_PROTOCOL } from "./generated/local-contracts.generated";
import type { DesktopInfo, Platform } from "./types";

export type TauriInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

interface TauriGlobal {
  core?: { invoke?: unknown };
}

/** The injected invoke function, or `null` outside the Desktop shell. */
export function detectTauriInvoke(scope: unknown = globalThis): TauriInvoke | null {
  const tauri = (scope as { __TAURI__?: TauriGlobal }).__TAURI__;
  const invoke = tauri?.core?.invoke;
  return typeof invoke === "function" ? (invoke as TauriInvoke) : null;
}

function failure(code: "daemon_unavailable" | "internal_error", message: string): BridgeAnswer {
  return {
    ok: false,
    error: { code, component: "bridge", message, retryable: code === "daemon_unavailable", correlation_id: null, details: {} },
  };
}

function isDesktopInfo(v: unknown): v is DesktopInfo {
  const o = v as Partial<DesktopInfo> | null;
  return (
    typeof o === "object" &&
    o !== null &&
    o.mode === "desktop" &&
    typeof o.product === "string" &&
    typeof o.desktop_version === "string" &&
    typeof o.protocol === "string" &&
    typeof o.sidecar === "object" &&
    o.sidecar !== null
  );
}

export function createDesktopPlatform(invoke: TauriInvoke): Platform {
  return {
    mode: "desktop",
    async desktopInfo() {
      const info = await invoke("desktop_info");
      if (!isDesktopInfo(info)) throw new Error("desktop_info answered an unexpected shape");
      // Incompatible protocol: fail closed, do not present a half-working Desktop.
      if (info.protocol !== LOCAL_PROTOCOL) {
        throw new Error(`Desktop speaks ${info.protocol}, the Dashboard expects ${LOCAL_PROTOCOL}`);
      }
      return info;
    },
    async request(command: BridgeCommand, payload: Record<string, unknown> = {}) {
      const request = buildRequest(command, payload);
      try {
        return parseAnswer(request, await invoke("bridge_request", { request }));
      } catch {
        // The shell rejected or lost the call: a typed error, no raw exception text.
        return failure("internal_error", "The Desktop shell did not answer the request.");
      }
    },
  };
}
