/**
 * UI-1 — page interne de démonstration du Design System (DEC-0078).
 *
 * Route `#/reglages/avance/design-system`, absente de la navigation de production :
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
  dsErrorState,
  dsField,
  dsHeroCard,
  dsMetric,
  dsModalHtml,
  dsNotify,
  dsPageHeader,
  dsProgress,
  dsSectionHeader,
  dsSkeleton,
  dsStateHtml,
  dsStatus,
  dsStatusDot,
  dsTabsHtml,
  dsTechDetails,
  initDsTabs,
  openDsDialog,
} from "../ds/ds";
import {
  dsActorAvatar,
  dsEntitySelect,
  dsIllustratedEmpty,
  dsShowMore,
  dsPersistentNotice,
  dsSegmented,
  initDsEntitySelect,
  initDsPersistentNotice,
} from "../ds/lot1";
import { dsMarkdown } from "../ds/markdown";
import { esc } from "../ui";
import { UI_LABEL } from "../language";

function demoSection(title: string, hint: string, body: string): string {
  return `<section class="ds-demo-section" aria-label="${esc(title)}">${dsSectionHeader(title)}<p>${esc(hint)}</p>${body}</section>`;
}

/** Une carte du catalogue : plusieurs sections, respiration conservée. */
function demoCard(title: string, hint: string, sections: string[]): string {
  return `<div class="ds-card tool-stack"><h2 class="ds-card-title">${esc(title)}</h2><p class="ds-card-hint">${esc(hint)}</p>${sections.join("")}</div>`;
}

/**
 * Les cinq états transverses, rendus par le composant partagé : la même
 * langue partout (wireframes/tools.html, écran « États »), une seule action
 * primaire par état, les identifiants repliés.
 */
function sharedStates(): string {
  const block = (title: string, hint: string, state: Parameters<typeof dsStateHtml>[0], options: Parameters<typeof dsStateHtml>[1]): string =>
    `<section class="ds-card">${dsSectionHeader(title)}<p class="ds-demo-hint">${esc(hint)}</p>${dsStateHtml(state, options)}</section>`;
  return (
    `<div class="state-grid">` +
    block("Introuvable", "404 explicite : l'adresse est rappelée, un seul retour.", "notFound", {
      title: "Adresse inconnue",
      message: "« #/ancien-lien » n'existe pas ou a été déplacée.",
      action: { label: "Retour à l'accueil", href: "#/" },
      details: [{ label: "Route", value: "#/ancien-lien", mono: true }],
    }) +
    block("Vide", "Explication + action, jamais un vide sans issue.", "empty", {
      title: "Aucune inspection lancée",
      message: "Choisissez un champ, puis lancez une résolution.",
      action: { label: "Lancer une inspection", href: "#/reglages/avance/inspecteur" },
    }) +
    block("Chargement", "Squelette silencieux, une annonce unique.", "loading", {
      title: "Chargement",
      message: "Les barres sont décoratives.",
    }) +
    block("Erreur", "Cause affichée, réessai possible, technique repliée.", "error", {
      title: "Résolution impossible",
      message: "Serveur injoignable. Vérifiez la connexion.",
      action: { label: UI_LABEL.retry, href: "#/reglages/avance/design-system" },
      details: [{ label: "Route", value: "POST /resolutions", mono: true }],
    }) +
    `<section class="ds-card state-grid-full">${dsSectionHeader(UI_LABEL.offline)}<p class="ds-demo-hint">Le statut de connexion du shell passe en dégradé ; aucune bannière dupliquée ici.</p>` +
    dsStateHtml("offline", {
      title: UI_LABEL.offline,
      message: "Le statut unique passe en dégradé, la file locale reste active et les actions attendent la reconnexion.",
      action: { label: "Reprendre quand reconnecté", href: "#/reglages/avance/design-system" },
      secondary: { label: "Voir la file locale", href: "#/reglages/avance/design-system" },
    }) +
    `</section>` +
    `</div>`
  );
}

/**
 * Les deux thèmes côte à côte.
 *
 * Chaque panneau force son thème via `data-ds-theme-preview` (tokens.css
 * déclare le même jeu de variables pour `:root` et pour ce sélecteur) :
 * la comparaison ne dépend donc pas du thème actif sur le poste et les
 * deux rendus restent visibles ensemble.
 */
