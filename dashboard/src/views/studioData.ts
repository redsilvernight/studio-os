/**
 * Fiche N7 — Export et suppression d'un studio (docs/maquettes-atelier/nouveaux.html).
 *
 * « Le client possède ses données » : export complet d'abord, suppression
 * confirmée ensuite (dialogue de conséquences, nom à retaper, délai de grâce
 * de 14 jours annulable). Jamais de suppression silencieuse.
 *
 * Contrat : POST /studios/{id}/exports -> {id} ; GET /studios/{id}/exports/{eid}
 * -> {download_url, expires_at} (lien pré-signé court) ; POST /studios/{id}/deletion
 * {confirm_slug} -> {deletion_scheduled_at} ; DELETE /studios/{id}/deletion annule
 * pendant le délai. L'export est permis dans tous les états (limite, suspendu) ;
 * la suppression est réservée au propriétaire.
 *
 * Les chiffres du dialogue de conséquences (projets, notes, volume) sont des
 * illustrations de la maquette : aucun endpoint de statistiques n'existe dans
 * le contrat — le texte par défaut est celui de la fiche.
 */
import { describeError, esc } from "../ui";
import { ApiError } from "../api";
import { confirmDs } from "../ds/confirm";
import { dsField, dsNotify, dsPageHeader, dsSkeleton, dsTechDetails, focusDsErrorBox, openDsDialog } from "../ds/ds";
import { dsIcon } from "../ds/lot1";
import {
  cancelStudioDeletion,
  createStudioExport,
  getStudio,
  getStudioExport,
  scheduleStudioDeletion,
  type Studio,
} from "../studioLifecycleApi";
import { formatDayLabel } from "../studioLifecycleFormat";
import "./studioLifecycle.css";

export interface StudioDataContext {
  baseUrl: string;
  authed: boolean;
}

export const DELETE_DIALOG_ID = "studio-delete-dialog";

/** Polling de l'export : le serveur prévient quand c'est prêt (fiche « prep »). */
export const EXPORT_POLL_INTERVAL_MS = 3000;
export const EXPORT_POLL_MAX_ATTEMPTS = 40;

/** Texte de conséquences par défaut — celui de la fiche (valeurs illustratives). */
export const DELETION_CONSEQUENCES_DEFAULT =
  "Seront effacés : tous les projets, notes, fichiers et l'historique du studio. " +
  "Les sauvegardes disparaissent à la fin de la rétention annoncée (30 jours). Vous pourrez annuler pendant le délai de grâce.";

export type StudioExportState =
  | { kind: "none" }
  | { kind: "preparing" }
  | { kind: "ready"; fileName: string; downloadUrl: string; size?: string }
  | { kind: "error"; message: string }
  | { kind: "limit" };

function bannerHtml(tone: "success" | "warning" | "danger", title: string, bodyHtml: string): string {
  const icon = tone === "success" ? "check" : "alert-triangle";
  return (
    `<div class="ds-banner ds-banner--${tone}" role="${tone === "danger" ? "alert" : "status"}">${dsIcon(icon, 20)}` +
    `<div class="ds-banner-body"><strong>${esc(title)}</strong><span>${bodyHtml}</span></div></div>`
  );
}

/** Carte « Exporter le studio » (état normal de la fiche). */
export function studioExportCardHtml(): string {
  return (
    `<section class="ds-card" aria-label="Exporter le studio"><h2>Exporter le studio</h2>` +
    `<p class="ds-list-sub">Une archive datée de tout votre studio : projets, notes, fichiers, journal. Le lien est valable 15 minutes.</p>` +
    `<div class="studio-actions"><button type="button" class="ds-btn ds-btn--primary" data-export-start>Préparer l'export</button></div></section>`
  );
}

/** Carte « Export en préparation » : squelette + permission de quitter. */
export function studioExportPreparingHtml(): string {
  return (
    `<section class="ds-card" aria-label="Export en préparation"><h2>Export en préparation</h2>` +
    `${dsSkeleton(2)}` +
    `<p class="ds-list-sub">Vous pouvez quitter cette page : nous vous prévenons quand c'est prêt.</p></section>`
  );
}

