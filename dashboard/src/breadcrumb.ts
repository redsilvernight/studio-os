/** Fil d'Ariane (R2-adresses), chargé à la demande : hors du budget initial. */
import type { LibraryKindSlug } from "./libraryFormat";
import type { Route } from "./router";
import { esc } from "./ui";

const PROJECT_CRUMB: Record<string, string> = {
  mission: "Exécutions",
  roadmap: "Plan",
  tasks: "Tâches",
  claims: "Fichiers occupés",
  activity: "Activité",
  history: "Historique",
  decisions: "Décisions",
  members: "Membres",
  "ai-integration": "Intégration IA",
};

type Crumb = [label: string, href?: string];

const LIBRARY_CRUMB: Record<LibraryKindSlug, string> = {
  rules: "Règles",
  skills: "Compétences",
  "agent-definitions": "Définitions d'agents",
  workflows: "Flux de travail",
  "model-profiles": "Profils de modèles",
  hooks: "Hooks",
};

/** Étapes d'une sous-page, la dernière sans lien ; aucune sur les pages principales. */
function crumbs(route: Route): Crumb[] {
  const settings: Crumb = ["Réglages", "#/reglages"];
  const engines: Crumb = ["Moteurs IA", "#/reglages/moteurs"];
  const notes: Crumb = ["Notes", "#/connaissances/notes"];
  const library: Crumb = ["Savoir-faire", "#/connaissances/savoir-faire"];
  switch (route.name) {
    case "project": {
      const home: Crumb = ["Projets", "#/projets"];
      const base = `#/projets/${route.id}`;
      const tab = PROJECT_CRUMB[route.tab];
      if (tab === undefined) return [home, ["Projet"]];
      return [home, ["Projet", base], [tab]];
    }
    case "task": return [["Tâches", "#/taches"], ["Tâche"]];
    case "agent": return [["Équipe IA", "#/equipe-ia"], ["Agent"]];
    case "vaultDetail": return [notes, ["Note"]];
    case "vaultAtlas": return [notes, ["Carte"]];
    case "library": return route.kind === null ? [] : [library, [LIBRARY_CRUMB[route.kind]]];
    case "libraryDetail":
      return [library, [LIBRARY_CRUMB[route.kind], `#/connaissances/savoir-faire/${route.kind}`], ["Fiche"]];
    case "adminMeasures": return [settings, ["Mesures"]];
    case "accounts": return [settings, ["Équipe et accès"]];
    case "machines": return [settings, ["Appareils"]];
    case "workspaces": return [settings, ["Dossiers"]];
    case "configRuntimes": return [settings, ["Moteurs IA"]];
    case "configRuntime": return [settings, engines, ["Moteur"]];
    case "configBindings": return [settings, engines, ["Affectations"]];
    case "configIntegrations": return [settings, ["Connexions IA"]];
    case "configApplication": return [settings, ["Application"]];
    case "configProject": return [settings, ["Réglages avancés du projet"]];
    case "inspector": return [settings, ["Inspecteur"]];
    case "designSystem": return [settings, ["Design system"]];
    default: return [];
  }
}

export function breadcrumbHtml(route: Route): string {
  const trail = crumbs(route);
  if (trail.length === 0) return "";
  const items = trail
    .map(([label, href]) =>
      href === undefined ? `<li aria-current="page">${esc(label)}</li>` : `<li><a href="${esc(href)}">${esc(label)}</a></li>`,
    )
    .join("");
  return `<nav class="app-breadcrumb" aria-label="Fil d'Ariane"><ol>${items}</ol></nav>`;
}
