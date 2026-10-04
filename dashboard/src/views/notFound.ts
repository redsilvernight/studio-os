/**
 * Page 404 explicite (UI-2) : remplace le repli silencieux vers
 * l'Accueil. Aucune redirection surprenante, un chemin de retour.
 */
import { dsPageHeader, dsStateHtml } from "../ds/ds";

export function notFoundHtml(hash: string): string {
  return `${dsPageHeader("Page introuvable", "Cette adresse ne correspond à aucune page de Studi'OS.")}${dsStateHtml("notFound", { title: "Page introuvable", message: `« ${hash === "" ? "#/" : hash} » n'existe pas ou a été déplacée.`, action: { label: "Retour à l'Accueil", href: "#/" } })}`;
}

export function renderNotFound(view: HTMLElement, hash: string): void {
  view.innerHTML = notFoundHtml(hash);
}
