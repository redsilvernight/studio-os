/**
 * Desktop adapter — the ONLY module that touches the Tauri runtime.
 *
 * It reaches the typed app commands the shell exposes (P2 `desktop_info`,
 * `bridge_request`; P3 `get_server_origin`, `set_server_origin`,
 * `restart_desktop`, `choose_folder`, `choose_file`) through the global
 * injected by Tauri; no `@tauri-apps/*` package is imported, so the web bundle
 * has no Tauri dependency at all. Every shell answer is shape-checked here.
 */
import { buildRequest, parseAnswer, type BridgeAnswer, type BridgeCommand } from "./contracts";
import { LOCAL_PROTOCOL } from "./generated/local-contracts.generated";
import type {
  DesktopInfo,
  PickerOptions,
  PickResult,
  Platform,
  ServerOriginRefusal,
  ServerOriginState,
  SetServerOriginResult,
} from "./types";

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

function isServerOriginState(v: unknown): v is ServerOriginState {
  const o = v as Partial<ServerOriginState> | null;
  return (
    typeof o === "object" &&
    o !== null &&
    (o.configured === null || typeof o.configured === "string") &&
    (o.applied === null || typeof o.applied === "string") &&
    typeof o.restart_required === "boolean"
  );
}

const REFUSALS: readonly ServerOriginRefusal[] = [
  "origin_empty",
  "origin_too_long",
  "origin_invalid",
  "origin_unsupported_scheme",
  "origin_credentials_not_allowed",
  "origin_not_an_origin",
  "origin_insecure_scheme",
  "origin_is_desktop_origin",
  "storage_unavailable",
  "storage_failed",
];

function refusalOf(error: unknown): ServerOriginRefusal {
  const code = (error as { code?: unknown } | null)?.code;
  return REFUSALS.find((r) => r === code) ?? "failed";
}

function toPickResult(answer: unknown): PickResult {
  const o = answer as Record<string, unknown> | null;
  if (o && o.status === "cancelled") return { status: "cancelled" };
  if (o && o.status === "selected" && typeof o.path === "string" && o.path && typeof o.display_name === "string") {
    return { status: "selected", path: o.path, display_name: o.display_name };
  }
  return { status: "error", code: "unexpected_answer" };
}

function pickErrorCode(error: unknown): string {
  const code = (error as { code?: unknown } | null)?.code;
  return typeof code === "string" && /^[a-z_]{1,40}$/.test(code) ? code : "failed";
}

export function createDesktopPlatform(invoke: TauriInvoke): Platform {
  return {
    mode: "desktop",
    native: { serverOrigin: true, pickers: true },
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
    async serverOrigin() {
      const state = await invoke("get_server_origin");
      if (!isServerOriginState(state)) throw new Error("get_server_origin answered an unexpected shape");
      return state;
    },
    async setServerOrigin(origin: string | null): Promise<SetServerOriginResult> {
      try {
        const state = await invoke("set_server_origin", { origin });
        if (!isServerOriginState(state)) return { ok: false, reason: "failed" };
        return { ok: true, state };
      } catch (error) {
        return { ok: false, reason: refusalOf(error) };
      }
    },
    async restartDesktop() {
      try {
        await invoke("restart_desktop");
        return true;
      } catch {
        return false;
      }
    },
    async chooseFolder(options?: PickerOptions): Promise<PickResult> {
      try {
        return toPickResult(await invoke("choose_folder", { options: options ?? null }));
      } catch (error) {
        return { status: "error", code: pickErrorCode(error) };
      }
    },
    async chooseFile(options?: PickerOptions): Promise<PickResult> {
      try {
        return toPickResult(await invoke("choose_file", { options: options ?? null }));
      } catch (error) {
        return { status: "error", code: pickErrorCode(error) };
      }
    },
  };
}
