// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { paletteEntries } from "./commandPalette";
import { adminOverviewHtml, uiModeSettingHtml } from "./views/admin";
import { loadUiMode, saveUiMode, toggledUiMode, UI_MODE_STORAGE_KEY } from "./uiMode";
import { shellHtml, shellNavGroups } from "./shell";

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

/** Colonne « Aujourd'hui » du lexique (PDF Atelier, partie 4) : interdite en mode Simple. */
const LEGACY_TERMS = [
  "Accueil", "Agents IA", "Roadmap", "Réservation", "Handoff", "Vault", "Atlas", "Bibliothèque", "Library",
  "Verrou", "Clé stable", "Jeton machine", "Heartbeat", "Runtime", "Harnais", "Liaison", "Binding", "MCP",
  "Inspecteur de résolution", "Espace de travail", "Daemon", "Administration", "Configuration", "Override",
  "Navigation complète",
];
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

function visibleText(html: string): string {
  const doc = document.implementation.createHTMLDocument("");
  doc.body.innerHTML = html;
  return doc.body.textContent ?? "";
}

describe("uiMode (R2-modes)", () => {
  it("defaults to simple; unreadable or legacy values are simple", () => {
    expect(loadUiMode(memoryStore())).toBe("simple");
    expect(loadUiMode(memoryStore("complete"))).toBe("simple");
    expect(loadUiMode(null)).toBe("simple");
    const broken = { getItem: (): string => { throw new Error("denied"); }, setItem: (): void => { throw new Error("denied"); } };
    expect(loadUiMode(broken)).toBe("simple");
    expect(() => saveUiMode("expert", broken)).not.toThrow();
  });

  it("round-trips and toggles both ways", () => {
    const store = memoryStore();
    saveUiMode("expert", store);
    expect(loadUiMode(store)).toBe("expert");
    saveUiMode(toggledUiMode("expert"), store);
    expect(loadUiMode(store)).toBe("simple");
    expect(UI_MODE_STORAGE_KEY).toBe("studio-os.ui-mode");
  });

  it("simple mode shows no UUID nor legacy lexicon term (shell, palette, display setting; other screens follow their own steps)", () => {
    const surfaces = [
      visibleText(shellHtml({ name: "dashboard" }, true, false, "simple")),
      paletteEntries({ name: "dashboard" }, false, "owner", "Gratuit", "simple", () => undefined).map((e) => `${e.label} ${e.group}`).join(" "),
      visibleText(uiModeSettingHtml("simple")),
    ];
    for (const text of surfaces) {
      expect(text).not.toMatch(UUID);
      for (const term of LEGACY_TERMS) expect(text, term).not.toContain(term);
    }
  });

  it("expert only adds: every simple destination keeps its place", () => {
    const flat = (mode: "simple" | "expert"): string[] =>
      shellNavGroups({ name: "dashboard" }, false, mode).flatMap((group) => group.items.map((item) => `${group.title}|${item.href}|${item.label}`));
    expect(flat("expert")).toEqual(flat("simple"));
    const simple = paletteEntries({ name: "dashboard" }, false, "owner", "Gratuit", "simple", () => undefined).map((e) => e.label);
    const expert = paletteEntries({ name: "dashboard" }, false, "owner", "Gratuit", "expert", () => undefined).map((e) => e.label);
    expect(expert.filter((l) => !l.includes("mode"))).toEqual(simple.filter((l) => !l.includes("mode")));
    expect(simple).toContain("Passer en mode Expert");
    expect(expert).toContain("Revenir au mode Simple");
    expect(shellHtml({ name: "dashboard" }, true, false, "simple")).not.toContain("nav-mode-toggle");
  });

  it("settings expose the mode switch reflecting the current mode", () => {
    expect(adminOverviewHtml(undefined, false, "simple")).toContain("data-ui-mode-toggle>");
    expect(adminOverviewHtml(undefined, false, "expert")).toContain("data-ui-mode-toggle checked>");
  });
});
