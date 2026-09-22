/**
 * P11 — commandes `workspace.*` du pont local pour l'assistant de configuration.
 *
 * Même discipline que `harnessApi` : requêtes typées, renégociation unique
 * après `capability_missing`, phrases FR fixes (jamais le texte brut du
 * démon, jamais un chemin, jamais un secret).
 */
import type { Platform } from "../platform";
import type {
  LocalError,
  WorkspaceConfirmRootsResult,
  WorkspaceGitStatus,
  WorkspaceStatus,
} from "../platform/generated/local-contracts.generated";

export type WorkspaceOutcome<T> = { ok: true; value: T } | { ok: false; error: LocalError };

type Command = Parameters<Platform["request"]>[0];

/** Le démon oublie les capabilities au redémarrage : renégocie une fois. */
async function negotiate(platform: Platform): Promise<void> {
  try {
    const info = await platform.desktopInfo();
    if (info?.peer) await platform.request("runtime.handshake", { peer: info.peer });
  } catch {
    // L'appel suivant rapporte le refus.
  }
}

async function call<T>(
  platform: Platform,
  command: Command,
  payload: Record<string, unknown>,
): Promise<WorkspaceOutcome<T>> {
  let answer = await platform.request(command, payload);
  if (!answer.ok && answer.error.code === "capability_missing") {
    await negotiate(platform);
    answer = await platform.request(command, payload);
  }
  if (!answer.ok) return { ok: false, error: answer.error };
  return { ok: true, value: answer.response.payload as T };
}

export function validateWorkspace(
  platform: Platform,
  workspaceId: string,
): Promise<WorkspaceOutcome<WorkspaceStatus>> {
  return call(platform, "workspace.validate", { workspace_id: workspaceId });
}

export function confirmRoots(
  platform: Platform,
  roots: { workspace_root: string; repo_roots?: { name: string; path: string }[] },
): Promise<WorkspaceOutcome<WorkspaceConfirmRootsResult>> {
  return call(platform, "workspace.confirm_roots", {
    roots: { workspace_root: roots.workspace_root, repo_roots: roots.repo_roots ?? [] },
  });
}

export function workspaceGitStatus(
  platform: Platform,
  workspaceId: string,
): Promise<WorkspaceOutcome<WorkspaceGitStatus>> {
  return call(platform, "workspace.git_status", { workspace_id: workspaceId });
}

export function saveWorkspaceConfig(
  platform: Platform,
  payload: {
    config: Record<string, unknown>;
    current_roots: Record<string, unknown> | null;
    root_confirmation_id?: string;
    expected_updated_at?: string;
  },
): Promise<WorkspaceOutcome<Record<string, unknown>>> {
  return call(platform, "workspace.save_config", {
    config: payload.config,
    current_roots: payload.current_roots,
    ...(payload.root_confirmation_id ? { root_confirmation_id: payload.root_confirmation_id } : {}),
    ...(payload.expected_updated_at ? { expected_updated_at: payload.expected_updated_at } : {}),
  });
}

const HEALTH_LABELS: Record<string, string> = {
  valid: "Valide",
  config_missing: "Non associé",
  config_invalid: "À réparer",
  moved: "Dossier déplacé",
  inaccessible: "Inaccessible",
  project_unavailable: "Projet indisponible",
};

const ACTION_LABELS: Record<string, string> = {
  none: "Aucune action requise.",
  create_config: "Associez un dossier pour continuer.",
  repair_config: "La configuration locale doit être réparée.",
  confirm_relocation: "Confirmez le nouvel emplacement du dossier.",
  grant_access: "Rétablissez l'accès au dossier.",
  detach_workspace: "Le projet n'est plus disponible sur le serveur.",
};

/** Santé d'un dossier en phrase simple, sans chemin ni jargon. */
export function workspaceHealthMessage(status: WorkspaceStatus | null | undefined): string {
  if (!status) return "État du dossier inconnu.";
  const health = HEALTH_LABELS[status.health] ?? status.health;
  const action = ACTION_LABELS[status.action] ?? "";
  return action ? `${health} — ${action}` : health;
}

const GIT_LABELS: Record<string, string> = {
  valid: "Git détecté",
  not_a_repo: "Ce dossier n'est pas un dépôt Git",
  invalid_repo: "Dépôt Git illisible",
  git_absent: "Git n'est pas installé",
  inaccessible: "Dossier inaccessible",
};

/** État Git en phrase simple ; Git reste optionnel, jamais bloquant. */
export function gitStatusMessage(status: WorkspaceGitStatus | null | undefined): string {
  if (!status) return "État Git inconnu.";
  const base = GIT_LABELS[status.state] ?? status.state;
  if (status.state === "valid" && status.branch) return `${base} — branche ${status.branch}.`;
  if (status.state === "valid" && status.detached) return `${base} — révision détachée.`;
  if (status.state === "valid") return `${base}.`;
  return `${base} — Studi'OS fonctionnera sans suivi de branche.`;
}

/** Phrase d'erreur sûre pour un refus ; jamais de texte brut du démon. */
export function workspaceErrorMessage(error: LocalError | null | undefined): string {
  if (!error) return "L'opération a échoué.";
  switch (error.code) {
    case "daemon_unavailable":
      return "L'assistant local de Studi'OS Desktop n'est pas disponible.";
    case "capability_missing":
    case "not_supported":
      return "Cette fonction n'est disponible que dans Studi'OS Desktop.";
    case "workspace_config_missing":
      return "Aucun dossier n'est encore associé sur ce poste.";
    case "workspace_inaccessible":
      return "Le dossier est inaccessible. Vérifiez son emplacement et vos droits.";
    case "workspace_moved":
      return "Le dossier a été déplacé. Confirmez son nouvel emplacement.";
    case "workspace_config_invalid":
      return "La configuration locale est invalide. Réparez-la avant de continuer.";
    case "permission_denied":
      return "Accès refusé : vérifiez les droits sur le dossier.";
    case "invalid_request":
      return "La demande a été refusée. Aucune modification n'a été appliquée.";
    default:
      return "L'opération a échoué. Aucune modification n'a été confirmée.";
  }
}
