/**
 * Mises à jour de projections de projet en attente (`project_projections.*`).
 * Le démon calcule le plan et n'écrit dans le dépôt qu'après la confirmation
 * explicite de l'utilisateur ; le tableau de bord ne voit ni chemin ni contenu.
 */
import { esc } from "./ui";
import { call, type HarnessOutcome } from "./harnessApi";
import type { Platform } from "./platform";
import type {
  ProjectProjectionsApplyResult,
  ProjectProjectionsStatus,
} from "./platform/generated/local-contracts.generated";

export type { ProjectProjectionsApplyResult, ProjectProjectionsStatus };

export function getProjectProjectionsStatus(platform: Platform): Promise<HarnessOutcome<ProjectProjectionsStatus>> {
  return call(platform, "project_projections.status", {});
}

export function applyProjectProjections(
  platform: Platform,
  workspaceId: string,
): Promise<HarnessOutcome<ProjectProjectionsApplyResult>> {
  return call(platform, "project_projections.apply", { workspace_id: workspaceId, confirmed: true });
}

const FILE_STATE_LABELS = { absent: "à créer", obsolete: "à mettre à jour", modified: "modifié localement" } as const;

export function projectProjectionsHtml(status: ProjectProjectionsStatus | null, busy: boolean): string {
  const updates = status?.updates ?? [];
  if (updates.length === 0) return "";
  const items = updates.map((update) => {
    const files = (update.files ?? []).map((file) => `<li>${esc(file.path)} — ${FILE_STATE_LABELS[file.state]}</li>`).join("");
    return `<li class="project-projections-item"><p>${(update.files ?? []).length} fichier(s) générés à écrire dans un dépôt du projet.</p>` +
      `<details><summary>Fichiers concernés</summary><ul>${files}</ul></details>` +
      `<button class="ds-btn ds-btn--primary" type="button" data-project-projections-apply="${esc(update.workspace_id)}"${busy ? " disabled" : ""}>Confirmer l'écriture dans le dépôt</button></li>`;
  }).join("");
  return `<h3 class="skills-sync-section-title">Dépôts du projet à mettre à jour</h3>` +
    `<p class="skills-sync-help">Rien n'est écrit dans un dépôt avant votre confirmation. Les fichiers générés sont ignorés par git ; vos autres fichiers de réglage ne sont jamais modifiés.</p>` +
    `<ul class="skills-sync-list" data-project-projections>${items}</ul>`;
}
