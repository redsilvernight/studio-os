/**
 * UI-14 — contraste des tokens DS : WCAG 2.2 AA mesuré, pas jugé à l'œil.
 *
 * Deux thèmes (clair, sombre) passent la même matrice : textes ≥ 4.5:1 sur
 * fond de surface comme sur fond de page, sémantiques ≥ 4.5:1 sur leurs
 * fonds pastel, encre des boutons ≥ 4.5:1, repère de focus et sidebar ≥ 3:1.
 * Le bloc sombre « système » (media query) doit rester identique au bloc
 * explicite `[data-theme="dark"]`, et les polices restent auto-hébergées.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./tokens.css", import.meta.url), "utf8");
const fontsCss = readFileSync(new URL("./fonts.css", import.meta.url), "utf8");
const cspSource = readFileSync(new URL("../../csp-policy.ts", import.meta.url), "utf8");

/**
 * Corps de la première règle dont la liste de sélecteurs contient
 * exactement `selector`. Les commentaires sont retirés (les sélecteurs
 * y sont mentionnés pour la documentation) et l'appartenance à la liste
 * est testée partie par partie : `:root` ne doit pas attraper
 * `:root[data-theme="dark"]`.
 */
function ruleBody(source: string, selector: string): string {
  const withoutComments = source.replace(/\/\*[\s\S]*?\*\//g, "");
  let index = withoutComments.indexOf(selector);
  while (index >= 0) {
    // La liste de sélecteurs court de la fin de la règle précédente
    // jusqu'à l'accolade d'ouverture.
    const listStart = Math.max(
      withoutComments.lastIndexOf("}", index),
      withoutComments.lastIndexOf("{", index),
    );
    const listEnd = withoutComments.indexOf("{", index);
    const list = withoutComments.slice(listStart + 1, listEnd);
    const parts = list.split(",").map((part) => part.trim());
    if (parts.includes(selector)) {
      let depth = 0;
      for (let i = listEnd; i < withoutComments.length; i += 1) {
        if (withoutComments[i] === "{") depth += 1;
        else if (withoutComments[i] === "}") {
          depth -= 1;
          if (depth === 0) return withoutComments.slice(listEnd + 1, i);
        }
      }
      throw new Error(`règle non fermée : ${selector}`);
    }
    index = withoutComments.indexOf(selector, index + 1);
  }
  throw new Error(`règle absente : ${selector}`);
}

function loadTokens(selector: string): Record<string, string> {
  const tokens: Record<string, string> = {};
  for (const match of ruleBody(css, selector).matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    tokens[match[1] as string] = (match[2] as string).toLowerCase();
  }
  return tokens;
}

function luminance(hex: string): number {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const f = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function ratio(a: string, b: string): number {
  const hi = Math.max(luminance(a), luminance(b));
  const lo = Math.min(luminance(a), luminance(b));
  return (hi + 0.05) / (lo + 0.05);
}

const light = loadTokens(":root");
const dark = loadTokens(':root[data-theme="dark"]');
const darkSystem = loadTokens(':root:not([data-theme="light"])');
// Fragments forcés (catalogue « les deux thèmes ») : mêmes valeurs que le
// thème correspondant, sans dépendre de la préférence du poste.
const lightPreview = loadTokens('[data-ds-theme-preview="light"]');
const darkPreview = loadTokens('[data-ds-theme-preview="dark"]');
const themes: Array<[string, Record<string, string>]> = [
  ["clair", light],
  ["sombre", dark],
];

for (const [themeName, tokens] of themes) {
  const t = (name: string): string => {
    const value = tokens[name];
    if (value === undefined) throw new Error(`token manquant (${themeName}) : ${name}`);
    return value;
  };

  describe(`thème ${themeName} — contraste des textes (AA ≥ 4.5:1)`, () => {
    const backgrounds = { surface: t("ds-surface"), page: t("ds-bg") };
    const texts = {
      texte: t("ds-text"),
      atténué: t("ds-text-muted"),
      discret: t("ds-text-faint"),
      action: t("ds-action"),
      succès: t("ds-success"),
      avertissement: t("ds-warning"),
      erreur: t("ds-danger"),
      ia: t("ds-ai"),
    };
    for (const [bgName, bg] of Object.entries(backgrounds)) {
      for (const [txName, tx] of Object.entries(texts)) {
        it(`${txName} sur fond ${bgName} ≥ 4.5:1`, () => {
          expect(ratio(tx, bg)).toBeGreaterThanOrEqual(4.5);
        });
      }
    }

    it("textes sémantiques sur leurs fonds pastels ≥ 4.5:1", () => {
      expect(ratio(t("ds-action"), t("ds-action-soft"))).toBeGreaterThanOrEqual(4.5);
      expect(ratio(t("ds-success"), t("ds-success-soft"))).toBeGreaterThanOrEqual(4.5);
      expect(ratio(t("ds-warning"), t("ds-warning-soft"))).toBeGreaterThanOrEqual(4.5);
      expect(ratio(t("ds-danger"), t("ds-danger-soft"))).toBeGreaterThanOrEqual(4.5);
      expect(ratio(t("ds-ai"), t("ds-ai-soft"))).toBeGreaterThanOrEqual(4.5);
    });

    it("boutons pleins : encre ≥ 4.5:1 sur action et danger", () => {
      expect(ratio(t("ds-action-ink"), t("ds-action"))).toBeGreaterThanOrEqual(4.5);
      expect(ratio(t("ds-danger-ink"), t("ds-danger"))).toBeGreaterThanOrEqual(4.5);
    });

    it("texte sur aplat fort (lien d'évitement, infobulles) ≥ 4.5:1", () => {
      expect(ratio(t("ds-ink-inverse"), t("ds-text"))).toBeGreaterThanOrEqual(4.5);
    });

    it("barre latérale ≥ 4.5:1 et focus ≥ 3:1", () => {
      for (const name of ["ds-navy-text", "ds-navy-muted", "ds-navy-active"]) {
        expect(ratio(t(name), t("ds-navy")), name).toBeGreaterThanOrEqual(4.5);
      }
      expect(ratio(t("ds-navy-active"), t("ds-nav-current"))).toBeGreaterThanOrEqual(4.5);
      expect(ratio(t("ds-action"), t("ds-surface"))).toBeGreaterThanOrEqual(3);
    });

    it("rôles Atelier : info et marque lisibles sur leur fond pastel", () => {
      expect(ratio(t("ds-info"), t("ds-info-soft"))).toBeGreaterThanOrEqual(4.5);
      expect(ratio(t("ds-brand"), t("ds-brand-soft"))).toBeGreaterThanOrEqual(4.5);
    });
  });
}

describe("thème sombre — cohérence des deux entrées CSS", () => {
  it("la media query système et l'attribut explicite portent les mêmes valeurs", () => {
    expect(darkSystem).toEqual(dark);
  });

  it("le thème clair reste le défaut (aucun attribut requis)", () => {
    expect(light["ds-bg"]).toBe("#f6f4f0");
    expect(light["ds-action"]).toBe("#5440d0");
    expect(light["ds-ai"]).toBe("#0a747e");
  });
});

describe("aperçu des deux thèmes (fragments forcés)", () => {
  it("l'aperçu clair porte les mêmes tokens que le thème clair", () => {
    expect(lightPreview).toEqual(light);
  });

  it("l'aperçu sombre porte les mêmes tokens que le thème sombre", () => {
    expect(darkPreview).toEqual(dark);
  });
});

describe("polices locales (CSP inchangée)", () => {
  it("aucune URL distante : les woff2 sont servies par le bundle", () => {
    expect(fontsCss).not.toMatch(/https?:\/\//);
    const sources = [...fontsCss.matchAll(/url\("([^"]+\.woff2)"\)/g)].map((m) => m[1] as string);
    expect(sources).toHaveLength(4);
    for (const source of sources) expect(source.startsWith("../assets/fonts/")).toBe(true);
  });

  it("gabarits Atelier : rayons 10/14/20, cibles 44 px, texte 16 px", () => {
    const root = ruleBody(css, ":root");
    expect(root).toContain("--ds-radius-md: 10px");
    expect(root).toContain("--ds-radius-lg: 14px");
    expect(root).toContain("--ds-radius-xl: 20px");
    expect(root).toContain("--ds-target: 44px");
    expect(root).toContain("--ds-text-base: 16px");
  });

  it("les tokens typographiques pointent d'abord sur les familles locales", () => {
    expect(ruleBody(css, ":root")).toContain('--ds-font-sans: "Figtree"');
    expect(ruleBody(css, ":root")).toContain('--ds-font-mono: "JetBrains Mono"');
  });

  it("la CSP autorise uniquement les polices same-origin", () => {
    expect(cspSource).toContain('"font-src \'self\'"');
  });
});
