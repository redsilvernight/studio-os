import { describe, expect, it } from "vitest";
import { parseRoute } from "../router";
import apiMatrix from "./api.matrix.json";
import { ROUTE_MATRIX } from "./routes.matrix";

describe("matrice de migration R0 : routes", () => {
  it.each(ROUTE_MATRIX)("%s garde son point d'entrée (%s)", (hash, name) => {
    expect(parseRoute(hash).name).toBe(name);
  });

  it("aucune adresse listée ne tombe en 404", () => {
    for (const [hash] of ROUTE_MATRIX) expect(parseRoute(hash).name).not.toBe("notFound");
  });
});

describe("matrice de migration R0 : appels d'API", () => {
  const modules = import.meta.glob<Record<string, unknown>>("../*Api.ts", { eager: true });
  const apiModule = import.meta.glob<Record<string, unknown>>("../api.ts", { eager: true });
  const byFile = { ...modules, ...apiModule };

  for (const [file, names] of Object.entries(apiMatrix as Record<string, string[]>)) {
    it(`${file} exporte toujours ses fonctions`, () => {
      const mod = byFile[`../${file}.ts`];
      if (!mod) throw new Error(`${file}.ts introuvable`);
      for (const name of names) expect(typeof mod[name], `${file}.${name}`).toBe("function");
    });
  }
});
