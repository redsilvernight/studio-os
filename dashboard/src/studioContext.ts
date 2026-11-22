/**
 * Contexte studio actif (atelier N1).
 *
 * Le studio actif est celui du contexte de session ; à défaut, la sélection
 * de l'écran « Choisissez un studio » (fiche N1) fait foi. Le choix est
 * mémorisé pour la session courante (sessionStorage, comme le contexte de
 * session) : il disparaît à la fermeture du poste. Aucun identifiant
 * sensible n'est stocké — un identifiant illisible vaut « aucun studio
 * sélectionné ».
 */
export const ACTIVE_STUDIO_STORAGE_KEY = "studio-os.active-studio";

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function storage(): StorageLike | null {
  try {
    // sessionStorage d'abord (contexte de session) ; localStorage en repli
    // pour les postes où le premier est refusé (mode privé strict).
    return globalThis.sessionStorage ?? globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function getActiveStudioId(store: StorageLike | null = storage()): string | null {
  try {
    const value = store?.getItem(ACTIVE_STUDIO_STORAGE_KEY) ?? null;
    return value !== null && value !== "" ? value : null;
  } catch {
    return null;
  }
}

export function setActiveStudioId(id: string | null, store: StorageLike | null = storage()): void {
  try {
    if (id === null) store?.removeItem(ACTIVE_STUDIO_STORAGE_KEY);
    else store?.setItem(ACTIVE_STUDIO_STORAGE_KEY, id);
  } catch {
    // Poste sans stockage (mode privé) : la sélection reste en mémoire.
  }
}

/**
 * Studio actif à utiliser pour un écran : celui du contexte de session,
 * sinon le premier de la liste (l'ordre du serveur fait foi).
 */
export function resolveActiveStudioId(
  studios: { id: string }[],
  store: StorageLike | null = storage(),
): string | null {
  const active = getActiveStudioId(store);
  if (active !== null && studios.some((studio) => studio.id === active)) return active;
  return studios[0]?.id ?? null;
}
