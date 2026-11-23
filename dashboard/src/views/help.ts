/**
 * Aide (R2-coque, fiche E1/E7) — route minimale `#/aide`.
 *
 * Lexique des rôles de studio, limites « sans objet » justifiées (pas de
 * promesse chiffrée : les seuils et prix sont des illustrations, DEC-0387 et
 * DEC-0383) et renvoi vers l'abonnement.
 */
import { dsPageHeader, dsSectionHeader } from "../ds/ds";
import { esc } from "../ui";
import { STUDIO_ROLE_LABELS } from "../studiosApi";

const ROLE_HELP: Array<{ role: keyof typeof STUDIO_ROLE_LABELS; text: string }> = [
  { role: "owner", text: "Crée le studio, gère les membres, l'abonnement et la suppression." },
  { role: "admin", text: "Gère les membres et les projets ; l'abonnement reste au propriétaire." },
  { role: "member", text: "Crée et modifie le contenu du studio." },
  { role: "viewer", text: "Consulte en lecture seule ; les actions sont masquées." },
];

export function helpHtml(): string {
  const roles = ROLE_HELP.map(
    (entry) => `<div><dt>${esc(STUDIO_ROLE_LABELS[entry.role])}</dt><dd>${esc(entry.text)}</dd></div>`,
  ).join("");
  return (
    `${dsPageHeader("Aide", "Rôles, limites et premiers pas dans l'Atelier.")}` +
    `<section aria-labelledby="help-roles">${dsSectionHeader("Rôles de studio")}` +
    `<dl class="ds-tech-list" id="help-roles">${roles}</dl></section>` +
    `<section aria-labelledby="help-limits">${dsSectionHeader("Limites")}` +
    `<p>Les formules et les seuils (stockage, envois) sont indicatifs : à 100 % d'un quota, les nouveaux envois sont refusés, la lecture et l'export restent possibles. Le détail chiffré vit sur la page Abonnement.</p>` +
    `<p><a class="ds-btn" href="#/abonnement">Voir l'abonnement</a></p></section>`
  );
}

export function renderHelp(view: HTMLElement): void {
  view.innerHTML = helpHtml();
}
