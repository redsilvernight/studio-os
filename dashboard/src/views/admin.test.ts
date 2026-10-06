// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { ADMIN_FAMILIES, adminOverviewHtml } from "./admin";

describe("adminOverviewHtml (P05-admin)", () => {
  it("mène aux 6 familles en 1 clic, sans identifiant visible", () => {
    expect(ADMIN_FAMILIES.map((f) => f.href)).toEqual([
      "#/machines",
      "#/accounts",
      "#/transfers",
      "#/library",
      "#/configuration/runtimes",
      "#/workspaces",
    ]);
    const html = adminOverviewHtml();
    expect(html).toContain("<h1>Administration</h1>");
    expect(html.match(/<h1>/g)).toHaveLength(1);
    expect(html).toContain("Revoir les comptes");
    for (const family of ADMIN_FAMILIES) {
      expect(html).toContain(`href="${family.href}"`);
      expect(html).toContain(family.title);
    }
    expect(html).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/i);
    expect(html).not.toContain("Connecté");
  });

  it("replie la technique et renvoie les experts hors de l'entrée", () => {
    const html = adminOverviewHtml();
    expect(html).toContain("<details");
    expect(html).toContain("Détails techniques");
    expect(html).toContain("Outils experts");
    expect(html).not.toContain("#/graphs");
  });
});
