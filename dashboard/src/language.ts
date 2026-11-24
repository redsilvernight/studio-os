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
  build_failure: "Échec de compilation",
  pr_ready: "Demande de fusion",
  roadmap_proposal: "Plan",
} as const;

/** Formes longues (page « À valider »). Même vocabulaire que les formes courtes, seule la précision change. */
export const REVIEW_KIND_LABEL = {
  ...REVIEW_KIND_SHORT_LABEL,
  decision_proposal: "Proposition de décision",
  resource_conflict: "Fichier occupé en conflit",
  roadmap_proposal: "Proposition de plan",
} as const;

/** Libellés d'interface partagés par plusieurs vues (un seul endroit à relire ou traduire). */
export const UI_LABEL = {
  configuration: "Réglages",
  refresh: "Actualiser",
  machines: "Postes",
  task: "Tâche",
  active: "Actif",
  title: "Titre",
  vault: "Notes",
  agent: "Agent",
  toReview: "À valider",
  identifier: "Identifiant",
  pending: "En attente",
  studio: "Studio",
  close: "Fermer",
  transfers: "Transferts",
  done: "Terminée",
  signInRequired: "Connexion requise",
  inProgress: "En cours",
  library: "Savoir-faire",
  administration: "Réglages",
  createdOn: "Créé le",
  nothingToReview: "Rien à valider",
  titleRequired: "Le titre est obligatoire.",
  notProvided: "Non renseigné",
  runs: "Exécutions",
  archived: "Archivé",
  readOnly: "Lecture seule",
  revision: "Révision",
  content: "Contenu",
  status: "Statut",
  roadmap: "Plan",
  retry: "Réessayer",
  offline: "Hors ligne",
  draft: "Brouillon",
  cancel: "Annuler",
  descriptionOptional: "Description (facultative)",
  signIn: "Connectez-vous",
  project: "Projet",
} as const;
