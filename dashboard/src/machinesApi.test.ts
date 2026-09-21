import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activeSessions,
  buildMachineRows,
  canonicalPresence,
  derivedPresence,
  fetchCanonicalMachines,
  isDashboardIdentity,
} from "./machinesApi";

const NOW = new Date("2026-09-15T12:00:00.000Z").getTime();
const ago = (seconds: number): string => new Date(NOW - seconds * 1000).toISOString();

describe("canonicalPresence", () => {
  it("mirrors the server heartbeat thresholds (online ≤45s, idle ≤90s, else offline)", () => {
    expect(canonicalPresence(ago(10), NOW)).toBe("online");
    expect(canonicalPresence(ago(45), NOW)).toBe("online");
    expect(canonicalPresence(ago(60), NOW)).toBe("idle");
    expect(canonicalPresence(ago(200), NOW)).toBe("offline");
    expect(canonicalPresence(null, NOW)).toBe("offline");
  });
});

describe("derivedPresence", () => {
  it("uses looser event-based windows and never claims canonical", () => {
    expect(derivedPresence(ago(60), NOW)).toBe("online");
    expect(derivedPresence(ago(10 * 60), NOW)).toBe("idle");
    expect(derivedPresence(ago(60 * 60), NOW)).toBe("offline");
    expect(derivedPresence(undefined, NOW)).toBe("offline");
  });
});

describe("buildMachineRows", () => {
  it("derives one row per machine id from agents, sessions and events", () => {
    const rows = buildMachineRows({
      machines: null,
      agents: [{ machine_id: "m1", display_name: "A" }, { machine_id: "m1" }, { machine_id: null }] as never,
      sessions: [
        { machine_id: "m1", started_at: ago(30), ended_at: null },
        { machine_id: "m2", started_at: ago(120), ended_at: ago(60) },
      ] as never,
      events: [{ machine_id: "m2", server_timestamp: ago(20) }] as never,
      now: NOW,
    });
    const m1 = rows.find((row) => row.machineId === "m1");
    const m2 = rows.find((row) => row.machineId === "m2");
    expect(m1).toMatchObject({ agentCount: 2, activeSessionCount: 1, status: "online", statusSource: "derived" });
    expect(m2).toMatchObject({ activeSessionCount: 0, lastActivityAt: ago(20), status: "online" });
  });

  it("prefers canonical last_seen_at when GET /machines answered", () => {
    const rows = buildMachineRows({
      machines: [
        { id: "m1", display_name: "canon", owner_user_id: "u1", last_seen_at: ago(10), status: "online" },
      ] as never,
      agents: [],
      sessions: [],
      events: [],
      now: NOW,
    });
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      displayName: "canon",
      ownerUserId: "u1",
      status: "online",
      statusSource: "canonical",
      lastSeenAt: ago(10),
    });
  });

  it("sorts online before idle before offline", () => {
    const rows = buildMachineRows({
      machines: null,
      agents: [{ machine_id: "old" }, { machine_id: "live" }, { machine_id: "idle" }] as never,
      sessions: [] as never,
      events: [
        { machine_id: "live", server_timestamp: ago(10) },
        { machine_id: "idle", server_timestamp: ago(600) },
        { machine_id: "old", server_timestamp: ago(4000) },
      ] as never,
      now: NOW,
    });
    expect(rows.map((row) => row.status)).toEqual(["online", "idle", "offline"]);
  });
});

describe("activeSessions", () => {
  it("keeps only sessions without ended_at", () => {
    const sessions = [
      { id: "a", ended_at: null },
      { id: "b", ended_at: ago(1) },
      { id: "c" },
    ] as never;
    expect(activeSessions(sessions).map((s) => s.id)).toEqual(["a", "c"]);
  });
});

describe("fetchCanonicalMachines", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns the list on 200", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [{ id: "m1" }] }));
    await expect(fetchCanonicalMachines("", "tok")).resolves.toEqual([{ id: "m1" }]);
  });

  it("returns null when the endpoint does not exist (405)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 405, json: async () => null }));
    await expect(fetchCanonicalMachines("", "tok")).resolves.toBeNull();
  });

  it("throws a machine-readable error on 403", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 403, json: async () => ({ detail: "forbidden" }) }),
    );
    await expect(fetchCanonicalMachines("", "tok")).rejects.toMatchObject({ status: 403 });
  });
});

describe("isDashboardIdentity", () => {
  it("recognizes the dashboard technical identity, case/whitespace insensitive", () => {
    expect(isDashboardIdentity("dashboard")).toBe(true);
    expect(isDashboardIdentity("Dashboard")).toBe(true);
    expect(isDashboardIdentity("  dashboard  ")).toBe(true);
    expect(isDashboardIdentity("DASHBOARD")).toBe(true);
  });

  it("does not match a normal machine name or an absent one", () => {
    expect(isDashboardIdentity("dev-laptop")).toBe(false);
    expect(isDashboardIdentity("dashboard-runner")).toBe(false);
    expect(isDashboardIdentity(null)).toBe(false);
    expect(isDashboardIdentity(undefined)).toBe(false);
    expect(isDashboardIdentity("")).toBe(false);
  });
});

describe("buildMachineRows excludes the dashboard identity", () => {
  it("drops the canonical dashboard machine row from the Machines list", () => {
    const rows = buildMachineRows({
      machines: [
        { id: "dash-1", display_name: "dashboard", owner_user_id: "u1", last_seen_at: ago(10), status: "online" },
        { id: "m1", display_name: "dev-laptop", owner_user_id: "u1", last_seen_at: ago(10), status: "online" },
      ] as never,
      agents: [],
      sessions: [],
      events: [],
      now: NOW,
    });
    expect(rows.map((row) => row.machineId)).toEqual(["m1"]);
  });

  it("never lets the excluded dashboard machine's agents/sessions leak into another row", () => {
    const rows = buildMachineRows({
      machines: [
        { id: "dash-1", display_name: "dashboard", owner_user_id: "u1", last_seen_at: ago(10), status: "online" },
        { id: "m1", display_name: "dev-laptop", owner_user_id: "u1", last_seen_at: ago(10), status: "online" },
      ] as never,
      agents: [{ machine_id: "dash-1", display_name: "ghost-agent" }] as never,
      sessions: [{ machine_id: "dash-1", started_at: ago(30), ended_at: null }] as never,
      events: [],
      now: NOW,
    });
    expect(rows).toHaveLength(1);
    expect(rows[0]?.machineId).toBe("m1");
    expect(rows[0]?.agentCount).toBe(0);
    expect(rows[0]?.activeSessionCount).toBe(0);
  });
});
