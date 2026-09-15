import { describe, expect, it } from "vitest";
import { agentsSeenInEvents, filterReviews, groupTasksByColumn, sinceIso24h } from "./overview";

const task = (status: string, id = "t") => ({ id, status }) as never;
const worklog = (status: string) => ({ status }) as never;

describe("filterReviews", () => {
  it("keeps only review_requested worklogs", () => {
    const logs = [worklog("review_requested"), worklog("approved"), worklog("completed")];
    expect(filterReviews(logs)).toHaveLength(1);
  });
});

describe("groupTasksByColumn", () => {
  it("groups by canonical column and never merges blocked", () => {
    const groups = groupTasksByColumn([
      task("created", "a"),
      task("in_progress", "b"),
      task("blocked", "c"),
      task("completed", "d"),
    ]);
    expect(groups["TODO"]).toHaveLength(1);
    expect(groups["IN PROGRESS"]).toHaveLength(1);
    expect(groups["BLOCKED"]).toHaveLength(1);
    expect(groups["DONE"]).toHaveLength(1);
  });
});

describe("agentsSeenInEvents", () => {
  it("collects agent actors and machine ids", () => {
    const events = [
      { actor_type: "agent", actor_id: "agent-1", machine_id: "m-1" },
      { actor_type: "user", actor_id: "u-1", machine_id: "m-2" },
    ] as never;
    const seen = agentsSeenInEvents(events);
    expect(seen.has("agent-1")).toBe(true);
    expect(seen.has("m-1")).toBe(true);
    expect(seen.has("u-1")).toBe(false);
  });
});

describe("sinceIso24h", () => {
  it("returns an ISO timestamp 24h before now", () => {
    const iso = sinceIso24h(new Date("2026-09-15T12:00:00Z").getTime());
    expect(iso).toBe("2026-09-14T12:00:00.000Z");
  });
});
