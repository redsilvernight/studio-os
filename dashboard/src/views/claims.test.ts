/**
 * Réservations : confirmation de libération nommant le détenteur,
 * bouton Libérer désactivé sur une réservation déjà libérée.
 *
 * DOM-free (vitest, environnement node) : assertions sur les chaînes produites.
 */
import { describe, expect, it } from "vitest";
import { resetActorNames, setActorNames } from "../actorNames";
import type { ResourceClaim } from "../claimsApi";
import { releaseClaimConfirmText, rowsHtml } from "./claims";

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
