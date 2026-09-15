import { describe, expect, it } from "vitest";
import { agentsSeenInEvents, groupTasksByColumn, reviewActionsHtml, reviewQueueItemDetail, sinceIso24h } from "./overview";

const task = (status: string, id = "t") => ({ id, status }) as never;

describe("reviewQueueItemDetail", () => {
  it("shows the agent for an ai_work_review item", () => {
    const item = { kind: "ai_work_review", agent_id: "11111111-2222-4333-8444-555555555555" } as never;
    expect(reviewQueueItemDetail(item)).toContain("agent");
  });

  it("shows the readable_id for a decision_proposal item", () => {
    const item = { kind: "decision_proposal", readable_id: "DEC-0049" } as never;
    expect(reviewQueueItemDetail(item)).toBe("DEC-0049");
  });

  it("shows the resource_path for a resource_conflict item", () => {
    const item = { kind: "resource_conflict", resource_path: "scenes/level_01.tscn" } as never;
    expect(reviewQueueItemDetail(item)).toBe("scenes/level_01.tscn");
  });
});

describe("reviewActionsHtml", () => {
  const item = { kind: "ai_work_review", id: "11111111-2222-4333-8444-555555555555" } as never;

  it("offers approve / request changes for an ai_work_review item", () => {
    const html = reviewActionsHtml(item, true);
    expect(html).toContain("data-review-approve");
    expect(html).toContain("data-review-changes");
    expect(html).not.toContain("disabled");
  });

  it("disables the actions without a token and offers none for other kinds", () => {
    expect(reviewActionsHtml(item, false)).toContain("disabled");
    expect(reviewActionsHtml({ kind: "decision_proposal" } as never, true)).not.toContain("data-review");
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