/** Bandeau « Export · prêt » : archive, lien de téléchargement, relance. */
export function studioExportReadyHtml(ready: { fileName: string; downloadUrl: string; size?: string }): string {
  const size = ready.size === undefined ? "" : ` · ${esc(ready.size)}`;
  return (
    bannerHtml(
      "success",
      "Votre export est prêt",
      `${esc(ready.fileName)}${size} · lien valable 15 minutes.` +
        `<div class="studio-banner-actions"><a class="ds-btn ds-btn--primary" href="${esc(ready.downloadUrl)}" data-export-download>Télécharger</a>` +
        `<button type="button" class="ds-btn" data-export-start>Préparer un nouvel export</button></div>`,
    ) + `<p class="ds-list-sub mono studio-tech-line">lien pré-signé court, une seule utilisation</p>`
  );
}

/** Bandeau « Erreur · export échoué » : rien n'a été modifié, détail replié. */
export function studioExportErrorHtml(message: string): string {
  return (
    bannerHtml(
      "danger",
      "Impossible de charger cette page",
      `L'export n'a pas pu être préparé. Rien n'a été modifié.` +
        `<div class="studio-banner-actions"><button type="button" class="ds-btn" data-export-start>Relancer l'export</button>` +
        `<button type="button" class="ds-btn ds-btn--ghost" data-export-detail>Voir le détail</button></div>`,
    ) + dsTechDetails([{ label: "Erreur", value: message }], "Détail de l'échec")
  );
}

/** Bandeau « Limite · 1 export à la fois ». */
export function studioExportLimitHtml(): string {
  return bannerHtml(
    "warning",
    "Un export est déjà en cours",
    `Un seul export à la fois. Le prochain sera possible dès que celui-ci sera terminé.` +
      `<div class="studio-banner-actions"><button type="button" class="ds-btn" data-export-progress>Voir l'avancement</button></div>`,
  );
}

/** État « Vide · rien à exporter ». */
export function studioDataEmptyHtml(): string {
  return (
    `<section class="ds-card"><div class="ds-empty ds-empty--illustrated" role="status">` +
    `<span class="ds-empty-art" aria-hidden="true">${dsIcon("inbox", 40)}</span>` +
    `<h3>Studio vide</h3><p>Il n'y a encore rien à exporter dans ce studio.</p></div></section>`
  );
}

/** Zone sensible « Supprimer le studio » : bordée danger, réservée au propriétaire. */
export function studioDangerZoneHtml(options: { isOwner: boolean }): string {
  const hint = options.isOwner
    ? "Effacement définitif après un délai de grâce de 14 jours. Réservé au propriétaire."
    : "Réservé au propriétaire.";
  const disabled = options.isOwner ? "" : ` disabled aria-disabled="true"`;
  return (
    `<section class="ds-card studio-card--danger" aria-label="Supprimer le studio"><h2>Supprimer le studio</h2>` +
    `<p class="ds-list-sub">${esc(hint)}</p>` +
    `<div class="studio-actions"><button type="button" class="ds-btn ds-btn--danger" data-delete-open${disabled}>Supprimer le studio…</button></div></section>`
  );
}

/** Bandeau « Délai de grâce · annulation possible ». */
export function studioDeletionGraceHtml(deletionScheduledAt: string): string {
  return bannerHtml(
    "warning",
    `Suppression programmée le ${formatDayLabel(deletionScheduledAt)}`,
    `Le studio est en lecture seule. Vous pouvez annuler jusqu'à cette date ; ensuite l'effacement est définitif.` +
      `<div class="studio-banner-actions"><button type="button" class="ds-btn ds-btn--primary" data-deletion-cancel>Annuler la suppression</button>` +
      `<button type="button" class="ds-btn" data-export-start>Exporter avant</button></div>`,
  );
}

