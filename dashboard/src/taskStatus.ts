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

export const TASK_COLUMNS: TaskColumn[] = ["TODO", "IN PROGRESS", "BLOCKED", "DONE"];
