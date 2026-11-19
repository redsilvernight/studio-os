// @vitest-environment happy-dom
/**
 * Thème clair / sombre / système : stockage tolérant, résolution et
 * application sur `<html>`, sélecteur présent dans le shell.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  applyThemeMode,
  isThemeMode,
  loadThemeMode,
  prefersDarkTheme,
  resolveTheme,
  saveThemeMode,
  THEME_STORAGE_KEY,
} from "./theme";
import { shellHtml } from "./shell";

function memoryStore(initial?: string): Pick<Storage, "getItem" | "setItem"> & { value: string | null } {
  const store = {
    value: initial ?? null,
    getItem: (): string | null => store.value,
    setItem: (_key: string, value: string): void => {
      store.value = value;
    },
  };
  return store;
}

beforeEach(() => {
  document.documentElement.removeAttribute("data-theme");
  globalThis.localStorage?.clear();
});

describe("theme (clair / sombre / système)", () => {
  it("vaut « système » par défaut et ignore une valeur illisible", () => {
    expect(loadThemeMode(memoryStore())).toBe("system");
    expect(loadThemeMode(memoryStore("n'importe quoi"))).toBe("system");
    expect(loadThemeMode(null)).toBe("system");
    expect(isThemeMode("dark")).toBe(true);
    expect(isThemeMode("sepia")).toBe(false);
  });

  it("mémorise le choix sous une clé stable, sans casser si le stockage refuse", () => {
    const store = memoryStore();
    saveThemeMode("dark", store);
    expect(store.value).toBe("dark");
    expect(loadThemeMode(store)).toBe("dark");
    expect(THEME_STORAGE_KEY).toBe("studio-os.theme");
    const broken = {
      getItem: (): string => {
        throw new Error("denied");
      },
      setItem: (): void => {
        throw new Error("denied");
      },
    };
    expect(loadThemeMode(broken)).toBe("system");
    expect(() => saveThemeMode("light", broken)).not.toThrow();
  });

  it("résout « système » depuis la préférence, les choix fermes priment", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
    expect(typeof prefersDarkTheme()).toBe("boolean");
  });

  it("pose data-theme pour un choix ferme et le retire pour « système »", () => {
    const root = document.documentElement;
    expect(applyThemeMode("dark", root, false)).toBe("dark");
    expect(root.getAttribute("data-theme")).toBe("dark");
    expect(applyThemeMode("light", root, true)).toBe("light");
    expect(root.getAttribute("data-theme")).toBe("light");
    expect(applyThemeMode("system", root, true)).toBe("dark");
    expect(root.hasAttribute("data-theme")).toBe(false);
  });

  it("le shell expose un sélecteur natif avec le mode courant présélectionné", () => {
    const html = shellHtml({ name: "dashboard" }, true, false, "simple", "dark");
    expect(html).toContain('id="theme-select"');
    expect(html).toContain('aria-label="Thème"');
    expect(html).toContain('<option value="dark" selected>Sombre</option>');
    expect(html).toContain('<option value="system">Système</option>');
    expect(html).toContain('<option value="light">Clair</option>');
  });
});