function themePreviews(): string {
  const panel = (mode: "light" | "dark", label: string): string =>
    `<section class="ds-theme-preview" data-ds-theme-preview="${mode}" aria-label="Thème ${label}">
      <header class="ds-theme-preview-head">
        <h3>Thème ${label}</h3>
        <p>${
          mode === "light"
            ? "Fond de page bleuté, surfaces blanches, action bleue."
            : "Fond profond, surfaces ardoise, action éclaircie."
        }</p>
      </header>
      <div class="ds-theme-preview-body">
        <div class="ds-demo-row">
          <button class="ds-btn ds-btn--primary" type="button">Action</button>
          <button class="ds-btn" type="button">Secondaire</button>
          <button class="ds-btn ds-btn--ghost" type="button">Discrète</button>
        </div>
        <div class="ds-demo-row">
          ${dsBadge("Succès", "success")}
          ${dsBadge(UI_LABEL.pending, "warning")}
          ${dsBadge("Erreur", "danger")}
          ${dsBadge("IA", "ai")}
        </div>
        <p class="ds-theme-preview-text">Texte principal et <span class="ds-theme-preview-muted">texte secondaire atténué</span>.</p>
        ${dsField(
          `ds-preview-nom-${mode}`,
          "Champ",
          `<input class="ds-input" id="FIELD" type="text" value=UI_LABEL.studio />`,
          "Aide sous le champ.",
          "",
        )}
        <div class="ds-notice ds-notice--info"><strong>Information.</strong>Notice sur fond pastel.</div>
        ${dsProgress(2, 5, "2 sur 5 (40 %)")}
      </div>
    </section>`;

  return `<div class="ds-theme-previews">${panel("light", "clair")}${panel("dark", "sombre")}</div>`;
}


