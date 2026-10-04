/**
 * P05-admin — Entrée « Administration » (UX V2, wireframes/admin.html).
 *
 * Une seule entrée mène aux 6 familles (Postes, Comptes, Transferts,
 * Bibliothèque, Configuration, Espaces de travail) : chaque famille est à
 * 1 clic de l'entrée, chaque détail à 2 clics maximum (C1). Noms humains
 * partout, aucun identifiant visible par défaut (C2) ; ≤ 3 blocs majeurs
 * (héros, familles, contexte + rappels à 2560) (C3) ; aucun statut de
 * connexion ici — l'unique `connection-status` vit dans le shell (C4).
 *
 * Aucune donnée inventée : sous-titres descriptifs (pas de comptes
 * fictifs), liens vers les routes existantes uniquement. Graphes et
 * Inspecteur restent des outils experts hors de cette entrée (review-admin).
 */
import { dsHeroCard, dsPageHeader } from "../ds/ds";
import { esc } from "../ui";
import "./admin.css";

export interface AdminFamily {
  href: string;
  title: string;
  hint: string;
  mark: string;
}

export const ADMIN_FAMILIES: readonly AdminFamily[] = [
  { href: "#/machines", title: "Postes", hint: "Environnements où le travail s'exécute", mark: "P" },
  { href: "#/accounts", title: "Comptes et membres", hint: "Comptes, sessions et accès par projet", mark: "C" },
  { href: "#/transfers", title: "Transferts", hint: "Fichiers échangés entre postes", mark: "T" },
  { href: "#/library", title: "Bibliothèque", hint: "Règles, savoir-faire et configurations", mark: "B" },
  { href: "#/configuration/runtimes", title: "Configuration", hint: "Runtimes, liaisons, projet, appli, IA", mark: "R" },
  { href: "#/workspaces", title: "Espaces de travail", hint: "Dossiers suivis sur ce poste", mark: "D" },
];

function familyCardHtml(family: AdminFamily): string {
  return (
    `<li><a class="admin-fam" href="${esc(family.href)}">` +
    `<span class="admin-fam-pic" aria-hidden="true">${esc(family.mark)}</span>` +
    `<span class="admin-fam-body"><strong>${esc(family.title)}</strong>` +
    `<span class="ds-list-sub">${esc(family.hint)}</span></span>` +
    `<span class="admin-fam-chev" aria-hidden="true">›</span></a></li>`
  );
}

export function adminOverviewHtml(): string {
  const hero = dsHeroCard({
    eyebrow: "Administration",
    title: "Garder le système sain",
    body: "Comptes à revoir, postes à vérifier, fichiers et réglages : chaque surface s'ouvre en un clic, les détails techniques restent repliés.",
    primary: { label: "Revoir les comptes", href: "#/accounts" },
    secondary: [{ label: "Voir tous les comptes", href: "#/accounts" }],
  });
  const families = `<section class="ds-panel admin-families" aria-label="Familles"><header><h2>Familles</h2><span class="ds-list-sub">chaque surface en 1 clic</span></header><div class="body"><ul class="admin-fams">${ADMIN_FAMILIES.map(familyCardHtml).join("")}</ul></div></section>`;
  const context =
    `<aside class="ds-panel admin-context" aria-label="À surveiller"><header><h2>À surveiller</h2></header><div class="body">` +
    `<ul class="ds-list"><li class="ds-list-item"><span class="grow"><span class="ds-list-title">Comptes en attente</span><br /><span class="ds-list-sub">à vérifier dans Comptes et membres</span></span></li>` +
    `<li class="ds-list-item"><span class="grow"><span class="ds-list-title">Postes sans activité</span><br /><span class="ds-list-sub">à revoir dans Postes</span></span></li></ul>` +
    `<details class="ds-tech"><summary>Détails techniques</summary><dl class="ds-tech-list"><div><dt>Routes</dt><dd><code class="mono">#/administration</code> → familles ci-dessus</dd></div><div><dt>Experts</dt><dd>Graphes et Inspecteur vivent dans « Outils experts », pas ici</dd></div></dl></details>` +
    `</div></aside>`;
  const feed =
    `<aside class="ds-panel admin-feed" aria-label="Rappels"><header><h2>Rappels honnêtes</h2></header><div class="body">` +
    `<h3>Création et révocation</h3><p class="ds-list-sub">Les postes et les suppressions de fichiers passent par l'API ou le CLI, pas par des boutons inventés ici.</p>` +
    `<h3>Résolution</h3><p class="ds-list-sub">La compatibilité agent et runtime s'explique dans l'Inspecteur, pas dans ces écrans.</p>` +
    `</div></aside>`;
  return (
    `<div class="admin">` +
    `${dsPageHeader("Administration", "Vue d'ensemble des surfaces d'administration.")}` +
    `<div class="admin-layout"><div class="admin-main">${hero}${families}</div>${context}${feed}</div>` +
    `</div>`
  );
}

export async function renderAdmin(root: HTMLElement): Promise<void> {
  root.innerHTML = adminOverviewHtml();
}
