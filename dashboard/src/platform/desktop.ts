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
  DataFolder,
  DesktopDiagnostics,
  DesktopInfo,
  DiagnosticsExportResult,
  PickerOptions,
  PickResult,
  Platform,
  ServerOriginRefusal,
  ServerOriginState,
  SetServerOriginResult,
  UpdateCheckResult,
  UpdateErrorCode,
  UpdateStatus,
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

const isString = (v: unknown): v is string => typeof v === "string";
const isNullableString = (v: unknown): boolean => v === null || typeof v === "string";
const COMPAT = ["compatible", "version_drift", "protocol_mismatch", "unknown"];

type Bag = Record<string, unknown>;
const isBag = (v: unknown): v is Bag => typeof v === "object" && v !== null && !Array.isArray(v);

export function isDiagnostics(v: unknown): v is DesktopDiagnostics {
  if (!isBag(v) || !isBag(v.sidecar) || !isBag(v.locations)) return false;
  const s = v.sidecar;
  const l = v.locations;
  const m = s.manifest;
  return (
    isString(v.desktop_version) &&
    isString(v.protocol) &&
    isString(v.os) &&
    isString(v.arch) &&
    isBag(s.state) &&
    isString(s.state.state) &&
    typeof s.present === "boolean" &&
    COMPAT.includes(s.compat as string) &&
    (m === null || (isBag(m) && isString(m.daemon_version) && isString(m.desktop_version) && isString(m.protocol))) &&
    isNullableString(v.server_origin) &&
    typeof v.updates_configured === "boolean" &&
    isNullableString(l.daemon_data_dir) &&
    isNullableString(l.logs_dir) &&
    isNullableString(l.shell_settings_dir) &&
    isNullableString(l.install_dir) &&
    isBag(l.data_format) &&
    isString(l.data_format.state) &&
    Array.isArray(l.logs) &&
    l.logs.every((f) => isBag(f) && isString(f.name) && typeof f.bytes === "number")
  );
}

export function toUpdateStatus(v: unknown): UpdateStatus | null {
  if (!isBag(v)) return null;
  if (v.state === "not_configured") return { state: "not_configured" };
  if (v.state === "up_to_date" && isString(v.current)) return { state: "up_to_date", current: v.current };
  if (v.state === "available" && isString(v.current) && isString(v.version) && isNullableString(v.notes ?? null)) {
    return { state: "available", current: v.current, version: v.version, notes: (v.notes as string | null | undefined) ?? null };
  }
  return null;
}

const UPDATE_CODES: readonly UpdateErrorCode[] = [
  "not_configured",
  "network",
  "invalid_metadata",
  "invalid_signature",
  "install_failed",
];

function updateCodeOf(error: unknown): UpdateErrorCode {
  const code = (error as { code?: unknown } | null)?.code;
  return UPDATE_CODES.find((c) => c === code) ?? "failed";
}

export function createDesktopPlatform(invoke: TauriInvoke): Platform {
  return {
    mode: "desktop",
    native: { serverOrigin: true, pickers: true, diagnostics: true, updates: true },
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
    async diagnostics(): Promise<DesktopDiagnostics | null> {
      const value = await invoke("get_diagnostics");
      if (!isDiagnostics(value)) throw new Error("get_diagnostics answered an unexpected shape");
      return value;
    },
    async exportDiagnostics(): Promise<DiagnosticsExportResult> {
      try {
        const answer = await invoke("export_diagnostics");
        const file = isBag(answer) ? answer.file : undefined;
        return isString(file) && file ? { ok: true, file } : { ok: false, code: "unexpected_answer" };
      } catch (error) {
        return { ok: false, code: pickErrorCode(error) };
      }
    },
    async openDataFolder(folder: DataFolder): Promise<boolean> {
      try {
        await invoke("open_data_folder", { folder });
        return true;
      } catch {
        return false;
      }
    },
    async checkForUpdate(): Promise<UpdateCheckResult> {
      try {
        const status = toUpdateStatus(await invoke("check_for_update"));
        return status ? { ok: true, status } : { ok: false, code: "invalid_metadata" };
      } catch (error) {
        return { ok: false, code: updateCodeOf(error) };
      }
    },
    async installUpdate() {
      try {
        await invoke("install_update");
        return { ok: true } as const;
      } catch (error) {
        return { ok: false, code: updateCodeOf(error) } as const;
      }
    },
  };
}
