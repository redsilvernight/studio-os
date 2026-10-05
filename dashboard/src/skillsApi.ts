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
  SkillSyncStatusState,
  SkillsApplyResult,
  SkillsCheckResult,
  SkillsPreviewResult,
  SkillsSyncStatus,
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

export type { SkillsApplyResult, SkillsPreviewResult, SkillsSyncStatus, SkillSyncStatusState };

export function getSkillsSyncStatus(platform: Platform): Promise<HarnessOutcome<SkillsSyncStatus>> {
  return call(platform, "skills.status", {});
}

export function previewSkills(platform: Platform): Promise<HarnessOutcome<SkillsPreviewResult>> {
  return call(platform, "skills.preview", {});
}

export function applySkills(platform: Platform, overwrite = false): Promise<HarnessOutcome<SkillsApplyResult>> {
  return call(platform, "skills.apply", overwrite ? { confirm: true, overwrite: true } : { confirm: true });
}

export function configureSkillsSync(platform: Platform, autoSync: boolean): Promise<HarnessOutcome<SkillsSyncStatus>> {
  return call(platform, "skills.configure", { auto_sync: autoSync });
}

export const SYNC_STATE_LABELS: Record<SkillSyncStatusState, string> = {
  in_progress: "Skills : synchronisation…",
  up_to_date: "Skills à jour",
  updated: "Skills mis à jour",
  conflicts: "Skills : conflits à résoudre",
  not_synced: "Skills non synchronisés",
  disabled: "Skills : synchro désactivée",
};

export const SYNC_STATE_LEVELS: Record<SkillSyncStatusState, "ok" | "info" | "warn" | "error"> = {
  in_progress: "info",
  up_to_date: "ok",
  updated: "ok",
  conflicts: "warn",
  not_synced: "warn",
  disabled: "info",
};

/** Message fixe : jamais le texte brut du démon (aucun chemin ni contenu de skill). */
export const SYNC_STATE_MESSAGES: Record<SkillSyncStatusState, string> = {
  in_progress: "La synchronisation des skills de la Library est en cours.",
  up_to_date: "Tous les skills de la Library sont à jour sur ce poste.",
  updated: "Des skills de la Library ont été ajoutés ou mis à jour sur ce poste.",
  conflicts:
    "Des skills modifiés à la main n'ont pas été écrasés. Rétablissez-les ou supprimez la copie locale, puis réessayez.",
  not_synced:
    "La synchronisation n'a pas pu aboutir (hors ligne, non connecté ou erreur). Elle sera retentée au prochain démarrage.",
  disabled: "La synchronisation automatique est désactivée sur ce poste.",
};
