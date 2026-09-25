/**
 * A0 — onglet Membres : DOM-free (vitest, node), assertions sur les chaînes.
 */
import { describe, expect, it } from "vitest";
import type { DirectoryUser } from "../membersApi";
import { PROJECT_TABS, workspaceTabsHtml } from "./projectDetail";
import { candidatesHtml, membersPanelHtml, membersRestrictedHtml } from "./members";

const P = "11111111-2222-4333-8444-555555555555";
const U = "aaaaaaaa-0000-4111-8111-000000000001";
const ADMIN = "bbbbbbbb-0000-4111-8111-000000000002";
const OTHER = "cccccccc-0000-4111-8111-000000000003";

const user = (id: string, display_name: string, email: string): DirectoryUser => ({
  id,
  display_name,
  email,
  role: "developer",
  created_at: "2026-09-25T10:00:00Z",
  updated_at: "2026-09-25T10:00:00Z",
  version: 1,
});

describe("onglet Membres", () => {
  it("est un onglet du workspace avec son deep link", () => {
    expect(PROJECT_TABS.map((t) => t.id)).toContain("members");
    expect(workspaceTabsHtml(P, "members")).toContain(`href="#/projects/${P}/members" aria-selected="true"`);
  });

  it("explique la restriction admin sans rien lister", () => {
    const html = membersRestrictedHtml();
    expect(html).toContain("réservée au rôle admin");
    expect(html).not.toContain("data-user-search");
  });

  it("liste par nom et e-mail, accordant nommé et bouton de retrait", () => {
    const html = membersPanelHtml([
      {
        project_id: P,
        user_id: U,
        granted_by_user_id: ADMIN,
        created_at: "2026-09-25T10:00:00Z",
        user_display_name: "Dev <Un>",
        user_email: "dev@example.test",
      },
      {
        project_id: P,
        user_id: ADMIN,
        granted_by_user_id: null,
        created_at: "2026-09-25T09:00:00Z",
        user_display_name: "Admin",
        user_email: "admin@example.test",
      },
    ]);
    expect(html).toContain("2 membre(s)");
    expect(html).toContain("<strong>Dev &lt;Un&gt;</strong>");
    expect(html).toContain("dev@example.test");
    expect(html).toContain(`<td>Admin</td>`);
    expect(html).toContain(`data-revoke="${U}"`);
    expect(html).toContain(`aria-label="Retirer Dev &lt;Un&gt; du projet"`);
    expect(html).toContain("système (migration)");
    expect(html).toContain("data-user-search");
    expect(html).not.toContain('name="user_id"');
  });

  it("retombe sur l'identifiant d'un accordant qui n'est pas membre", () => {
    const html = membersPanelHtml([
      { project_id: P, user_id: U, granted_by_user_id: OTHER, created_at: "2026-09-25T10:00:00Z" },
    ]);
    expect(html).toContain(`title="${OTHER}"`);
    expect(html).toContain("Utilisateur inconnu");
  });

  it("montre un état vide qui garde la recherche d'ajout", () => {
    const html = membersPanelHtml([]);
    expect(html).toContain("Aucun membre");
    expect(html).toContain("Rechercher un utilisateur");
    expect(html).toContain('name="q"');
  });
});

describe("candidats à l'ajout", () => {
  it("propose d'ajouter les non-membres et signale les membres", () => {
    const html = candidatesHtml(
      [user(U, "Dev", "dev@example.test"), user(ADMIN, "Admin", "admin@example.test")],
      new Set([ADMIN]),
    );
    expect(html).toContain(`data-grant-user="${U}"`);
    expect(html).not.toContain(`data-grant-user="${ADMIN}"`);
    expect(html).toContain("Déjà membre");
    expect(html).toContain("dev@example.test");
  });

  it("échappe les champs et gère une recherche vide", () => {
    expect(candidatesHtml([user(U, "<b>x</b>", "x@example.test")], new Set())).toContain("&lt;b&gt;x&lt;/b&gt;");
    expect(candidatesHtml([], new Set())).toContain("Aucun utilisateur trouvé.");
  });
});
