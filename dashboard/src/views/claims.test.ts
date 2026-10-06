/**
 * Réservations : confirmation de libération nommant le détenteur,
 * bouton Libérer désactivé sur une réservation déjà libérée.
 *
 * DOM-free (vitest, environnement node) : assertions sur les chaînes produites.
 */
import { describe, expect, it } from "vitest";
import { resetActorNames, setActorNames } from "../actorNames";
import type { ResourceClaim } from "../claimsApi";
import { filterClaims, paginateClaims, releaseClaimConfirmText, rowsHtml } from "./claims";

const claim = {
  id: "claim-1",
  project_id: "proj-1",
  task_id: null,
  resource_path: "godot/scenes/level1.tscn",
  resource_type: "file",
  claimed_by_machine_id: "abcdef12-3456",
  status: "active",
  ttl_seconds: 3600,
  expires_at: new Date(Date.now() + 3_600_000).toISOString(),
} as unknown as ResourceClaim;

describe("filtre et pagination", () => {
  const released = { ...claim, id: "c2", status: "released" } as ResourceClaim;
  const expired = { ...claim, id: "c3", expires_at: new Date(Date.now() - 1000).toISOString() } as ResourceClaim;
  const all = [claim, released, expired];

  it("filtre par état : actives, passées (expirées + libérées), toutes", () => {
    const now = Date.now();
    expect(filterClaims(all, "active", now)).toEqual([claim]);
    expect(filterClaims(all, "past", now)).toEqual([released, expired]);
    expect(filterClaims(all, "all", now)).toHaveLength(3);
  });

  it("pagine par 10 et borne la page demandée", () => {
    const items = Array.from({ length: 25 }, (_, i) => i);
    expect(paginateClaims(items, 1)).toMatchObject({ pages: 3, page: 1 });
    expect(paginateClaims(items, 3).items).toEqual([20, 21, 22, 23, 24]);
    expect(paginateClaims(items, 99).page).toBe(3);
    expect(paginateClaims(items, 0).page).toBe(1);
    expect(paginateClaims([], 5)).toEqual({ items: [], page: 1, pages: 1 });
  });
});

describe("libération d'une réservation", () => {
  it("confirmation : chemin et machine détentrice, texte brut", () => {
    setActorNames([{ id: "abcdef12-3456", display_name: "flo-laptop" }], []);
    const text = releaseClaimConfirmText(claim);
    expect(text).toContain("godot/scenes/level1.tscn");
    expect(text).toContain("machine flo-laptop");
    expect(text).not.toContain("<");
    resetActorNames();
  });

  it("bouton Libérer actif sur une réservation active, désactivé une fois libérée", () => {
    const releaseButton = (html: string): string => /<button[^>]*data-release[^>]*>/.exec(html)?.[0] ?? "";
    expect(releaseButton(rowsHtml([claim], true))).not.toContain("disabled");
    expect(releaseButton(rowsHtml([{ ...claim, status: "released" } as ResourceClaim], true))).toContain("disabled");
    expect(releaseButton(rowsHtml([claim], false))).toContain("disabled");
  });
});
