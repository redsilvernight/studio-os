/**
 * P3 x P5 — page « Dossiers » (Desktop seulement).
 *
 * La sélection passe par le sélecteur natif P3 (`platform.chooseFolder`), jamais
 * par une commande du pont (`workspace.pick_folder` n'existe pas). Le pont
 * `workspace.*` n'est pas encore servi par l'assistant local : la page le dit
 * au lieu de simuler une association réussie.
 */
import { getPlatform, type PickResult, type Platform } from "../platform";
import { esc } from "../ui";
import { dsPageHeader } from "../ds/ds";
import { workspaceListHtml } from "../workspaces/workspaces";

export type FolderPickOutcome =
  | { kind: "selected"; path: string; displayName: string }
  | { kind: "cancelled" }
  | { kind: "unavailable" }
  | { kind: "error"; code: string };

/** Native pick -> closed outcome; malformed or non-absolute answers are never a selection. */
export function toFolderOutcome(result: PickResult): FolderPickOutcome {
  switch (result.status) {
    case "selected": {
      const path = typeof result.path === "string" ? result.path : "";
      if (path === "" || path.length > 4096) return { kind: "error", code: "invalid_selection" };
      return { kind: "selected", path, displayName: result.display_name };
    }
    case "cancelled":
      return { kind: "cancelled" };
    case "unavailable":
      return { kind: "unavailable" };
    default:
      return { kind: "error", code: typeof result.code === "string" ? result.code : "error" };
  }
}

export async function pickWorkspaceFolder(platform: Platform = getPlatform()): Promise<FolderPickOutcome> {
  try {
    return toFolderOutcome(await platform.chooseFolder({ title: "Choisir le dossier du projet" }));
  } catch {
    return { kind: "error", code: "picker_failed" };
  }
}

export function outcomeMessage(outcome: FolderPickOutcome | null): string {
  if (outcome === null) return "";
  switch (outcome.kind) {
    case "selected":
      return `Dossier choisi : ${outcome.displayName}. L'association au projet sera confirmée par l'assistant local ; cette étape n'est pas encore disponible dans cette version.`;
    case "cancelled":
      return "Sélection annulée. Aucun dossier n'a été modifié.";
    case "unavailable":
      return "Le sélecteur de dossier natif n'est pas disponible ici.";
    default:
      return "Le dossier n'a pas pu être sélectionné. Aucun dossier n'a été modifié.";
  }
}

export function workspacesPageHtml(mode: "web" | "desktop", outcome: FolderPickOutcome | null): string {
  const header = dsPageHeader("Dossiers", "Dossiers locaux associés à vos projets.");
  if (mode === "web") {
    return `${header}<section class="ds-card" data-testid="workspaces-web"><p>Les dossiers locaux sont gérés dans Studi'OS Desktop.</p></section>`;
  }
  const message = outcomeMessage(outcome);
  const status = message === "" ? "" : `<p role="status" data-testid="workspaces-outcome" data-outcome="${esc(outcome?.kind ?? "")}">${esc(message)}</p>`;
  return `${header}<section class="ds-card" data-testid="workspaces-desktop">
${workspaceListHtml([])}
<p><button class="ds-btn ds-btn--primary" type="button" id="workspace-add">Ajouter un dossier</button></p>
${status}
</section>`;
}

export async function renderWorkspaces(root: HTMLElement, platform: Platform = getPlatform(), outcome: FolderPickOutcome | null = null): Promise<void> {
  root.innerHTML = workspacesPageHtml(platform.mode, outcome);
  if (platform.mode === "web") return;
  root.querySelector<HTMLButtonElement>("#workspace-add")?.addEventListener("click", () => {
    void pickWorkspaceFolder(platform).then((picked) => renderWorkspaces(root, platform, picked));
  });
}
