/**
 * Harness integrations over the local bridge (P1 `harness.*` commands).
 *
 * The Dashboard only sends requests and reads validated answers: it never
 * launches a harness, reads or parses one of its files. Everything vendor
 * specific lives in the Desktop's harness adapters.
 */
import type { Platform } from "./platform";
import type {
  HarnessApplyResult,
  HarnessDetectResult,
  HarnessPlan,
  HarnessRollbackResult,
  HarnessState,
  HarnessStatus,
  HarnessVerifyResult,
  LocalError,
  VerifyState,
} from "./platform/generated/local-contracts.generated";

export type {
  HarnessApplyResult,
  HarnessDetectResult,
  HarnessPlan,
  HarnessRollbackResult,
  HarnessState,
  HarnessStatus,
  HarnessVerifyResult,
  VerifyState,
};

export type HarnessOutcome<T> = { ok: true; value: T } | { ok: false; error: LocalError };

type Command = Parameters<Platform["request"]>[0];

/** The daemon forgets granted capabilities when it restarts: negotiate again, once. */
async function negotiate(platform: Platform): Promise<void> {
  try {
    const info = await platform.desktopInfo();
    if (info?.peer) await platform.request("runtime.handshake", { peer: info.peer });
  } catch {
    // The retry below reports the refusal.
  }
}

async function call<T>(platform: Platform, command: Command, payload: Record<string, unknown>): Promise<HarnessOutcome<T>> {
  let answer = await platform.request(command, payload);
  if (!answer.ok && answer.error.code === "capability_missing") {
    await negotiate(platform);
    answer = await platform.request(command, payload);
  }
  if (!answer.ok) return { ok: false, error: answer.error };
  return { ok: true, value: answer.response.payload as T };
}

export function detectHarnesses(platform: Platform, workspaceId: string): Promise<HarnessOutcome<HarnessDetectResult>> {
  return call(platform, "harness.detect", { workspace_id: workspaceId });
}

