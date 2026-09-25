/**
 * A0 — onglet Membres : DOM-free (vitest, node), assertions sur les chaînes.
 */
import { describe, expect, it } from "vitest";
import { PROJECT_TABS, workspaceTabsHtml } from "./projectDetail";
import { membersPanelHtml, membersRestrictedHtml } from "./members";

const P = "11111111-2222-4333-8444-555555555555";
const U = "aaaaaaaa-0000-4111-8111-000000000001";
const ADMIN = "bbbbbbbb-0000-4111-8111-000000000002";

describe("onglet Membres", () => {
  it("est un onglet du workspace avec son deep link", () => {
    expect(PROJECT_TABS.map((t) => t.id)).toContain("members");
    expect(workspaceTabsHtml(P, "members")).toContain(`href="#/projects/${P}/members" aria-selected="true"`);
  });

  it("explique la restriction admin sans rien lister", () => {
    const html = membersRestrictedHtml();
    expect(html).toContain("réservée au rôle admin");
    expect(html).not.toContain("data-grant");
  });

  it("liste par UUID complet, accordant et bouton de retrait", () => {
    const html = membersPanelHtml([
      { project_id: P, user_id: U, granted_by_user_id: ADMIN, created_at: "2026-09-25T10:00:00Z" },
      { project_id: P, user_id: ADMIN, granted_by_user_id: null, created_at: "2026-09-25T09:00:00Z" },
    ]);
    expect(html).toContain("2 membre(s)");
    expect(html).toContain(`<code class="mono">${U}</code>`);
    expect(html).toContain(`data-revoke="${U}"`);
    expect(html).toContain("système (migration)");
    expect(html).toContain("data-grant");
  });

  it("montre un état vide qui garde le formulaire d'ajout", () => {
    const html = membersPanelHtml([]);
    expect(html).toContain("Aucun membre");
    expect(html).toContain("Ajouter au projet");
  });
});
