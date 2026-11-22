import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// R1-formats : les vues ne bricolent plus pluriels, fuseau UTC ni secondes brutes.
const dir = __dirname;
const sources = readdirSync(dir)
  .filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))
  .map((name) => ({ name, text: readFileSync(join(dir, name), "utf8") }));

function offenders(pattern: RegExp): string[] {
  return sources.filter(({ text }) => pattern.test(text)).map(({ name }) => name);
}

describe("formats communs", () => {
  it("aucun « (s) » ni « (aux) » dans les libellés", () => {
    expect(offenders(/[A-Za-zÀ-ÿ]\((s|aux)\)/)).toEqual([]);
  });
  it("aucune heure UTC affichée", () => {
    expect(offenders(/timeZone:\s*"UTC"|\(UTC\)|en UTC/)).toEqual([]);
  });
  it("aucune durée en secondes affichée", () => {
    // shortcut: les champs de saisie du délai de hook restent en secondes (1 à 600), plage trop fine pour des minutes.
    const found = offenders(/\$\{[^}]*seconds?\}\s*s|(?<!quelques |des )secondes(?!\s*:)/);
    expect(found.filter((name) => name !== "hookForms.ts")).toEqual([]);
  });
});