/** Dialogue de conséquences (alertdialog) : nom à retaper avant confirmation. */
export function studioDeletionDialogHtml(studioName: string, consequences = DELETION_CONSEQUENCES_DEFAULT): string {
  const field = dsField(
    "delete-confirm-name",
    "Tapez le nom du studio pour confirmer",
    `<input class="ds-input" id="FIELD" name="confirm_name" type="text" autocomplete="off">`,
  );
  return (
    `<div class="ds-overlay" id="${DELETE_DIALOG_ID}" hidden><div class="ds-modal" role="alertdialog" aria-modal="true" ` +
    `aria-labelledby="${DELETE_DIALOG_ID}-title"><h2 id="${DELETE_DIALOG_ID}-title">Supprimer ${esc(studioName)} ?</h2>` +
    `<div><p>${esc(consequences)}</p>${field}` +
    `<div class="ds-dialog-actions">` +
    `<button type="button" class="ds-btn ds-btn--danger" data-delete-confirm disabled aria-disabled="true">Supprimer définitivement dans 14 jours</button>` +
    `<button type="button" class="ds-btn" data-ds-close>Annuler</button></div>` +
    `<div data-delete-msg class="ds-list-sub" role="status"></div></div></div></div>`
  );
}

/** Page complète : en-tête, grâce éventuelle, export, zone sensible, dialogue. */
export function studioDataPageHtml(options: {
  studioName: string;
  deletionScheduledAt: string | null;
  exportState: StudioExportState;
  isOwner: boolean;
  empty?: boolean;
}): string {
  const grace =
    options.deletionScheduledAt === null ? "" : studioDeletionGraceHtml(options.deletionScheduledAt);
  let exportArea: string;
  switch (options.exportState.kind) {
    case "preparing":
      exportArea = studioExportPreparingHtml();
      break;
    case "ready":
      exportArea = studioExportReadyHtml(options.exportState);
      break;
    case "error":
      exportArea = studioExportErrorHtml(options.exportState.message);
      break;
    case "limit":
      exportArea = studioExportLimitHtml();
      break;
    default:
      exportArea = options.empty === true ? studioDataEmptyHtml() : studioExportCardHtml();
  }
  // Fiche N7 : délai de grâce, préparation, prêt et erreur ne montrent que
  // leur bandeau ; la zone « Supprimer le studio… » n'apparaît qu'aux états
  // normal et limite.
  const showDanger =
    options.deletionScheduledAt === null &&
    (options.exportState.kind === "none" || options.exportState.kind === "limit") &&
    options.empty !== true;
  return (
    dsPageHeader("Confidentialité", "Qui peut voir quoi, et les accès exceptionnels au studio.") +
    grace +
    `<div class="studio-sections">${exportArea}${showDanger ? studioDangerZoneHtml({ isOwner: options.isOwner }) : ""}</div>` +
    studioDeletionDialogHtml(options.studioName)
  );
}

/* ------------------------------------------------------------------ */
/* Rendu                                                               */
/* ------------------------------------------------------------------ */

function exportFileName(studio: Studio): string {
  const day = new Date().toISOString().slice(0, 10);
  return `${studio.name.replace(/\s+/g, "-")}-${day}.zip`;
}

async function pollExport(baseUrl: string, studioId: string, exportId: string): Promise<{ downloadUrl: string }> {
  for (let attempt = 0; attempt < EXPORT_POLL_MAX_ATTEMPTS; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, EXPORT_POLL_INTERVAL_MS));
    try {
      const link = await getStudioExport(baseUrl, studioId, exportId);
      if (link.download_url !== "") return { downloadUrl: link.download_url };
    } catch (error) {
      // Pas encore prêt (404/409) : on continue ; toute autre erreur remonte.
      if (!(error instanceof ApiError) || (error.status !== 404 && error.status !== 409)) throw error;
    }
  }
  throw new Error("L'export prend plus de temps que prévu.");
}

