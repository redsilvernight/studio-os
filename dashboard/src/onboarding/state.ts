/**
 * P11 — état local du premier lancement (first-run).
 *
 * Stocke le minimum pour reprendre l'assistant : schéma, statut, étape et les
 * identifiants déjà choisis. Ne duplique jamais les domaines sources de
 * vérité (config serveur, config workspace, mémoire, harnais) et ne contient
 * aucun secret, aucun jeton, aucun chemin local complet.
 */

export const ONBOARDING_STORAGE_KEY = "studio-os.onboarding.v1";
export const ONBOARDING_SCHEMA_VERSION = 1;

export type OnboardingStatus = "not_started" | "in_progress" | "completed" | "skipped";

export type OnboardingStepId =
  | "bienvenue"
  | "connexion"
  | "verification"
  | "projet"
  | "dossier"
  | "memoire"
  | "environnement"
  | "assistant"
  | "final"
  | "termine";

export interface OnboardingState {
  schema: number;
  status: OnboardingStatus;
  /** Dernière étape atteinte ; revalidée contre l'état réel à la reprise. */
  current: OnboardingStepId;
  /** Identifiants choisis pendant le parcours (jamais saisis à la main). */
  projectId?: string;
  projectName?: string;
  workspaceId?: string;
  /** Nom d'affichage du dossier (nom seul, jamais le chemin complet). */
  folderName?: string;
  completedAt?: string;
}

export const INITIAL_ONBOARDING_STATE: OnboardingState = {
  schema: ONBOARDING_SCHEMA_VERSION,
  status: "not_started",
  current: "bienvenue",
};

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function storage(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

function isStepId(value: unknown): value is OnboardingStepId {
  return (
    value === "bienvenue" ||
    value === "connexion" ||
    value === "verification" ||
    value === "projet" ||
    value === "dossier" ||
    value === "memoire" ||
    value === "environnement" ||
    value === "assistant" ||
    value === "final" ||
    value === "termine"
  );
}

function isStatus(value: unknown): value is OnboardingStatus {
  return value === "not_started" || value === "in_progress" || value === "completed" || value === "skipped";
}

/** Lit l'état ; une valeur illisible ou étrangère vaut "jamais démarré". */
export function loadOnboardingState(store: StorageLike | null = storage()): OnboardingState {
  try {
    const raw = store?.getItem(ONBOARDING_STORAGE_KEY);
    if (!raw) return { ...INITIAL_ONBOARDING_STATE };
    const parsed = JSON.parse(raw) as Partial<OnboardingState>;
    if (parsed.schema !== ONBOARDING_SCHEMA_VERSION) return { ...INITIAL_ONBOARDING_STATE };
    if (!isStatus(parsed.status)) return { ...INITIAL_ONBOARDING_STATE };
    return {
      schema: ONBOARDING_SCHEMA_VERSION,
      status: parsed.status,
      current: isStepId(parsed.current) ? parsed.current : "bienvenue",
      ...(typeof parsed.projectId === "string" ? { projectId: parsed.projectId } : {}),
      ...(typeof parsed.projectName === "string" ? { projectName: parsed.projectName } : {}),
      ...(typeof parsed.workspaceId === "string" ? { workspaceId: parsed.workspaceId } : {}),
      ...(typeof parsed.folderName === "string" ? { folderName: parsed.folderName } : {}),
      ...(typeof parsed.completedAt === "string" ? { completedAt: parsed.completedAt } : {}),
    };
  } catch {
    return { ...INITIAL_ONBOARDING_STATE };
  }
}

/** Persiste l'état ; un stockage indisponible n'interrompt pas le parcours. */
export function saveOnboardingState(state: OnboardingState, store: StorageLike | null = storage()): void {
  try {
    store?.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Le parcours reste utilisable en mémoire pour cette session.
  }
}

export function clearOnboardingState(store: StorageLike | null = storage()): void {
  try {
    store?.removeItem(ONBOARDING_STORAGE_KEY);
  } catch {
    // Rien à réparer : l'état est local et régénérable.
  }
}
