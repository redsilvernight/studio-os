/**
 * P3 — étapes du premier lancement : le poste seul, sans projet ni dossier.
 * La mémoire, l'environnement (Git, analyse du code) et l'assistant IA se
 * configurent ensuite par dossier depuis « Espaces de travail ».
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
    id: "final",
    title: "Prêt",
    heading: "Votre poste est prêt",
    intro: "Contrôlez le résumé avant de terminer. Vos dossiers se configureront ensuite depuis « Espaces de travail », sans obligation.",
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

function stepIndex(id: OnboardingStepId): number {
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
