/**
 * Vocabulaire grand public (UX V2 · P02-language, cible C2).
 *
 * Source unique des libellés de repli : une identité affichée est un nom humain ;
 * à défaut, un libellé générique — jamais un UUID ni un préfixe d'UUID.
 * L'identifiant complet reste disponible dans « Informations techniques » et
 * dans les champs de copie explicites.
 */

export const FALLBACK_LABEL = {
  agent: "Agent sans nom",
  machine: "Poste sans nom",
  project: "Projet sans nom",
  task: "Tâche sans titre",
  user: "Un membre de l'équipe",
} as const;

/** Verbes explicites pour les liens de navigation vers un objet. */
export const ACTION_LABEL = {
  openTask: "Ouvrir la tâche",
  openProject: "Ouvrir le projet",
  openAgent: "Ouvrir l'agent",
} as const;

/** Libellés lisibles des types d'éléments « À valider » (formes courtes, pour l'Accueil). */
export const REVIEW_KIND_SHORT_LABEL = {
  ai_work_review: "Travail IA",
  decision_proposal: "Décision",
  resource_conflict: "Conflit",
  build_failure: "Échec de build",
  pr_ready: "Demande de fusion",
  roadmap_proposal: "Roadmap",
} as const;