function utcNow(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

/**
 * Turns `features.harness` on in the folder's local config. Only the local
 * toggle changes: no harness file is written before a confirmed apply.
 */
export async function enableHarnessFeature(platform: Platform, workspaceId: string): Promise<HarnessOutcome<null>> {
  const stored = await call<Record<string, unknown>>(platform, "workspace.get_config", { workspace_id: workspaceId });
  if (!stored.ok) return stored;
  const config = stored.value;
  const features = (config["features"] as Record<string, unknown> | undefined) ?? {};
  if (features["harness"] === true) return { ok: true, value: null };
  const saved = await call(platform, "workspace.save_config", {
    config: { ...config, features: { ...features, harness: true }, updated_at: utcNow() },
    current_roots: config["roots"],
    ...(typeof config["updated_at"] === "string" ? { expected_updated_at: config["updated_at"] } : {}),
  });
  return saved.ok ? { ok: true, value: null } : saved;
}

/**
 * Asking for a preview is the user's request to connect this folder: a
 * folder whose harness integrations are still off gets them turned on once.
 */
export async function previewHarness(platform: Platform, workspaceId: string, adapterId: string): Promise<HarnessOutcome<HarnessPlan>> {
  const payload = { workspace_id: workspaceId, adapter_id: adapterId };
  const first = await call<HarnessPlan>(platform, "harness.preview", payload);
  if (first.ok || first.error.code !== "feature_disabled") return first;
  const enabled = await enableHarnessFeature(platform, workspaceId);
  if (!enabled.ok) return enabled;
  return call(platform, "harness.preview", payload);
}

export function applyHarness(platform: Platform, plan: HarnessPlan): Promise<HarnessOutcome<HarnessApplyResult>> {
  return call(platform, "harness.apply", { plan_id: plan.plan_id, plan_hash: plan.plan_hash, confirmed: true });
}

/** The daemon resolves this alias to the newest restorable backup of the harness. */
export function latestRollbackId(workspaceId: string, adapterId: string): string {
  return `latest:${workspaceId}:${adapterId}`;
}

export function rollbackHarness(platform: Platform, rollbackId: string): Promise<HarnessOutcome<HarnessRollbackResult>> {
  return call(platform, "harness.rollback", { rollback_id: rollbackId, confirmed: true });
}

/** Proves the harness can reach Studi'OS: a real MCP call, nothing is written. */
export function verifyHarness(platform: Platform, workspaceId: string, adapterId: string): Promise<HarnessOutcome<HarnessVerifyResult>> {
  return call(platform, "harness.verify", { workspace_id: workspaceId, adapter_id: adapterId });
}

export const VERIFY_TONES: Record<VerifyState, "neutral" | "success" | "warning" | "danger" | "info"> = {
  unconfigured: "neutral",
  configured: "info",
  token_missing: "warning",
  verified: "success",
  failed: "danger",
};

/** Fixed French wording per verification state: the daemon's text is never displayed. */
export const VERIFY_MESSAGES: Record<VerifyState, string> = {
  unconfigured: "Le harnais n'est pas encore configuré pour Studi'OS.",
  configured: "Configuration en place ; la connexion n'a pas pu être vérifiée.",
  token_missing:
    "Configuration en place, mais aucun jeton machine n'est fourni au harnais : ses appels au MCP Studi'OS seront refusés. " +
    "Studi'OS Desktop ne transmet pas encore ce jeton automatiquement. En attendant, lancez le harnais depuis un terminal " +
    "où la variable STUDIO_MCP_MACHINE_TOKEN contient le jeton de ce poste, puis vérifiez à nouveau.",
  verified: "Connexion vérifiée : le harnais s'authentifie auprès du MCP Studi'OS.",
  failed: "La connexion au MCP Studi'OS a échoué. Vérifiez que le serveur est joignable et que ce poste est toujours enrôlé, puis réessayez.",
};

export const STATE_LABELS: Record<HarnessState, string> = {
  not_detected: "Non installé",
  detected: "Installé · non configuré",
  configured: "Configuré",
  incompatible: "Version non prise en charge",
  error: "Indisponible",
};

export const STATE_TONES: Record<HarnessState, "neutral" | "success" | "warning" | "danger" | "info"> = {
  not_detected: "neutral",
  detected: "info",
  configured: "success",
  incompatible: "warning",
  error: "danger",
};

const REASONS: Record<string, string> = {
  executable_not_found: "L'exécutable n'a pas été trouvé sur ce poste.",
  unsupported_version: "Cette version n'est pas prise en charge : Studi'OS ne modifie pas une configuration qu'il ne connaît pas.",
  unexpected_output: "L'exécutable trouvé ne s'identifie pas comme ce harnais.",
  probe_failed: "L'exécutable n'a pas répondu correctement.",
  timeout: "L'exécutable n'a pas répondu à temps.",
  permission_denied: "Accès refusé : vérifiez les droits sur le dossier de travail.",
  read_only: "Le fichier de configuration est en lecture seule.",
  ambiguous_config: "Plusieurs fichiers de configuration existent : rien n'est modifié.",
  entry_differs: "Une entrée Studi'OS différente existe déjà.",
  changed_since_preview: "Le fichier a changé depuis l'aperçu. Recommencez l'aperçu.",
  plan_unknown: "Cet aperçu n'existe plus. Recommencez l'aperçu.",
  plan_expired: "Cet aperçu a expiré. Recommencez l'aperçu.",
  plan_hash_mismatch: "L'aperçu ne correspond plus. Recommencez l'aperçu.",
  rollback_conflict: "Le fichier a été modifié depuis la configuration : la restauration est refusée pour ne pas écraser vos changements.",
  rollback_unknown: "Aucune sauvegarde à restaurer.",
  already_rolled_back: "Cette sauvegarde a déjà été restaurée.",
  not_applied: "Aucune configuration appliquée à restaurer.",
  feature_disabled: "Les intégrations IA ne sont pas activées pour ce dossier.",
  backup_failed: "La sauvegarde n'a pas pu être créée : rien n'a été modifié.",
  verify_failed: "La vérification après écriture a échoué : l'original a été rétabli.",
  restore_failed: "La vérification a échoué et l'original n'a pas pu être rétabli automatiquement. Utilisez « Restaurer » ; une sauvegarde locale est conservée.",
  unsafe_path: "Emplacement de configuration refusé.",
  symlink: "Emplacement de configuration refusé (lien symbolique).",
  too_large: "Le fichier de configuration est trop volumineux.",
  not_utf8: "Le fichier de configuration n'est pas un texte valide.",
  syntax: "Le fichier de configuration n'est pas valide : rien n'est modifié.",
  workspace_unknown: "Dossier local inconnu de Studi'OS Desktop.",
  adapter_unknown: "Harnais inconnu.",
};

/** A user-facing sentence for a refusal; never raw daemon text, paths or secrets. */
export function harnessErrorMessage(error: LocalError | null | undefined): string {
  if (!error) return "L'opération a échoué.";
  const reason = error.details?.["reason"];
  if (typeof reason === "string" && REASONS[reason]) return REASONS[reason];
  switch (error.code) {
    case "daemon_unavailable":
      return "L'assistant local de Studi'OS Desktop n'est pas disponible.";
    case "capability_missing":
    case "not_supported":
      return "Cette fonction n'est disponible que dans Studi'OS Desktop.";
    case "feature_disabled":
      return REASONS["feature_disabled"] ?? "";
    case "workspace_config_missing":
      return REASONS["workspace_unknown"] ?? "";
    case "permission_denied":
      return REASONS["permission_denied"] ?? "";
    default:
      return "L'opération a échoué. Aucune modification n'a été confirmée.";
  }
}

export const CHANGE_LABELS: Record<string, string> = { create: "Création", modify: "Modification", delete: "Suppression" };

/** Fixed French wording per kind: the daemon's English summary is never displayed. */
export const CHANGE_DETAILS: Record<string, string> = {
  create: "Le fichier est créé avec l'entrée MCP studio-os.",
  modify: "L'entrée MCP studio-os est ajoutée ou remplacée ; les autres réglages sont conservés et l'ancien fichier est sauvegardé.",
  delete: "Le fichier est supprimé ; l'ancien contenu est sauvegardé.",
};
