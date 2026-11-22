/**
 * Bandeau « studio suspendu » persistant en tête de toutes les pages du studio
 * actif (fiche N5 : « Bandeau persistant en tête de toutes les pages du
 * studio »). Le statut vient de GET /studios/{id} pour le studio actif
 * (studioContext) ; aucun motif n'est exposé par l'API, donc aucun motif
 * n'est affiché ici — le détail est sur l'écran dédié (#/studios/{id}/suspended).
 */
import { esc } from "./ui";
import { dsIcon } from "./ds/lot1";
import { getActiveStudioId } from "./studioContext";
import { getStudio } from "./studioLifecycleApi";

const SUSPENDED_BANNER_ID = "studio-suspended-banner";

/** Pur : contenu du bandeau pour un studio suspendu. */
export function suspendedShellBannerHtml(studioId: string, studioName: string): string {
  return (
    `<div class="ds-banner ds-banner--danger">${dsIcon("alert-triangle", 20)}` +
    `<div class="ds-banner-body"><strong>${esc(studioName)} est suspendu</strong>` +
    `<span>Lecture seule : vous pouvez consulter et exporter, mais plus rien ne peut être modifié ni envoyé.</span></div>` +
    `<div class="studio-banner-actions"><a class="ds-btn" href="#/studios/${encodeURIComponent(studioId)}/suspended">En savoir plus</a></div></div>`
  );
}

let syncToken = 0;

/**
 * Synchronise le bandeau du shell avec le statut du studio actif. Non bloquant
 * pour le rendu : toute erreur (réseau, 403, studio supprimé) masque le bandeau.
 */
export async function syncSuspendedBanner(baseUrl: string, authed: boolean, onSuspendedPage: boolean): Promise<void> {
  const mine = ++syncToken;
  const slot = document.getElementById(SUSPENDED_BANNER_ID);
  if (slot === null) return;
  const studioId = authed && !onSuspendedPage ? getActiveStudioId() : null;
  if (studioId === null) {
    slot.hidden = true;
    slot.innerHTML = "";
    return;
  }
  try {
    const studio = await getStudio(baseUrl, studioId);
    if (mine !== syncToken) return;
    if (studio.status === "suspended") {
      slot.innerHTML = suspendedShellBannerHtml(studio.id, studio.name);
      slot.hidden = false;
      return;
    }
  } catch {
    if (mine !== syncToken) return;
  }
  slot.hidden = true;
  slot.innerHTML = "";
}
