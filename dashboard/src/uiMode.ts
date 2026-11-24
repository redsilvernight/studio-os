/**
 * Mode d'affichage (R2-modes) : « simple » (défaut, tout nouveau compte) ou
 * « expert ». Expert ajoute (identifiants copiables, termes techniques) sans
 * jamais retirer ni déplacer un élément du mode Simple : mêmes routes, mêmes
 * données, même navigation. Le choix se mémorise sur le poste, sans
 * identifiant ni secret ; une valeur illisible vaut « simple ».
 */
export type UiMode = "simple" | "expert";

export const UI_MODE_STORAGE_KEY = "studio-os.ui-mode";

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function storage(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function loadUiMode(store: StorageLike | null = storage()): UiMode {
  try {
    return store?.getItem(UI_MODE_STORAGE_KEY) === "expert" ? "expert" : "simple";
  } catch {
    return "simple";
  }
}

/** Mémorise le mode ; un stockage indisponible ne bloque jamais l'interface. */
export function saveUiMode(mode: UiMode, store: StorageLike | null = storage()): void {
  try {
    store?.setItem(UI_MODE_STORAGE_KEY, mode);
  } catch {
    // Quota ou navigation privée : le choix n'est simplement pas mémorisé.
  }
}

export function toggledUiMode(mode: UiMode): UiMode {
  return mode === "expert" ? "simple" : "expert";
}

/** Expose le mode au CSS (`[data-ui-mode="expert"]`) et aux tests. */
export function applyUiMode(mode: UiMode, root: HTMLElement = document.documentElement): void {
  root.dataset["uiMode"] = mode;
}

/** Bascule, mémorise, applique et notifie (`ui-mode-change`) ; renvoie le nouveau mode. */
export function switchUiMode(mode: UiMode): UiMode {
  saveUiMode(mode);
  applyUiMode(mode);
  document.dispatchEvent(new CustomEvent("ui-mode-change", { detail: mode }));
  return mode;
}
