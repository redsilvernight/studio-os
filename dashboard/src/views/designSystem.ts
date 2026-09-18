/**
 * UI-1 — page interne de démonstration du Design System (DEC-0078).
 *
 * Route `#/design-system`, absente de la navigation de production :
 * surface de validation visuelle des primitives × états avant la
 * migration des pages métier (UI-2+). Aucun appel API, aucun texte
 * technique traduit, aucun mélange FR/EN.
 */
import {
  dsAgentBadge,
  dsAvatar,
  dsBadge,
  dsDrawerHtml,
  dsEmptyState,
  dsField,
  dsMetric,
  dsModalHtml,
  dsNotify,
  dsPageHeader,
  dsProgress,
  dsSectionHeader,
  dsSkeleton,
  dsStatus,
  dsTabsHtml,
  initDsTabs,
  openDsDialog,
} from "../ds/ds";
import { esc } from "../ui";

function demoSection(title: string, hint: string, body: string): string {
  return `<section class="ds-demo-section" aria-label="${esc(title)}">${dsSectionHeader(title)}<p>${esc(hint)}</p>${body}</section>`;
}

export function designSystemHtml(): string {
  const buttons = `<div class="ds-demo-row">
    <button class="ds-btn ds-btn--primary" type="button">Action principale</button>
    <button class="ds-btn" type="button">Action secondaire</button>
    <button class="ds-btn ds-btn--ghost" type="button">Action discrète</button>
    <button class="ds-btn ds-btn--danger" type="button">Action destructive</button>
    <button class="ds-btn ds-btn--sm" type="button">Compacte</button>
    <button class="ds-btn ds-btn--primary" type="button" disabled>Désactivée</button>
    <button class="ds-btn ds-btn--primary ds-btn--loading" type="button" disabled>Chargement…</button>
    <button class="ds-icon-btn" type="button" aria-label="Fermer">×</button>
  </div>`;

  const badges = `<div class="ds-demo-row">
    ${dsBadge("Neutre")}
    ${dsBadge("Succès", "success")}
    ${dsBadge("En attente", "warning")}
    ${dsBadge("Erreur", "danger")}
    ${dsBadge("IA · Auxiliaire", "ai")}
    ${dsBadge("Information", "info")}
  </div>
  <div class="ds-demo-row">
    ${dsStatus("success", "Connecté")}
    ${dsStatus("warning", "En attente")}
    ${dsStatus("danger", "Bloqué")}
    ${dsStatus("ai", "Agent actif")}
    ${dsStatus("idle", "Inconnu")}
  </div>`;

  const fields = `<div class="ds-demo-grid">
    ${dsField("ds-nom", "Nom du projet", `<input class="ds-input" id="FIELD" type="text" value="Studio" />`, "Nom affiché dans les listes.", "")}
    ${dsField("ds-recherche", "Rechercher", `<div class="ds-search"><span class="ds-search-icon" aria-hidden="true">⌕</span><input class="ds-input" id="FIELD" type="search" placeholder="Nom, mot-clé…" /></div>`)}
    ${dsField("ds-statut", "Statut", `<select class="ds-select" id="FIELD"><option>À faire</option><option>En cours</option><option>Bloqué</option></select>`)}
    ${dsField("ds-erreur", "Avec erreur", `<input class="ds-input" id="FIELD" type="text" value="!!" />`, "", "Ce champ est requis.")}
  </div>`;

  const tabs = dsTabsHtml("ds-demo", [
    { id: "liste", label: "Liste", panel: "<p>Premier panneau : contenu de la liste.</p>" },
    { id: "board", label: "Tableau", panel: "<p>Deuxième panneau : contenu du tableau.</p>" },
    { id: "calendrier", label: "Calendrier", panel: "<p>Troisième panneau : contenu du calendrier.</p>" },
  ]);

  const table = `<div class="ds-table-wrap"><table class="ds-table">
    <caption>Exemple : trois projets, colonnes utiles uniquement.</caption>
    <thead><tr><th scope="col">Nom</th><th scope="col">Statut</th><th scope="col">Mis à jour</th></tr></thead>
    <tbody>
      <tr><td>Phare</td><td>${dsStatus("success", "Actif")}</td><td>aujourd'hui</td></tr>
      <tr><td>Digue</td><td>${dsStatus("warning", "En pause")}</td><td>hier</td></tr>
    </tbody>
  </table></div>`;

  const list = `<ul class="ds-list">
    <li class="ds-list-item"><div class="grow"><div class="ds-list-title">Corriger le doublon de tâche</div><div class="ds-list-sub">Projet Phare · priorité haute</div></div>${dsBadge("Bloqué", "danger")}</li>
    <li class="ds-list-item"><div class="grow"><div class="ds-list-title">Relire la proposition d'agent</div><div class="ds-list-sub">En attente depuis hier</div></div>${dsBadge("À examiner", "warning")}</li>
  </ul>`;

  const states = `<div class="ds-card">${dsEmptyState("Aucune tâche", "Créez votre première tâche pour démarrer.", { label: "Créer une tâche", href: "#/design-system" })}</div>
  <div class="ds-card">${dsSkeleton(3)}</div>
  <div class="ds-demo-row">
    <div class="ds-notice ds-notice--success"><strong>Succès.</strong>La tâche a été créée.</div>
    <div class="ds-notice ds-notice--warning"><strong>En attente.</strong>La décision n'a pas encore de réponse.</div>
    <div class="ds-notice ds-notice--danger"><strong>Erreur.</strong>Le transfert a été interrompu, réessayez.</div>
    <div class="ds-notice ds-notice--info"><strong>Information.</strong>La présence affichée est dérivée, jamais canonique.</div>
  </div>`;

  const indicators = `<div class="ds-demo-grid">
    <div class="ds-card">${dsMetric("Tâches en cours", 4)}</div>
    <div class="ds-card">${dsProgress(2, 5, "2 Mo sur 5 Mo transférés (40 %)")}</div>
    <div class="ds-card"><div class="ds-demo-row">${dsAvatar("Amina Benali")}${dsAgentBadge("Auxiliaire de relecture")}</div></div>
  </div>`;

  const dialogs = `<div class="ds-demo-row">
    <button class="ds-btn" type="button" id="ds-open-modal">Ouvrir la modale</button>
    <button class="ds-btn" type="button" id="ds-open-drawer">Ouvrir le tiroir</button>
  </div>
  ${dsModalHtml({ id: "ds-demo-modal", title: "Exemple de modale", body: "<p>La touche Échap ferme. Le focus revient au bouton d'ouverture.</p>", actions: [{ label: "Fermer", variant: "primary" }] })}
  ${dsDrawerHtml({ id: "ds-demo-drawer", title: "Exemple de tiroir", body: "<p>Détail progressif : l'information secondaire attend ici.</p>", actions: [{ label: "Fermer", variant: "primary" }] })}`;

  const toasts = `<div class="ds-demo-row">
    <button class="ds-btn" type="button" id="ds-toast-success">Succès</button>
    <button class="ds-btn" type="button" id="ds-toast-warning">Avertissement</button>
    <button class="ds-btn" type="button" id="ds-toast-danger">Erreur</button>
  </div>`;

  const tooltip = `<p><button class="ds-btn ds-btn--ghost" type="button" data-ds-tip="Explication affichée au survol et au clavier.">Survolez ou tabulez ici</button></p>`;

  return `${dsPageHeader("Design System", "Primitives visuelles de StudiOS : un langage calme, aéré et accessible. Page interne de validation, absente de la navigation.", [{ label: "Interne", variant: "ghost" }])}
  <div class="ds-demo">
    ${demoSection("Boutons", "Primaire = bleu, une seule action principale par surface. Clavier : Tab puis Entrée ou Espace.", buttons)}
    ${demoSection("Badges et statuts", "La couleur ne suffit jamais : chaque état porte son libellé.", badges)}
    ${demoSection("Champs", "Label visible, aide et erreur associées au champ.", fields)}
    ${demoSection("Onglets", "Clavier : flèches gauche/droite pour changer d'onglet.", tabs)}
    ${demoSection("Tableaux", "Colonnes utiles uniquement ; défilement horizontal sous 640 px.", table)}
    ${demoSection("Listes", "Une information par ligne ; le détail attend un clic.", list)}
    ${demoSection("États", "Vide = explication + action. Chargement = squelette silencieux.", states)}
    ${demoSection("Indicateurs", "Un chiffre fort, une progression expliquée, des identités lisibles.", indicators)}
    ${demoSection("Modale et tiroir", "Échap ferme. Le focus revient au déclencheur.", dialogs)}
    ${demoSection("Notifications", "Annoncées aux lecteurs d'écran, refermables, jamais seules pour une info critique.", toasts)}
    ${demoSection("Infobulle", "Accessible au clavier autant qu'à la souris.", tooltip)}
  </div>`;
}

export function renderDesignSystem(view: HTMLElement): void {
  view.innerHTML = designSystemHtml();
  initDsTabs(view, "ds-demo");
  view.querySelector("#ds-open-modal")?.addEventListener("click", (event) => {
    openDsDialog(view, "ds-demo-modal", event.currentTarget as HTMLElement);
  });
  view.querySelector("#ds-open-drawer")?.addEventListener("click", (event) => {
    openDsDialog(view, "ds-demo-drawer", event.currentTarget as HTMLElement);
  });
  view.querySelector("#ds-toast-success")?.addEventListener("click", () => {
    dsNotify("La tâche a été créée.", "success");
  });
  view.querySelector("#ds-toast-warning")?.addEventListener("click", () => {
    dsNotify("La décision attend encore une réponse.", "warning");
  });
  view.querySelector("#ds-toast-danger")?.addEventListener("click", () => {
    dsNotify("Le transfert a été interrompu.", "danger");
  });
}
