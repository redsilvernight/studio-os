/**
 * Task-status presentation mapping (DASH-1 ; abandon : DEC-0359).
 *
 * Canonical backend statuses (contracts/tasks.py): created | in_progress |
 * blocked | completed | abandoned. `blocked` is NEVER merged into
 * `in_progress` in the model — the display below only labels columns.
 * `abandoned` closes a task without delivery (neutral tone, its own
 * ABANDONED column — never merged into DONE).
 */

import { agentLabel, machineLabel } from "./actorNames";

export type TaskStatus = "created" | "in_progress" | "blocked" | "completed" | "abandoned";

export type TaskColumn = "TODO" | "IN PROGRESS" | "BLOCKED" | "DONE" | "ABANDONED";

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
    case "abandoned":
      return "ABANDONED";
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
    case "ABANDONED":
      return "abandoned";
  }
}

export const TASK_COLUMNS: TaskColumn[] = ["TODO", "IN PROGRESS", "BLOCKED", "DONE", "ABANDONED"];

/**
 * UI-5 — Libellés français d'affichage (les clés backend `created` /
 * `in_progress` / `blocked` / `completed` / `abandoned` restent inchangées,
 * seuls les libellés visibles sont traduits). Source unique partagée par la
 * page Tâches, le détail et le Workspace projet.
 */
export const TASK_STATUS_LABEL_FR: Record<TaskStatus, string> = {
  created: "À faire",
  in_progress: "En cours",
  blocked: "Bloqué",
  completed: "Terminé",
  abandoned: "Abandonnée",
};

export type TaskStatusTone = "neutral" | "info" | "warning" | "success";

/** Pastille DS associée à un statut (la couleur n'est jamais le seul signal). */
export function taskStatusTone(status: string): TaskStatusTone {
  switch (status) {
    case "in_progress":
      return "info";
    case "blocked":
      return "warning";
    case "completed":
      return "success";
    case "abandoned":
      return "neutral";
    default:
      return "neutral";
  }
}

/** Libellé français sûr pour un statut connu ou inconnu (repli = clé brute). */
export function taskStatusLabel(status: string): string {
  return (TASK_STATUS_LABEL_FR as Record<string, string>)[status] ?? status;
}

export interface TaskClaimHolder {
  claimed_by_machine_id?: string | null;
  claimed_by_agent_id?: string | null;
}

/**
 * UI-5 — Signal prise/disponible d'après les seules données réelles
 * (claimed_by_machine_id / claimed_by_agent_id). Aucune priorité ni
 * assigné n'existe côté backend : ne jamais en inventer.
 */
export function taskClaimHint(task: TaskClaimHolder): string {
  const machine = task.claimed_by_machine_id ?? null;
  if (machine === null || machine === "") return "Disponible";
  const agent = task.claimed_by_agent_id ?? null;
  if (agent !== null && agent !== "") {
    return `Prise par ${agentLabel(agent)} sur ${machineLabel(machine)}`;
  }
  return `Prise sur ${machineLabel(machine)}`;
}
