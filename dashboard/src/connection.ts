/**
 * Server connection state (Desktop shell).
 *
 * One small state machine, fed by two sources: what real API calls observe
 * (`apiEvents`) and an explicit `/healthz` probe. It only ever reports what
 * was observed — never a guess — and recovers on its own: while the server is
 * unreachable it retries with a capped backoff, and any later answer moves it
 * back to `connected` without restarting the app.
 */
export type ConnectionState = "unknown" | "connecting" | "connected" | "unreachable" | "auth_expired";

export interface ConnectionSnapshot {
  state: ConnectionState;
  /** Why it is unreachable, for the details view: `network` or `http_<status>`. */
  detail: string | null;
}

export interface ConnectionDeps {
  /** Resolves the HTTP status of `/healthz`; rejects when there is no answer. */
  probe(): Promise<number>;
  schedule(callback: () => void, delayMs: number): () => void;
}

export interface ConnectionMonitor {
  snapshot(): ConnectionSnapshot;
  subscribe(listener: (snapshot: ConnectionSnapshot) => void): () => void;
  /** Probe now (start-up, or the user pressed « Réessayer »). */
  check(): Promise<void>;
  reportReachable(): void;
  reportNetworkError(): void;
  reportUnauthorized(): void;
  /** The user signed in again or out: the session is no longer « expired ». */
  clearAuthExpired(): void;
  stop(): void;
}

export const RETRY_DELAYS_MS = [3000, 6000, 12000, 24000, 30000] as const;

export function createConnectionMonitor(deps: ConnectionDeps): ConnectionMonitor {
  let current: ConnectionSnapshot = { state: "unknown", detail: null };
  let cancelRetry: (() => void) | null = null;
  let attempt = 0;
  let stopped = false;
  let checking: Promise<void> | null = null;
  const listeners = new Set<(s: ConnectionSnapshot) => void>();

  function set(next: ConnectionSnapshot): void {
    if (next.state === current.state && next.detail === current.detail) return;
    current = next;
    for (const listener of [...listeners]) listener(current);
  }

  function clearRetry(): void {
    cancelRetry?.();
    cancelRetry = null;
  }

  function scheduleRetry(): void {
    clearRetry();
    if (stopped) return;
    const delay = RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)] ?? 30000;
    attempt += 1;
    cancelRetry = deps.schedule(() => {
      cancelRetry = null;
      void check();
    }, delay);
  }

  function markReachable(): void {
    attempt = 0;
    clearRetry();
    // An answered request does not lift an expired session: only signing in does.
    if (current.state !== "auth_expired") set({ state: "connected", detail: null });
  }

  function markUnreachable(detail: string): void {
    if (current.state === "auth_expired") return;
    set({ state: "unreachable", detail });
    scheduleRetry();
  }

  async function check(): Promise<void> {
    if (checking) return checking;
    // Only the first probe shows « connecting »: a retry keeps « unreachable ».
    if (current.state === "unknown") set({ state: "connecting", detail: null });
    checking = (async () => {
      try {
        const status = await deps.probe();
        if (status >= 200 && status < 300) markReachable();
        else markUnreachable(`http_${status}`);
      } catch {
        markUnreachable("network");
      } finally {
        checking = null;
      }
    })();
    return checking;
  }

  return {
    snapshot: () => current,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    check,
    reportReachable: markReachable,
    reportNetworkError: () => markUnreachable("network"),
    reportUnauthorized() {
      clearRetry();
      set({ state: "auth_expired", detail: null });
    },
    clearAuthExpired() {
      if (current.state === "auth_expired") set({ state: "unknown", detail: null });
    },
    stop() {
      stopped = true;
      clearRetry();
      listeners.clear();
    },
  };
}
