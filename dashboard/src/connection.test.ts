import { describe, expect, it } from "vitest";
import { createConnectionMonitor, RETRY_DELAYS_MS } from "./connection";

function harness(probeImpl: () => Promise<number>) {
  const scheduled: { cb: () => void; delay: number; cancelled: boolean }[] = [];
  let probes = 0;
  const monitor = createConnectionMonitor({
    probe: () => {
      probes += 1;
      return probeImpl();
    },
    schedule: (cb, delay) => {
      const entry = { cb, delay, cancelled: false };
      scheduled.push(entry);
      return () => {
        entry.cancelled = true;
      };
    },
  });
  return { monitor, scheduled, probes: () => probes };
}

const offline = async (): Promise<number> => {
  throw new TypeError("offline");
};

describe("connection monitor", () => {
  it("connects when /healthz answers 2xx", async () => {
    const h = harness(async () => 200);
    expect(h.monitor.snapshot().state).toBe("unknown");
    await h.monitor.check();
    expect(h.monitor.snapshot()).toEqual({ state: "connected", detail: null });
  });

  it("reports unreachable on a network failure and retries with a growing backoff", async () => {
    const h = harness(offline);
    await h.monitor.check();
    expect(h.monitor.snapshot()).toEqual({ state: "unreachable", detail: "network" });
    expect(h.scheduled.at(-1)?.delay).toBe(RETRY_DELAYS_MS[0]);
    h.scheduled.at(-1)!.cb();
    await h.monitor.check();
    expect(h.scheduled.at(-1)?.delay).toBe(RETRY_DELAYS_MS[1]);
    expect(h.monitor.snapshot().state).toBe("unreachable");
  });

  it("treats a non-2xx health answer as unreachable with its status", async () => {
    const h = harness(async () => 503);
    await h.monitor.check();
    expect(h.monitor.snapshot()).toEqual({ state: "unreachable", detail: "http_503" });
  });

  it("recovers by itself, without a restart, when the server comes back", async () => {
    let up = false;
    const h = harness(async () => {
      if (!up) throw new TypeError("offline");
      return 200;
    });
    await h.monitor.check();
    expect(h.monitor.snapshot().state).toBe("unreachable");
    up = true;
    h.scheduled.at(-1)!.cb();
    await h.monitor.check();
    expect(h.monitor.snapshot().state).toBe("connected");
  });

  it("an answered API call recovers the state too and cancels the pending retry", () => {
    const h = harness(offline);
    h.monitor.reportNetworkError();
    expect(h.monitor.snapshot().state).toBe("unreachable");
    h.monitor.reportReachable();
    expect(h.monitor.snapshot().state).toBe("connected");
    expect(h.scheduled.at(-1)?.cancelled).toBe(true);
  });

  it("an expired session sticks until the user signs in again", () => {
    const h = harness(async () => 200);
    h.monitor.reportUnauthorized();
    h.monitor.reportReachable();
    h.monitor.reportNetworkError();
    expect(h.monitor.snapshot().state).toBe("auth_expired");
    h.monitor.clearAuthExpired();
    expect(h.monitor.snapshot().state).toBe("unknown");
  });

  it("notifies subscribers only on change and stops cleanly", async () => {
    const h = harness(async () => 200);
    const seen: string[] = [];
    h.monitor.subscribe((s) => seen.push(s.state));
    await h.monitor.check();
    h.monitor.reportReachable();
    expect(seen).toEqual(["connecting", "connected"]);
    h.monitor.stop();
    h.monitor.reportNetworkError();
    expect(seen).toEqual(["connecting", "connected"]);
  });

  it("de-duplicates concurrent probes", async () => {
    const h = harness(async () => 200);
    await Promise.all([h.monitor.check(), h.monitor.check()]);
    expect(h.probes()).toBe(1);
  });
});
