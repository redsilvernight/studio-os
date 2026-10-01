/**
 * Remote-launch settings of this machine (R3 `launch.get_settings` / `launch.save_settings`).
 *
 * Only the machine owner opts in (AIB-J): the Dashboard sends an explicit,
 * confirmed request and shows the validated answer. The daemon owns the
 * stored file and refuses any harness id it does not know.
 */
import type { Platform } from "./platform";
import type {
  LaunchSettings,
  LaunchSettingsView,
  LocalError,
} from "./platform/generated/local-contracts.generated";
import { call, type HarnessOutcome } from "./harnessApi";

export type { LaunchSettings, LaunchSettingsView };

export const MIN_CONCURRENT = 1;
export const MAX_CONCURRENT = 8;

export function getLaunchSettings(platform: Platform): Promise<HarnessOutcome<LaunchSettingsView>> {
  return call(platform, "launch.get_settings", {});
}

/** `confirmed: true` is the contract's explicit consent; callers only reach it after a confirmation step. */
export function saveLaunchSettings(platform: Platform, settings: LaunchSettings): Promise<HarnessOutcome<LaunchSettingsView>> {
  return call(platform, "launch.save_settings", {
    opt_in: settings.opt_in,
    max_concurrent: settings.max_concurrent,
    allowed_harnesses: settings.allowed_harnesses ?? [],
    confirmed: true,
  });
}

/** A user-facing sentence for a refusal; never raw daemon text. */
export function launchSettingsErrorMessage(error: LocalError | null | undefined): string {
  switch (error?.code) {
    case "invalid_request":
      return "Réglages refusés : vérifiez la concurrence (1 à 8) et les harnais choisis. Rien n'a été enregistré.";
    case "internal_error":
      return "Les réglages n'ont pas pu être enregistrés sur ce poste. Rien n'a été modifié.";
    case "daemon_unavailable":
      return "L'assistant local de Studi'OS Desktop n'est pas disponible.";
    case "capability_missing":
    case "not_supported":
      return "Cette fonction n'est disponible que dans Studi'OS Desktop.";
    default:
      return "L'opération a échoué. Aucune modification n'a été confirmée.";
  }
}

/** The ids the owner may tick: what is detected plus what is already allowed (so it can be unticked). */
export function offeredHarnesses(view: LaunchSettingsView): string[] {
  return [...new Set([...(view.detected_harnesses ?? []), ...(view.allowed_harnesses ?? [])])].sort();
}

export function clampConcurrent(value: number): number {
  if (!Number.isFinite(value)) return MIN_CONCURRENT;
  return Math.min(MAX_CONCURRENT, Math.max(MIN_CONCURRENT, Math.trunc(value)));
}
