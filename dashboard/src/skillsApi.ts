/**
 * Skills Library state on this machine (P1 `skills.check`, read-only).
 *
 * The Dashboard only asks the Desktop which Studio Library skills are current
 * in the two global skill directories; it never reads or writes a skill file.
 */
import type { Platform } from "./platform";
import type {
  SkillHarnessTarget,
  SkillSyncState,
  SkillsCheckResult,
} from "./platform/generated/local-contracts.generated";
import { call, type HarnessOutcome } from "./harnessApi";

export type { SkillHarnessTarget, SkillSyncState, SkillsCheckResult };

export function checkSkills(platform: Platform): Promise<HarnessOutcome<SkillsCheckResult>> {
  return call(platform, "skills.check", {});
}

export const SKILL_STATE_LABELS: Record<SkillSyncState, string> = {
  current: "À jour",
  missing: "Absent",
  outdated: "Obsolète",
  locally_modified: "Modifié localement",
};

export const SKILL_STATE_TONES: Record<SkillSyncState, "success" | "warning" | "danger" | "neutral"> = {
  current: "success",
  missing: "neutral",
  outdated: "warning",
  locally_modified: "danger",
};

export const SKILL_TARGET_LABELS: Record<SkillHarnessTarget, string> = {
  agents: "Dossier partagé",
  assistant: "Dossier de l'assistant",
};
