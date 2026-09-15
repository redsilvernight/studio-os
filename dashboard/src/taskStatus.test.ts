import { describe, expect, it } from "vitest";
import { TASK_COLUMNS, columnToStatus, statusColumn } from "./taskStatus";

describe("statusColumn", () => {
  it("maps canonical statuses without merging blocked", () => {
    expect(statusColumn("created")).toBe("TODO");
    expect(statusColumn("in_progress")).toBe("IN PROGRESS");
    expect(statusColumn("blocked")).toBe("BLOCKED");
    expect(statusColumn("completed")).toBe("DONE");
  });

  it("marks unknown statuses instead of inventing a column", () => {
    expect(statusColumn("archived")).toBe("UNKNOWN");
    expect(statusColumn("")).toBe("UNKNOWN");
  });

  it("exposes the four display columns", () => {
    expect(TASK_COLUMNS).toEqual(["TODO", "IN PROGRESS", "BLOCKED", "DONE"]);
  });
});

describe("columnToStatus", () => {
  it("is the exact inverse of statusColumn (drop target → canonical status)", () => {
    for (const column of TASK_COLUMNS) {
      expect(statusColumn(columnToStatus(column))).toBe(column);
    }
    expect(columnToStatus("BLOCKED")).toBe("blocked");
    expect(columnToStatus("DONE")).toBe("completed");
  });
});
