/**
 * « Configurer ce poste » (P1 `setup.plan` / `setup.apply`).
 *
 * Le tableau de bord n'envoie que deux commandes : un aperçu sans écriture,
 * puis une application liée à cet aperçu (identifiant + empreinte +
 * confirmation explicite). Il ne lit ni n'écrit aucun fichier local : les
 * libellés ci-dessous traduisent des états du Desktop, jamais son contenu.
 */
import type { Platform } from "./platform";
import type {
  LocalError,
  SetupAdaptersState,
  SetupApplyResult,
  SetupItemKind,
  SetupItemOutcome,
  SetupItemPlan,
  SetupItemState,
  SetupPlan,
  SetupSkillsOutcome,
  SetupUnavailableReason,
} from "./platform/generated/local-contracts.generated";
import { call, type HarnessOutcome } from "./harnessApi";

export type { SetupApplyResult, SetupItemPlan, SetupPlan };

export function previewSetup(platform: Platform): Promise<HarnessOutcome<SetupPlan>> {
  return call(platform, "setup.plan", {});
}

export function applySetup(
  platform: Platform,
  plan: SetupPlan,
  overwriteItems: string[],
  syncSkills: boolean,
): Promise<HarnessOutcome<SetupApplyResult>> {
  return call(platform, "setup.apply", {
    plan_id: plan.plan_id,
    plan_hash: plan.plan_hash,
    confirmed: true,
    overwrite_items: overwriteItems,
    sync_skills: syncSkills,
  });
}

export const ITEM_KIND_LABELS: Record<SetupItemKind, string> = {
  hook: "Script de démarrage de session",
  guard: "Script de protection Git",
  plugin: "Extension de l'outil",
};

export const ITEM_STATE_LABELS: Record<SetupItemState, string> = {
  missing: "À installer",
  current: "À jour",
  differs: "Différent de la version gérée",
};

export const ITEM_STATE_TONES: Record<SetupItemState, "success" | "warning" | "neutral"> = {
  missing: "neutral",
  current: "success",
  differs: "warning",
};

export const ITEM_OUTCOME_LABELS: Record<SetupItemOutcome, string> = {
  written: "Écrit et relu",
  unchanged: "Déjà à jour, rien écrit",
  skipped: "Laissé tel quel",
  failed: "Échec, non confirmé",
};

export const ITEM_OUTCOME_TONES: Record<SetupItemOutcome, "success" | "neutral" | "warning" | "danger"> = {
  written: "success",
  unchanged: "neutral",
  skipped: "warning",
  failed: "danger",
};

export const SKILLS_UNAVAILABLE_LABELS: Record<SetupUnavailableReason, string> = {
  not_signed_in: "Ce poste n'est pas connecté à Studi'OS.",
  credential_rejected: "L'accès de ce poste a été refusé : reconnectez-le.",
  library_unreachable: "La bibliothèque Studi'OS est injoignable.",
  invalid_skill: "Une skill de la bibliothèque est invalide.",
};

export const SKILLS_OUTCOME_LABELS: Record<SetupSkillsOutcome, string> = {
  synced: "Synchronisées et relues",
  unchanged: "Déjà à jour, rien écrit",
  skipped: "Non synchronisées",
  unavailable: "Indisponible, rien écrit",
  failed: "Échec, non confirmé",
};

export const ADAPTERS_STATE_LABELS: Record<SetupAdaptersState, string> = {
  checked: "Vérifiés",
  not_applicable: "Aucun dossier avec des définitions canoniques",
  unavailable: "Vérification impossible",
};

export function setupErrorMessage(error: LocalError | null | undefined): string {
  switch (error?.code) {
    case "plan_expired":
      return "L'aperçu a expiré : relancez-le avant d'appliquer.";
    case "invalid_request":
      return "L'aperçu ne correspond plus à la demande : relancez-le.";
    case "daemon_unavailable":
      return "L'assistant local de Studi'OS Desktop n'est pas disponible.";
    case "capability_missing":
    case "not_supported":
      return "Cette fonction n'est disponible que dans Studi'OS Desktop.";
    default:
      return "L'opération a échoué. Aucune modification n'a été confirmée.";
  }
}

/** Y a-t-il quelque chose à écrire ? Sinon une seconde exécution n'écrit rien. */
export function hasPendingWork(plan: SetupPlan): boolean {
  const skillsPending = plan.skills.state === "checked" && ((plan.skills.missing ?? 0) > 0 || (plan.skills.outdated ?? 0) > 0);
  return (plan.hooks ?? []).some((item) => item.state !== "current") || skillsPending;
}