/** Lot 1 (R1-composants) : composants structurants, chacun dans ses états. */
function lot1Demo(): string {
  const studios = [
    { id: "atelier", label: "Atelier Lumière", meta: "Propriétaire" },
    { id: "nord", label: "Studio Nord", meta: "Membre" },
    { id: "lecture", label: "Collectif Arc", meta: UI_LABEL.readOnly },
  ];
  const entity = `<div class="ds-demo-row">${dsEntitySelect("ds-demo-studio", UI_LABEL.studio, studios, "atelier")}</div>`;
  const avatars = `<div class="ds-demo-row">${dsActorAvatar("Amina Benali")}${dsActorAvatar("Relecteur", "agent")}</div>`;
  const notices = `<div class="ds-demo-column">
    ${dsPersistentNotice("ds-n-info", "info", "Nouveau plan disponible", "Comparez les offres quand vous voulez.")}
    ${dsPersistentNotice("ds-n-warning", "warning", "Limite bientôt atteinte", "9 projets sur 10 utilisés.", { action: { label: "Voir l'abonnement", href: "#/reglages/avance/design-system" }, dismissible: true })}
    ${dsPersistentNotice("ds-n-danger", "danger", "Studio suspendu", "Les modifications sont bloquées.")}
  </div>`;
  const pager = `<div class="ds-demo-column">${dsShowMore(50, 213, "tâches", "#/reglages/avance/design-system")}${dsShowMore(213, 213, "tâches")}</div>`;
  const seg = `<div class="ds-demo-row">${dsSegmented("ds-demo-mode", "Mode d'affichage", [{ value: "simple", label: "Simple" }, { value: "expert", label: "Expert" }], "simple")}</div>`;
  const empty = dsIllustratedEmpty("inbox", UI_LABEL.nothingToReview, "Les propositions des agents apparaîtront ici.", { label: "Voir les projets", href: "#/reglages/avance/design-system" });
  const form = `<form class="ds-form" novalidate>
    <div class="ds-form-field"><label for="ds-f-nom">Nom du studio</label><input class="ds-input" id="ds-f-nom" type="text" aria-describedby="ds-f-nom-hint"><span class="ds-form-hint" id="ds-f-nom-hint">Visible par les membres.</span></div>
    <div class="ds-form-field"><label for="ds-f-mail">Adresse</label><input class="ds-input" id="ds-f-mail" type="email" aria-invalid="true" aria-describedby="ds-f-mail-err"><span class="ds-form-error" id="ds-f-mail-err">Adresse invalide.</span></div>
    <div class="ds-form-actions"><button class="ds-btn ds-btn--primary" type="button">Créer</button><button class="ds-btn" type="button">Annuler</button></div>
  </form>`;
  const prose = dsMarkdown(["### Notes", "", "Texte **gras**, *italique*, `code` et [un lien](https://example.com).", "", "- Premier", "- Second", "", "> Citation"].join("\n"));
  return demoCard("Composants du lot 1", "Sélecteur, avatars, notifications persistantes, « Afficher plus », bascule, état vide, formulaire, texte mis en forme.", [
    `<div data-ds-lot1="entity">${demoSection("Sélecteur d'entité", "Flèches, Entrée, Échap ; le rôle est lu avec le nom.", entity)}</div>`,
    `<div data-ds-lot1="avatar">${demoSection("Avatars", "Humain : initiales. Agent : icône, nom annoncé « Agent … ».", avatars)}</div>`,
    `<div data-ds-lot1="notice">${demoSection("Notifications persistantes", "Restent tant que la cause demeure ; l'icône accompagne le texte.", notices)}</div>`,
    `<div data-ds-lot1="more">${demoSection("Afficher plus", "Liste partielle, liste complète.", pager)}</div>`,
    `<div data-ds-lot1="segmented">${demoSection("Bascule segmentée", "Flèches pour changer de mode.", seg)}</div>`,
    `<div data-ds-lot1="empty">${demoSection("État vide illustré", "Icône, explication, une action.", empty)}</div>`,
    `<div data-ds-lot1="form">${demoSection("Formulaire", "Étiquette, aide, erreur associées au champ.", form)}</div>`,
    `<div data-ds-lot1="markdown">${demoSection("Texte mis en forme", "Markdown sans HTML brut.", prose)}</div>`,
  ]);
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
    <button class="ds-icon-btn" type="button" aria-label=UI_LABEL.close>×</button>
  </div>`;

  const badges = `<div class="ds-demo-row">
    ${dsBadge("Neutre")}
    ${dsBadge("Succès", "success")}
    ${dsBadge(UI_LABEL.pending, "warning")}
    ${dsBadge("Erreur", "danger")}
    ${dsBadge("IA · Auxiliaire", "ai")}
    ${dsBadge("Information", "info")}
  </div>
  <div class="ds-demo-row">
    ${dsStatus("success", "Connecté")}
    ${dsStatus("warning", UI_LABEL.pending)}
    ${dsStatus("danger", "Bloqué")}
    ${dsStatus("ai", "Agent actif")}
    ${dsStatus("idle", "Inconnu")}
  </div>`;

  const fields = `<div class="ds-demo-grid">
    ${dsField("ds-nom", "Nom du projet", `<input class="ds-input" id="FIELD" type="text" value=UI_LABEL.studio />`, "Nom affiché dans les listes.", "")}
    ${dsField("ds-recherche", "Rechercher", `<div class="ds-search"><span class="ds-search-icon" aria-hidden="true">⌕</span><input class="ds-input" id="FIELD" type="search" placeholder="Nom, mot-clé…" /></div>`)}
    ${dsField("ds-statut", UI_LABEL.status, `<select class="ds-select" id="FIELD"><option>À faire</option><option>En cours</option><option>Bloqué</option></select>`)}
    ${dsField("ds-erreur", "Avec erreur", `<input class="ds-input" id="FIELD" type="text" value="!!" />`, "", "Ce champ est requis.")}
  </div>`;

  const tabs = dsTabsHtml("ds-demo", [
    { id: "liste", label: "Liste", panel: "<p>Premier panneau : contenu de la liste.</p>" },
    { id: "board", label: "Tableau", panel: "<p>Deuxième panneau : contenu du tableau.</p>" },
    { id: "calendrier", label: "Calendrier", panel: "<p>Troisième panneau : contenu du calendrier.</p>" },
  ], undefined, "Démonstration des onglets");

  const table = `<div class="ds-table-wrap"><table class="ds-table">
    <caption>Exemple : trois projets, colonnes utiles uniquement.</caption>
    <thead><tr><th scope="col">Nom</th><th scope="col">Statut</th><th scope="col">Mis à jour</th></tr></thead>
    <tbody>
      <tr><td>Phare</td><td>${dsStatus("success", UI_LABEL.active)}</td><td>aujourd'hui</td></tr>
      <tr><td>Digue</td><td>${dsStatus("warning", "En pause")}</td><td>hier</td></tr>
    </tbody>
  </table></div>`;

  const list = `<ul class="ds-list">
    <li class="ds-list-item"><div class="grow"><div class="ds-list-title">Corriger le doublon de tâche</div><div class="ds-list-sub">Projet Phare · priorité haute</div></div>${dsBadge("Bloqué", "danger")}</li>
    <li class="ds-list-item"><div class="grow"><div class="ds-list-title">Relire la proposition d'agent</div><div class="ds-list-sub">En attente depuis hier</div></div>${dsBadge("À examiner", "warning")}</li>
  </ul>`;

  const states = `${dsEmptyState("Aucune tâche", "Créez votre première tâche pour démarrer.", { label: "Créer une tâche", href: "#/reglages/avance/design-system" })}<div>${dsSkeleton(3)}</div>`;

  const indicators = `<div class="ds-demo-grid">
    <div class="ds-card">${dsMetric("Tâches en cours", 4)}</div>
    <div class="ds-card">${dsProgress(2, 5, "2 Mo sur 5 Mo transférés (40 %)")}</div>
    <div class="ds-card"><div class="ds-demo-row">${dsAvatar("Amina Benali")}${dsAgentBadge("Auxiliaire de relecture")}</div></div>
  </div>`;

  const dialogs = `<div class="ds-demo-row">
    <button class="ds-btn" type="button" id="ds-open-modal">Ouvrir la modale</button>
    <button class="ds-btn" type="button" id="ds-open-drawer">Ouvrir le tiroir</button>
  </div>
  ${dsModalHtml({ id: "ds-demo-modal", title: "Exemple de modale", body: "<p>La touche Échap ferme. Le focus revient au bouton d'ouverture.</p>", actions: [{ label: UI_LABEL.close, variant: "primary" }] })}
  ${dsDrawerHtml({ id: "ds-demo-drawer", title: "Exemple de tiroir", body: "<p>Détail progressif : l'information secondaire attend ici.</p>", actions: [{ label: UI_LABEL.close, variant: "primary" }] })}`;

  const toasts = `<div class="ds-demo-row">
    <button class="ds-btn" type="button" id="ds-toast-success">Succès</button>
    <button class="ds-btn" type="button" id="ds-toast-warning">Avertissement</button>
    <button class="ds-btn" type="button" id="ds-toast-danger">Erreur</button>
  </div>`;

  const tooltip = `<p><button class="ds-btn ds-btn--ghost" type="button" data-ds-tip="Explication affichée au survol et au clavier.">Survolez ou tabulez ici</button></p>`;

  const progressive =
    dsHeroCard({
      eyebrow: "Agents / Fiche",
      title: "Travaille sur « Valider des wireframes »",
      body: "Studi'OS · mis à jour il y a 12 min. La relecture détaillée se fait dans À valider.",
      status: dsStatusDot("info", "Session de travail ouverte"),
      primary: { label: "Ouvrir le travail", href: "#/reglages/avance/design-system" },
      secondary: [{ label: "Voir la tâche liée", href: "#/reglages/avance/design-system" }],
    }) +
    `<div class="ds-demo-row">${dsStatusDot("success", "Opérationnel")}${dsStatusDot("warning", UI_LABEL.pending, true)}<span class="ds-list-sub">La seconde pastille est compacte : libellé réservé aux lecteurs d'écran.</span></div>` +
    dsTechDetails([
      { label: UI_LABEL.identifier, value: "aaaaaaaa-0000-4111-8111-000000000001", mono: true },
      { label: UI_LABEL.revision, value: "v3", mono: true },
      { label: UI_LABEL.createdOn, value: "il y a 12 min" },
    ]) +
    dsErrorState("Chargement impossible", "Les données n'ont pas pu être rechargées.", {
      label: UI_LABEL.retry,
      href: "#/reglages/avance/design-system",
    });

  const hero = `<section class="ds-hero">
    <p class="ds-hero-eyebrow">Une seule action principale par surface</p>
    <h2>Tester une primitive sans quitter la page</h2>
    <p class="ds-hero-body">Clavier : Tab puis Entrée. La couleur n'est jamais seule : chaque statut porte son libellé.</p>
    <div class="ds-hero-actions"><button class="ds-btn ds-btn--primary" type="button" data-ds-jump="ds-demo-etats">Voir les états</button></div>
  </section>`;

  const notices = `<div class="ds-demo-column">
    <div class="ds-notice ds-notice--success"><strong>Succès.</strong>La tâche a été créée.</div>
    <div class="ds-notice ds-notice--warning"><strong>En attente.</strong>La décision n'a pas encore de réponse.</div>
    <div class="ds-notice ds-notice--danger"><strong>Erreur.</strong>Le transfert a été interrompu, réessayez.</div>
    <div class="ds-notice ds-notice--info"><strong>Information.</strong>La présence affichée est dérivée, jamais canonique.</div>
    <div>${dsProgress(2, 5, "2 Mo sur 5 Mo transférés (40 %)")}</div>
  </div>`;

  return `<p class="ds-eyebrow">Interne · absente de la navigation</p>${dsPageHeader("Design System", "Primitives calmes et accessibles, validées avant usage. Page interne de validation, absente de la navigation.", [{ label: "Interne", variant: "ghost" }])}
  <div class="tool-columns">
  <div class="tool-main">
    ${hero}
    ${demoCard("Actions et statuts", "Une action primaire par surface, la couleur jamais seule.", [
      demoSection("Boutons", "Primaire = bleu, une seule action principale par surface. Clavier : Tab puis Entrée ou Espace.", buttons),
      demoSection("Badges et statuts", "La couleur ne suffit jamais : chaque état porte son libellé.", badges),
    ])}
    ${demoCard("Saisie", "Label visible, aide et erreur associées au champ.", [
      demoSection("Champs", "Label visible, aide et erreur associées au champ.", fields),
      demoSection("Onglets", "Clavier : flèches gauche/droite pour changer d'onglet.", tabs),
    ])}
    ${demoCard("Données", "Colonnes utiles uniquement, une information par ligne.", [
      demoSection("Tableaux", "Colonnes utiles uniquement ; défilement horizontal sous 640 px.", table),
      demoSection("Listes", "Une information par ligne ; le détail attend un clic.", list),
    ])}
    ${demoCard("États et divulgation", "Cinq états transverses, un seul composant partagé, le technique replié.", [
      demoSection("États", "Vide = explication + action. Chargement = squelette silencieux.", states),
      `<section class="ds-demo-section" id="ds-demo-etats" aria-label="Cinq états transverses">${dsSectionHeader("Cinq états, une seule langue")}<p>Introuvable, vide, chargement, erreur et hors ligne : même gabarit, une seule action primaire, détails repliés.</p>${sharedStates()}</section>`,
      demoSection("Divulgation progressive", "L'essentiel d'abord, le technique replié sur place : héros à action unique, pastille de statut, détails repliés, erreur cohérente avec le vide et le chargement.", progressive),
      demoSection("Indicateurs", "Un chiffre fort, une progression expliquée, des identités lisibles.", indicators),
    ])}
    ${lot1Demo()}
    ${demoCard("Thèmes", "Le même jeu de tokens, deux rendus : clair et sombre, côte à côte.", [
      demoSection("Les deux thèmes", "Les panneaux ci-dessous forcent leur thème : la comparaison ne dépend pas du thème actif sur le poste. Le sélecteur de la barre latérale choisit « Système », « Clair » ou « Sombre » pour toute la page.", themePreviews()),
    ])}
  </div>
  <aside class="ds-card tool-context" aria-label="Notices, progression et dialogues">
    <div><h2>Notices et progression</h2>${notices}</div>
    <div>${demoSection("Modale et tiroir", "Échap ferme. Le focus revient au déclencheur.", dialogs)}</div>
    <div>${demoSection("Notifications", "Annoncées aux lecteurs d'écran, refermables, jamais seules pour une info critique.", toasts)}</div>
    <div>${demoSection("Infobulle", "Accessible au clavier autant qu'à la souris.", tooltip)}</div>
    <div><h2>Identités lisibles</h2><p>Initiales et nom humain par défaut ; un identifiant brut n'apparaît que dans un bloc technique replié.</p>${dsTechDetails([
      { label: "Jetons", value: "couleurs sémantiques, remplacées par thème", mono: true },
      { label: "Variantes", value: "ds-tone, ds-state — jamais de style inline", mono: true },
    ], "Détails techniques")}</div>
  </aside>
  </div>`;
}

export function renderDesignSystem(view: HTMLElement): void {
  view.innerHTML = designSystemHtml();
  initDsTabs(view, "ds-demo");
  initDsEntitySelect(view, "ds-demo-studio");
  initDsPersistentNotice(view, "ds-n-warning");
  // Le héros propose une seule entrée : descendre aux états, sans changer de route.
  view.querySelector("[data-ds-jump]")?.addEventListener("click", (event) => {
    const target = (event.currentTarget as HTMLElement).dataset.dsJump ?? "";
    view.querySelector(`#${CSS.escape(target)}`)?.scrollIntoView();
  });
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
