import type { Platform } from "../platform";
import type { StudioClient } from "../api";
import { newUuid } from "../ui";
import type {
  DetectedRepositoryListResult,
  DetectedRepositoryView,
  LocalWorkspaceConfig,
  WorkspaceListResult,
  WorkspaceStatus,
} from "../platform/generated/local-contracts.generated";
import { callWorkspace, type WorkspaceOutcome } from "../onboarding/workspaceApi";

export { confirmRoots, saveWorkspaceConfig, workspaceErrorMessage } from "../onboarding/workspaceApi";
export type { WorkspaceOutcome } from "../onboarding/workspaceApi";
export type { DetectedRepositoryView };

export async function listWorkspaces(platform: Platform): Promise<WorkspaceOutcome<WorkspaceStatus[]>> {
  const result = await callWorkspace<WorkspaceListResult>(platform, "workspace.list", {});
  return result.ok ? { ok: true, value: result.value.items ?? [] } : result;
}

/**
 * P3-detected — dépôts `unresolved` enregistrés par `resolve_workspace`
 * (racine, remotes normalisés, dernière vue), sans autre dossier suivi.
 * Lecture seule : jamais un chemin brut vers le serveur, jamais un secret.
 */
export async function listDetectedRepositories(
  platform: Platform,
): Promise<WorkspaceOutcome<DetectedRepositoryView[]>> {
  const result = await callWorkspace<DetectedRepositoryListResult>(
    platform,
    "workspace.list_detected",
    {},
  );
  return result.ok ? { ok: true, value: result.value.items ?? [] } : result;
}

/** Nom d'affichage d'un dépôt détecté : dernier segment, jamais le chemin brut. */
export function detectedFolderName(root: string): string {
  const parts = root.split(/[\\/]+/).filter((part) => part !== "");
  return parts.length === 0 ? root : (parts[parts.length - 1] as string);
}

export interface DetectedLinkRequest {
  root: string;
  /** Premier remote normalisé, ou `null` pour un dépôt sans remote (lien manuel). */
  remote: string | null;
  projectId: string;
  projectSlug: string;
  profile: LocalWorkspaceConfig["profile"];
}

export type DetectedLinkResult = { ok: true } | { ok: false; message: string };

const linkFail = (message: string): DetectedLinkResult => ({ ok: false, message });

/**
 * P3-detected — « Lier à un projet » en un geste : ajoute le remote aux
 * `repositories` du projet choisi (sauf dépôt sans remote : lien manuel
 * direct), puis crée la configuration locale via `confirm_roots` /
 * `save_config` — l'équivalent d'un `resolve` réussi, sans autre action.
 * Le pont oublie l'entrée détectée à la sauvegarde : le dépôt rejoint les
 * dossiers suivis. Phrases FR fixes, jamais le texte brut du serveur.
 */
export async function linkDetectedRepository(
  client: StudioClient,
  platform: Platform,
  request: DetectedLinkRequest,
): Promise<DetectedLinkResult> {
  if (request.remote !== null) {
    const linked = await client.POST("/api/v1/projects/{project_id}/repositories", {
      params: { path: { project_id: request.projectId } },
      body: { url: request.remote },
    });
    if (!linked.response.ok) {
      const status = linked.response.status;
      if (status === 409)
        return linkFail("Ce dépôt est déjà rattaché à un autre projet. Demandez l'accès à ce projet ou choisissez-en un autre.");
      if (status === 422)
        return linkFail("L'adresse du dépôt est invalide. Aucune modification n'a été appliquée.");
      if (status === 403)
        return linkFail("Accès refusé : seul un admin ou un developer peut rattacher un dépôt.");
      if (status === 404) return linkFail("Projet introuvable sur le serveur.");
      return linkFail("Le rattachement a échoué. Aucune modification n'a été appliquée.");
    }
  }
  const confirmed = await callWorkspace<{ root_confirmation_id: string }>(
    platform,
    "workspace.confirm_roots",
    { roots: { workspace_root: request.root, repo_roots: [] } },
  );
  if (!confirmed.ok)
    return linkFail("Le dossier est inaccessible. Vérifiez son emplacement et vos droits.");
  const now = new Date().toISOString();
  const saved = await callWorkspace(platform, "workspace.save_config", {
    config: {
      schema_version: 1,
      workspace_id: newUuid(),
      profile: request.profile,
      project_id: request.projectId,
      project_slug: request.projectSlug,
      roots: { workspace_root: request.root, repo_roots: [] },
      features: { watchers: true, knowledge: false, code_graph: false, harness: false },
      secret_references: [],
      created_at: now,
      updated_at: now,
    },
    current_roots: null,
    root_confirmation_id: confirmed.value.root_confirmation_id,
  });
  if (!saved.ok) return linkFail("Le dossier n'a pas pu être suivi. Aucun dépôt n'a été perdu.");
  return { ok: true };
}

function folderKey(path: string): string {
  return path.replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();
}

export function findLinkedWorkspace(items: WorkspaceStatus[], projectId: string, root: string): WorkspaceStatus | undefined {
  const wanted = folderKey(root);
  return items.find((item) => item.config?.project_id === projectId && folderKey(item.config.roots.workspace_root) === wanted);
}

export async function findLinkedWorkspaceId(platform: Platform, projectId: string, root: string): Promise<string | undefined> {
  const listed = await listWorkspaces(platform);
  return listed.ok ? findLinkedWorkspace(listed.value, projectId, root)?.workspace_id : undefined;
}

export function getWorkspaceConfig(platform: Platform, workspaceId: string): Promise<WorkspaceOutcome<LocalWorkspaceConfig>> {
  return callWorkspace(platform, "workspace.get_config", { workspace_id: workspaceId });
}
