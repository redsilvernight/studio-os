/**
 * Thème clair / sombre / système (DS tokens, DEC-0078 §2, extension
 * « thème sombre » de la tâche cea09af9).
 *
 * Le choix ne change que la présentation : il pose `data-theme` sur
 * `<html>` (« light » ou « dark ») ou le retire pour suivre la préférence
 * du système (les media queries de `tokens.css` prennent alors le relais).
 * Il se mémorise sur le poste, sans identifiant ni secret ; une valeur
 * illisible vaut « système ». Aucun style inline (contrainte CSP).
 *
 * « Système » ne s'écrit pas : la clé localStorage est SUPPRIMÉE, si bien
 * que l'absence de clé est l'état « suit le système » (une clé absente
 * survit aux mises à jour et se confond avec une première visite). Le
 * même contrat est rejoué par `public/theme-boot.js`, exécuté avant le
 * premier rendu pour éviter le flash de thème (CSP `script-src 'self'`).
 */
export type ThemeMode = "system" | "light" | "dark";

export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "studio-os.theme";

export const THEME_MODES: readonly ThemeMode[] = ["system", "light", "dark"];

export const THEME_LABELS: Record<ThemeMode, string> = {
  system: "Système",
  light: "Clair",
  dark: "Sombre",
};

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function storage(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function isThemeMode(value: string | null): value is ThemeMode {
  return value === "system" || value === "light" || value === "dark";
}

export function loadThemeMode(store: StorageLike | null = storage()): ThemeMode {
  try {
    const stored = store?.getItem(THEME_STORAGE_KEY) ?? null;
    return isThemeMode(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

/**
 * Mémorise le choix ; un stockage indisponible ne bloque jamais l'interface.
 *
 * « Système » supprime la clé au lieu d'écrire « system » : l'absence de
 * clé EST le mode système, lisible par le script de pré-rendu sans
 * partager de code avec ce module.
 */
export function saveThemeMode(mode: ThemeMode, store: StorageLike | null = storage()): void {
  try {
    if (mode === "system") {
      store?.removeItem(THEME_STORAGE_KEY);
      return;
    }
    store?.setItem(THEME_STORAGE_KEY, mode);
  } catch {
    // Quota ou navigation privée : le choix n'est simplement pas mémorisé.
  }
}

export function prefersDarkTheme(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Thème effectivement peint pour un mode donné. */
export function resolveTheme(mode: ThemeMode, systemDark: boolean): ResolvedTheme {
  if (mode === "light") return "light";
  if (mode === "dark") return "dark";
  return systemDark ? "dark" : "light";
}

/**
 * Applique le mode au document : attribut explicite pour un choix ferme,
 * absence d'attribut pour « système » (aucun écouteur à maintenir).
 * Retourne le thème résolu (utile aux tests et aux libellés).
 */
export function applyThemeMode(
  mode: ThemeMode,
  root: HTMLElement = document.documentElement,
  systemDark: boolean = prefersDarkTheme(),
): ResolvedTheme {
  const resolved = resolveTheme(mode, systemDark);
  if (mode === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", resolved);
  return resolved;
}
