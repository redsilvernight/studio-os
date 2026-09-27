/**
 * A3 — Comptes : DOM-free (vitest, node), assertions sur les chaînes et sur
 * les appels de l'API cliente.
 */
import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import { applyAccountAction, listUserMemberships } from "../accountsApi";
import type { DirectoryUser } from "../membersApi";
import { parseRoute } from "../router";
import { shellNavGroups } from "../shell";
import { accountsRestrictedHtml, accountsTableHtml, membershipsHtml } from "./accounts";

const SELF = "aaaaaaaa-0000-4111-8111-000000000001";
const OTHER = "bbbbbbbb-0000-4111-8111-000000000002";
const P = "11111111-2222-4333-8444-555555555555";

const user = (id: string, status: DirectoryUser["status"], name = "Ada"): DirectoryUser => ({
  id,
  display_name: name,
  email: `${name.toLowerCase()}@example.test`,
  role: "developer",
  status,
  created_at: "2026-09-25T10:00:00Z",
  updated_at: "2026-09-25T10:00:00Z",
  version: 1,
});

describe("vue Comptes", () => {
  it("a sa route et son entrée de navigation", () => {
    expect(parseRoute("#/accounts")).toEqual({ name: "accounts" });
    expect(parseRoute("#/accounts/x")).toEqual({ name: "notFound", hash: "#/accounts/x" });
    const labels = shellNavGroups({ name: "accounts" }).flatMap((g) => g.items.filter((i) => i.active).map((i) => i.label));
    expect(labels).toEqual(["Comptes"]);
  });

  it("explique la restriction admin sans rien lister", () => {
    const html = accountsRestrictedHtml();
    expect(html).toContain("réservée au rôle admin");
    expect(html).not.toContain("<table");
  });

  it("affiche l'état en français et les actions adaptées, jamais sur son propre compte", () => {
    const html = accountsTableHtml(
      [user(SELF, "active", "Moi"), user(OTHER, "disabled", "Dora"), user("c", "pending", "Pia")],
      SELF,
    );
    expect(html).toContain("Actif");
    expect(html).toContain("Désactivé");
    expect(html).toContain("En attente de vérification");
    expect(html).toContain("Votre compte");
    expect(html).not.toContain(`data-account-action="disable" data-user="${SELF}"`);
    expect(html).toContain(`data-account-action="enable" data-user="${OTHER}"`);
    expect(html).toContain(`data-account-action="disable" data-user="c"`);
    expect(html).not.toMatch(/\b(pending|active|disabled)\b(?![-"])/);
  });

  it("montre un état vide explicite pour un compte sans accès", () => {
    expect(membershipsHtml([])).toContain("Aucun projet accessible");
    const html = membershipsHtml([
      { project_id: P, user_id: OTHER, granted_by_user_id: null, created_at: "2026-09-25T10:00:00Z" },
    ]);
    expect(html).toContain(`#/projects/${P}/members`);
  });
});

describe("API Comptes", () => {
  it("appelle la route d'action et renvoie le compte mis à jour", async () => {
    const POST = vi.fn().mockResolvedValue({ data: user(OTHER, "disabled"), response: { ok: true, status: 200 } });
    const client = { POST } as unknown as StudioClient;
    for (const action of ["disable", "enable", "revoke-sessions"] as const) {
      await applyAccountAction(client, OTHER, action);
      expect(POST).toHaveBeenLastCalledWith(`/api/v1/users/{user_id}/${action}`, {
        params: { path: { user_id: OTHER } },
      });
    }
  });

  it("remonte le refus serveur comme erreur typée", async () => {
    const GET = vi.fn().mockResolvedValue({
      error: { detail: { error_code: "forbidden" } },
      response: { ok: false, status: 403 },
    });
    await expect(listUserMemberships({ GET } as unknown as StudioClient, OTHER)).rejects.toMatchObject({
      status: 403,
      errorCode: "forbidden",
    });
  });
});
