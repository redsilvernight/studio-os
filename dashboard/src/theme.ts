/**
 * Thème clair / sombre / système (DS tokens, DEC-0078 §2).
 *
 * Le choix ne change que la présentation : il pose `data-theme` sur
 * `<html>` (« light » ou « dark ») ou le retire pour suivre la préférence
 * du système (les media queries de `tokens.css` prennent alors le relais).
 * Il se mémorise sur le poste, sans identifiant ni secret ; une valeur
 * illisible vaut « système ». Aucun style inline (contrainte CSP).
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

type StorageLike = Pick<Storage, "getItem" | "setItem">;

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

/** Mémorise le choix ; un stockage indisponible ne bloque jamais l'interface. */
export function saveThemeMode(mode: ThemeMode, store: StorageLike | null = storage()): void {
  try {
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