/** Rendu de l'écran N7 : export + zone sensible, avec le délai de grâce. */
export async function renderStudioData(root: HTMLElement, ctx: StudioDataContext, studioId: string): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = studioDataPageHtml({
      studioName: "",
      deletionScheduledAt: null,
      exportState: { kind: "error", message: "Session requise : ouvrez une session pour exporter ou supprimer." },
      isOwner: false,
    });
    return;
  }
  root.innerHTML = `<div class="studio-sections">${dsSkeleton(3)}</div>`;
  let studio: Studio;
  try {
    studio = await getStudio(ctx.baseUrl, studioId);
  } catch (error) {
    root.innerHTML = studioDataPageHtml({
      studioName: "",
      deletionScheduledAt: null,
      exportState: { kind: "error", message: describeError(error) },
      isOwner: false,
    });
    return;
  }

  let currentExport: StudioExportState = { kind: "none" };

  const paint = (exportState: StudioExportState): void => {
    currentExport = exportState;
    root.innerHTML = studioDataPageHtml({
      studioName: studio.name,
      deletionScheduledAt: studio.deletion_scheduled_at ?? null,
      exportState,
      isOwner: studio.role === "owner",
    });
    wire();
  };

  const startExport = (): void => {
    paint({ kind: "preparing" });
    createStudioExport(ctx.baseUrl, studio.id)
      .then((created) => pollExport(ctx.baseUrl, studio.id, created.id))
      .then(({ downloadUrl }) => {
        paint({ kind: "ready", fileName: exportFileName(studio), downloadUrl });
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 409) {
          paint({ kind: "limit" });
          return;
        }
        paint({ kind: "error", message: describeError(error) });
      });
  };

  const wire = (): void => {
    root.querySelectorAll<HTMLElement>("[data-export-start]").forEach((button) => {
      button.addEventListener("click", startExport);
    });
    root.querySelector("[data-export-progress]")?.addEventListener("click", () => paint({ kind: "preparing" }));
    root.querySelector<HTMLElement>("[data-export-detail]")?.addEventListener("click", () => {
      const details = root.querySelector<HTMLDetailsElement>(".ds-tech");
      if (details !== null) {
        details.open = true;
        focusDsErrorBox(details);
      }
    });
    root.querySelector<HTMLElement>("[data-delete-open]")?.addEventListener("click", () => {
      openDsDialog(root, DELETE_DIALOG_ID, root.querySelector<HTMLElement>("[data-delete-open]"));
      wireDeleteDialog();
    });
    root.querySelector<HTMLElement>("[data-deletion-cancel]")?.addEventListener("click", async () => {
      const ok = await confirmDs(
        "Annuler la suppression programmée ? Le studio redeviendra modifiable immédiatement.",
        { title: "Annuler la suppression", confirmLabel: "Annuler la suppression" },
      );
      if (!ok) return;
      try {
        await cancelStudioDeletion(ctx.baseUrl, studio.id);
        studio = { ...studio, deletion_scheduled_at: null };
        paint(currentExport);
        dsNotify("Suppression annulée : le studio est rouvert.", "success");
      } catch (error) {
        dsNotify(describeError(error), "danger");
      }
    });
  };

  const wireDeleteDialog = (): void => {
    const input = root.querySelector<HTMLInputElement>(`#${DELETE_DIALOG_ID} input[name="confirm_name"]`);
    const confirmButton = root.querySelector<HTMLButtonElement>("[data-delete-confirm]");
    const msg = root.querySelector<HTMLElement>("[data-delete-msg]");
    if (input === null || confirmButton === null) return;
    input.addEventListener("input", () => {
      const matches = input.value.trim() === studio.name || input.value.trim() === studio.slug;
      confirmButton.disabled = !matches;
      if (matches) confirmButton.removeAttribute("aria-disabled");
      else confirmButton.setAttribute("aria-disabled", "true");
    });
    confirmButton.addEventListener("click", () => {
      confirmButton.disabled = true;
      scheduleStudioDeletion(ctx.baseUrl, studio.id, studio.slug)
        .then((result) => {
          studio = { ...studio, deletion_scheduled_at: result.deletion_scheduled_at };
          paint({ kind: "none" });
          dsNotify("Suppression programmée. Vous pouvez l'annuler pendant 14 jours.", "warning");
        })
        .catch((error: unknown) => {
          confirmButton.disabled = false;
          if (msg !== null) {
            msg.textContent = describeError(error);
            focusDsErrorBox(msg);
          }
        });
    });
  };

  paint({ kind: "none" });
}
