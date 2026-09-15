/**
 * Task-status presentation mapping (DASH-1).
 *
 * Canonical backend statuses (contracts/tasks.py): created | in_progress |
 * blocked | completed. `blocked` is NEVER merged into `in_progress` in the
 * model — the display below only labels columns.
 */

export type TaskStatus = "created" | "in_progress" | "blocked" | "completed";

export type TaskColumn = "TODO" | "IN PROGRESS" | "BLOCKED" | "DONE";

export function statusColumn(status: string): TaskColumn | "UNKNOWN" {
  switch (status) {
    case "created":
      return "TODO";
    case "in_progress":
      return "IN PROGRESS";
    case "blocked":
      return "BLOCKED";
    case "completed":
      return "DONE";
    default:
      return "UNKNOWN";
  }
}

/** Inverse of `statusColumn`, for a column drop target → canonical status. */
export function columnToStatus(column: TaskColumn): TaskStatus {
  switch (column) {
    case "TODO":
      return "created";
    case "IN PROGRESS":
      return "in_progress";
    case "BLOCKED":
      return "blocked";
    case "DONE":
      return "completed";
  }
}

export const TASK_COLUMNS: TaskColumn[] = ["TODO", "IN PROGRESS", "BLOCKED", "DONE"];
