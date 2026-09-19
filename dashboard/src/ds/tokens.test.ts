/**
 * UI-14 — contraste des tokens DS : WCAG 2.2 AA mesuré, pas jugé à l'œil.
 *
 * Textes : ≥ 4.5:1 sur fond blanc comme sur fond de page. Repère de focus et
 * sidebar : ≥ 3:1 (non-texte / grand contraste documenté dans tokens.css).
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

function loadTokens(): Record<string, string> {
  const css = readFileSync(new URL("./tokens.css", import.meta.url), "utf8");
  const tokens: Record<string, string> = {};
  for (const match of css.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) {
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

const tokens = loadTokens();
const t = (name: string): string => {
  const value = tokens[name];
  if (value === undefined) throw new Error(`token manquant : ${name}`);
  return value;
};

describe("contraste des textes (AA ≥ 4.5:1)", () => {
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

  it("bouton primaire : encre blanche sur action ≥ 4.5:1", () => {
    expect(ratio(t("ds-action-ink"), t("ds-action"))).toBeGreaterThanOrEqual(4.5);
  });
});

describe("sidebar et focus (≥ 3:1)", () => {
  it("textes sidebar sur bleu nuit ≥ 4.5:1", () => {
    expect(ratio(t("ds-navy-text"), t("ds-navy"))).toBeGreaterThanOrEqual(4.5);
    expect(ratio(t("ds-navy-muted"), t("ds-navy"))).toBeGreaterThanOrEqual(4.5);
    expect(ratio(t("ds-navy-active"), t("ds-navy"))).toBeGreaterThanOrEqual(4.5);
  });

  it("repère de focus perceptible sur fond blanc et bleu nuit ≥ 3:1", () => {
    expect(ratio(t("ds-action"), t("ds-surface"))).toBeGreaterThanOrEqual(3);
    expect(ratio("#ffffff", t("ds-navy"))).toBeGreaterThanOrEqual(3);
  });
});
