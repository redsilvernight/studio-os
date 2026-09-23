/**
 * P11 — étapes de l'assistant de configuration (vocabulaire utilisateur, sans
 * jargon : ni MCP, ni démon, ni Graphify, ni Vault, ni token dans le parcours
 * principal).
 */
import type { OnboardingStepId } from "./state";

export interface OnboardingStep {
  id: OnboardingStepId;
  /** Titre court pour la progression. */
  title: string;
  /** Question posée à l'utilisateur. */
  heading: string;
  /** Explication en une ou deux phrases. */
  intro: string;
  /** Faux = l'utilisateur peut passer sans bloquer la fin du parcours. */
  required: boolean;
}

export const ONBOARDING_STEPS: readonly OnboardingStep[] = [
  {
    id: "bienvenue",
    title: "Bienvenue",
    heading: "Bienvenue dans Studi'OS",
    intro: "Studi'OS relie vos projets, vos connaissances et vos assistants IA. Cet assistant vous guide en quelques étapes.",
    required: true,
  },
  {
    id: "connexion",
    title: "Connexion",
    heading: "Connecter Studi'OS",
    intro: "Indiquez où joindre votre serveur Studi'OS, puis connectez-vous. Sans serveur, l'application démarre quand même.",
    required: true,
  },
  {
    id: "verification",
    title: "Vérification",
    heading: "Vérification locale",
    intro: "Studi'OS vérifie que l'assistant local répond et que ce poste est reconnu.",
    required: true,
  },
  {
    id: "projet",
    title: "Projet",
    heading: "Choisir un projet",
    intro: "Sélectionnez le projet à relier à ce poste, ou créez-le s'il n'existe pas encore.",
    required: true,
  },
  {
    id: "dossier",
    title: "Dossier",
    heading: "Associer un dossier",
    intro: "Choisissez le dossier de travail sur ce poste. Vos fichiers restent en place : seul un repère local est ajouté.",
    required: true,
  },
  {
    id: "memoire",
    title: "Mémoire",
    heading: "Activer la mémoire du projet",
    intro: "Studi'OS peut utiliser des fichiers Markdown locaux pour conserver et retrouver les connaissances de ce projet.",
    required: false,
  },
  {
    id: "environnement",
    title: "Environnement",
    heading: "Environnement local",
    intro: "Tour d'horizon de ce que Studi'OS détecte sur ce poste. Rien ici ne bloque la suite.",
    required: false,
  },
  {
    id: "assistant",
    title: "Assistant IA",
    heading: "Connecter votre assistant IA",
    intro: "Si un assistant IA est installé (Claude Code, OpenCode), Studi'OS peut le relier à ce projet. Rien n'est modifié sans votre confirmation.",
    required: false,
  },
  {
    id: "final",
    title: "Vérification",
    heading: "Votre projet est prêt",
    intro: "Contrôlez le résumé avant de terminer. Chaque point est revalidé à l'instant, pas recopié d'une étape précédente.",
    required: true,
  },
  {
    id: "termine",
    title: "Terminé",
    heading: "Configuration terminée",
    intro: "Vous pouvez relancer cet assistant à tout moment depuis les paramètres.",
    required: true,
  },
];

export const STEP_ORDER: readonly OnboardingStepId[] = ONBOARDING_STEPS.map((step) => step.id);

export function stepById(id: OnboardingStepId): OnboardingStep {
  const found = ONBOARDING_STEPS.find((step) => step.id === id);
  if (!found) throw new Error(`unknown onboarding step: ${id}`);
  return found;
}

export function stepIndex(id: OnboardingStepId): number {
  return STEP_ORDER.indexOf(id);
}

export function nextStep(id: OnboardingStepId): OnboardingStepId | null {
  const at = stepIndex(id);
  return at < 0 || at + 1 >= STEP_ORDER.length ? null : (STEP_ORDER[at + 1] as OnboardingStepId);
}

export function previousStep(id: OnboardingStepId): OnboardingStepId | null {
  const at = stepIndex(id);
  return at <= 0 ? null : (STEP_ORDER[at - 1] as OnboardingStepId);
}
