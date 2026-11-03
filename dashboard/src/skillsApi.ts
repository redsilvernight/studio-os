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
  SkillResolution,
  LocalError,
} from "./platform/generated/local-contracts.generated";
import { call, harnessErrorMessage, type HarnessOutcome } from "./harnessApi";

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

export type { SkillsApplyResult, SkillsPreviewResult, SkillsSyncStatus, SkillSyncStatusState, SkillResolution };

export function getSkillsSyncStatus(platform: Platform): Promise<HarnessOutcome<SkillsSyncStatus>> {
  return call(platform, "skills.status", {});
}

export function previewSkills(platform: Platform): Promise<HarnessOutcome<SkillsPreviewResult>> {
  return call(platform, "skills.preview", {});
}

export function skillsPreviewErrorMessage(error: LocalError): string {
  if (error.code === "secret_absent" || error.code === "secret_revoked") {
    return "Impossible de charger les versions : reconnectez ce poste à Studi'OS.";
  }
  if (error.code === "internal_error") {
    return error.retryable
      ? "Impossible de charger les versions de la Library : le serveur est temporairement indisponible ou trop sollicité. Patientez un instant puis réessayez."
      : "Impossible de charger les versions de la Library. Réessayez ; si le problème persiste, consultez les diagnostics de l'assistant local.";
  }
  if (["daemon_unavailable", "capability_missing", "not_supported", "permission_denied"].includes(error.code)) {
    return `Impossible de charger les versions. ${harnessErrorMessage(error)}`;
  }
  return "Impossible de charger les versions. Vérifiez la connexion puis réessayez.";
}

export function applySkills(platform: Platform, selection: boolean | readonly SkillResolution[] = false): Promise<HarnessOutcome<SkillsApplyResult>> {
  const payload = typeof selection === "boolean"
    ? selection ? { confirm: true, overwrite: true } : { confirm: true }
    : { confirm: true, resolutions: [...selection] };
  return call(platform, "skills.apply", payload);
}

export function configureSkillsSync(platform: Platform, autoSync: boolean): Promise<HarnessOutcome<SkillsSyncStatus>> {
  return call(platform, "skills.configure", { auto_sync: autoSync });
}

export const SYNC_STATE_LABELS: Record<SkillSyncStatusState, string> = {
  in_progress: "Library : synchronisation…",
  up_to_date: "Library à jour",
  updated: "Library mise à jour",
  conflicts: "Library : conflits à résoudre",
  not_synced: "Library non synchronisée",
  disabled: "Library : synchro désactivée",
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
  in_progress: "La synchronisation de la Library (skills, rules, agents) est en cours.",
  up_to_date: "Les skills, rules et agents de la Library sont à jour sur ce poste.",
  updated: "Des skills, rules ou agents de la Library ont été ajoutés ou mis à jour sur ce poste.",
  conflicts:
    "Des skills, rules ou agents modifiés à la main n'ont pas été écrasés. Comparez les versions et choisissez celle à garder pour chaque fichier.",
  not_synced:
    "La synchronisation n'a pas pu aboutir (hors ligne, non connecté ou erreur). Elle sera retentée au prochain démarrage.",
  disabled: "La synchronisation automatique est désactivée sur ce poste.",
};
