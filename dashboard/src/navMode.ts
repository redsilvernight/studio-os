/**
 * Mode de navigation (UX V2 P06-regression-rollout).
 *
 * Activation progressive et retour arrière sans perte : « simple » (défaut,
 * cinq destinations quotidiennes, le reste replié) ou « complet » (toutes les
 * destinations déployées en permanence, comme avant la V2). Le mode ne change
 * que la présentation de la barre latérale : mêmes routes, mêmes liens
 * profonds, mêmes données ; il se mémorise sur le poste, sans identifiant
 * ni secret, et une valeur illisible vaut « simple ».
 */
export type NavMode = "simple" | "complete";

export const NAV_MODE_STORAGE_KEY = "studio-os.nav-mode";

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function storage(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function loadNavMode(store: StorageLike | null = storage()): NavMode {
  try {
    return store?.getItem(NAV_MODE_STORAGE_KEY) === "complete" ? "complete" : "simple";
  } catch {
    return "simple";
  }
}

/** Mémorise le mode ; un stockage indisponible ne bloque jamais la navigation. */
export function saveNavMode(mode: NavMode, store: StorageLike | null = storage()): void {
  try {
    store?.setItem(NAV_MODE_STORAGE_KEY, mode);
  } catch {
    // Quota ou navigation privée : le choix n'est simplement pas mémorisé.
  }
}

export function toggledNavMode(mode: NavMode): NavMode {
  return mode === "complete" ? "simple" : "complete";
}
