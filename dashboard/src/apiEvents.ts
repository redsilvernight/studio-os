/**
 * Connection signals from the API client.
 *
 * The client reports what it observes on every call — the server answered, the
 * network failed, the session was refused — so the Desktop shell can show one
 * honest connection state without polling. With no observer installed (the web
 * build) this is a transparent `fetch`.
 */
import { hasToken } from "./auth";
import { advisoryLatest, parseUpgradeRequired, type UpgradeInfo } from "./clientCompatibility";

export interface ApiObserver {
  /**
   * Refuse a request before it leaves (no network call, no `reachable` signal).
   * The Desktop shell uses it so a relative URL never resolves against the
   * Desktop origin (`tauri.localhost`), which is never a server.
   */
  refuse?(url: string): boolean;
  /** The server answered (any HTTP status): it is reachable. */
  reachable?(): void;
  /** The request never got an answer (offline, DNS, refused, blocked). */
  networkError?(): void;
  /** A signed-in session was refused (HTTP 401). */
  unauthorized?(): void;
  /** The server says a newer client build is recommended (C1 grace window). */
  clientUpdate?(latest: string): void;
  /** The server refused this build outright (426 client_upgrade_required). */
  upgradeRequired?(info: UpgradeInfo): void;
}

let observer: ApiObserver | null = null;

export function setApiObserver(next: ApiObserver | null): void {
  observer = next;
}

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

export const observedFetch: typeof fetch = async (input, init) => {
  if (observer?.refuse?.(urlOf(input))) {
    observer.networkError?.();
    throw new TypeError("no server address configured");
  }
  let response: Response;
  try {
    response = await globalThis.fetch(input, init);
  } catch (error) {
    observer?.networkError?.();
    throw error;
  }
  observer?.reachable?.();
  if (response.status === 401 && hasToken()) observer?.unauthorized?.();
  const headers = response.headers;
  const latest = headers ? advisoryLatest(headers) : null;
  if (latest !== null) observer?.clientUpdate?.(latest);
  if (response.status === 426 && typeof response.clone === "function") {
    // The structured detail lives in the body; a clone avoids consuming the
    // caller's stream. A malformed body simply yields no blocking screen.
    try {
      const body: unknown = await response.clone().json();
      const detail = (body as { detail?: { error_code?: unknown } } | null)?.detail;
      const code = typeof detail?.error_code === "string" ? detail.error_code : null;
      const info = parseUpgradeRequired(code, detail);
      if (info !== null) observer?.upgradeRequired?.(info);
    } catch {
      // Non-JSON body: nothing to display.
    }
  }
  return response;
};
