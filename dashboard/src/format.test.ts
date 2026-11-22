import { describe, expect, it } from "vitest";
import {
  formatAmount,
  formatDay,
  formatDuration,
  formatMonth,
  formatNumber,
  formatRelative,
  formatVolume,
  plural,
  sfx,
} from "./format";

const NOW = Date.parse("2026-11-22T12:00:00Z");
const ago = (seconds: number): string => new Date(NOW - seconds * 1000).toISOString();

describe("pluriels", () => {
  it("0 et 1 au singulier, 2 et plus au pluriel", () => {
    expect([0, 1, 2, 10].map(sfx)).toEqual(["", "", "s", "s"]);
    expect(plural(1, "fichier")).toBe("1 fichier");
    expect(plural(3, "fichier")).toBe("3 fichiers");
    expect(plural(2, "cheval", "chevaux")).toBe("2 chevaux");
  });
});

describe("dates", () => {
  it("un jour calendaire ne subit aucun décalage de fuseau", () => {
    expect(formatDay("2026-11-22")).toBe("22/11/2026");
    expect(formatDay("2026-11-22", true)).toBe("dimanche 22 novembre 2026");
    expect(formatDay("n'importe quoi")).toBe("n'importe quoi");
    expect(formatMonth("2026-11")).toBe("novembre 2026");
  });
  it("durée relative", () => {
    expect(formatRelative(ago(10), NOW)).toBe("à l'instant");
    expect(formatRelative(ago(240), NOW)).toBe("il y a 4 min");
    expect(formatRelative(ago(7200), NOW)).toBe("il y a 2 h");
    expect(formatRelative(ago(90000), NOW)).toBe("il y a 1 jour");
    expect(formatRelative(ago(3 * 86400), NOW)).toBe("il y a 3 jours");
    expect(formatRelative(null, NOW)).toBeNull();
    expect(formatRelative("pas une date", NOW)).toBeNull();
  });
});

describe("durées, volumes, montants", () => {
  it("durée lisible, jamais en secondes", () => {
    expect(formatDuration(12)).toBe("moins d'une minute");
    expect(formatDuration(300)).toBe("5 min");
    expect(formatDuration(3600)).toBe("1 h");
    expect(formatDuration(7500)).toBe("2 h 05");
    expect(formatDuration(3 * 86400)).toBe("3 jours");
    expect(formatDuration(Number.NaN)).toBe("—");
  });
  it("volume en Gio", () => {
    expect(formatVolume(2 * 1024 ** 3)).toBe("2 Gio");
    expect(formatVolume(0.5 * 1024 ** 3)).toBe(`${formatNumber(0.5)} Gio`);
    expect(formatVolume(null)).toBe("—");
  });
  it("montant", () => {
    expect(formatAmount("12.50", "EUR")).toBe("12,50 EUR");
    expect(formatAmount("1", null)).toBe("1 (devise inconnue)");
  });
});
