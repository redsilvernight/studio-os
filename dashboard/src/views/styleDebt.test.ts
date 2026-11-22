/**
 * R1-dette : une seule couche de style. Les feuilles de vues ne portent ni
 * couleur, ni z-index, ni taille de police en dur (tout passe par les tokens
 * de ds/tokens.css), et aucune vue n'appelle window.confirm (confirmDs).
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const VIEWS = join(__dirname);
const read = (name: string): string => readFileSync(join(VIEWS, name), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

describe("views/*.css", () => {
  const sheets = readdirSync(VIEWS).filter((name) => name.endsWith(".css"));
  it("trouve les feuilles de vues", () => expect(sheets.length).toBeGreaterThan(10));
  for (const sheet of sheets) {
    it(`${sheet} : aucune couleur, z-index ni font-size en dur`, () => {
      const css = read(sheet);
      expect(css.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).toEqual([]);
      expect(css.match(/\brgba?\(|\bhsla?\(/g) ?? []).toEqual([]);
      expect(css.match(/z-index\s*:\s*-?\d+/g) ?? []).toEqual([]);
      expect(css.match(/font-size\s*:\s*[\d.]+(px|rem)/g) ?? []).toEqual([]);
    });
  }
});

describe("views/*.ts", () => {
  it("aucun window.confirm : confirmDs à la place", () => {
    const offenders = readdirSync(VIEWS)
      .filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))
      .filter((name) => /window\.confirm\(/.test(readFileSync(join(VIEWS, name), "utf8")));
    expect(offenders).toEqual([]);
  });
});
