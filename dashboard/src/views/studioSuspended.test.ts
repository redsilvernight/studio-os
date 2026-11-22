/**
 * Fiche N5 — Studio suspendu (vitest, node).
 *
 * L'API n'expose que `status: "suspended"` : le motif est donc rendu en
 * texte fixe selon le rôle (S3b). Les variantes de la fiche restent
 * disponibles pour les états d'erreur et de limite.
 */
import { describe, expect, it } from "vitest";
import { parseRoute } from "../router";
import {
  studioSuspendedAdminHtml,
  studioSuspendedBlockedHtml,
  studioSuspendedEmptyHtml,
  studioSuspendedLoadingHtml,
  studioSuspendedMemberHtml,
  studioSuspendedOwnerHtml,
  studioSuspendedPaymentErrorHtml,
  SUSPENDED_OWNER_REASON,
} from "./studioSuspended";

const ROWS = [{ name: "Prototype mods en réseau", lastActivity: "Dernière activité il y a 3 jours" }];

describe("route N5", () => {
  it("expose l'écran par identifiant de studio", () => {
    expect(parseRoute("#/studios/s1/suspended")).toEqual({ name: "studioSuspended", id: "s1" });
  });
});

describe("N5 · propriétaire", () => {
  it("donne le motif et la porte de sortie vers la régularisation", () => {
    const html = studioSuspendedOwnerHtml("Atelier Phare", ROWS, "#/studios/s1/data");
    expect(html).toContain("Ce studio est suspendu");
    expect(html).toContain(SUSPENDED_OWNER_REASON);
    expect(html).toContain("Régulariser le paiement");
    expect(html).toContain("Exporter mes données");
  });

  it("rappelle la lecture seule", () => {
    const html = studioSuspendedOwnerHtml("Atelier Phare", ROWS);
    expect(html).toContain("Lecture seule : vous pouvez consulter et exporter, mais plus rien ne peut être modifié ni envoyé.");
  });
});

describe("N5 · membre", () => {
  it("explique sans reproche et propose de prévenir le propriétaire", () => {
    const html = studioSuspendedMemberHtml("Atelier Phare", "Flo", ROWS);
    expect(html).toContain("Le propriétaire (Flo) a été prévenu.");
    expect(html).toContain("En attendant, vous gardez la lecture et l'export de vos contributions.");
    expect(html).toContain("Prévenir Flo");
    expect(html).toContain("Exporter mes données");
  });
});

describe("N5 · suspendu par l'administration", () => {
  it("indique l'origine de la suspension et le contact support", () => {
    const html = studioSuspendedAdminHtml("Atelier Phare", ROWS);
    expect(html).toContain("Votre studio a été suspendu par l'équipe Studi'OS.");
    expect(html).toContain("aucun contenu n'a été supprimé");
    expect(html).toContain("Contacter le support");
  });
});

describe("N5 · contenu en lecture seule", () => {
  it("liste le contenu avec la pastille « Lecture seule »", () => {
    const html = studioSuspendedOwnerHtml("Atelier Phare", ROWS);
    expect(html).toContain("Prototype mods en réseau");
    expect(html).toContain("Lecture seule");
  });
});

describe("N5 · états chargement, erreur et vide", () => {
  it("annonce la réouverture en chargement", () => {
    const html = studioSuspendedLoadingHtml();
    expect(html).toContain("Réouverture du studio…");
    expect(html).toContain("ds-skeleton");
  });

  it("explique l'échec du paiement sans perte de données", () => {
    const html = studioSuspendedPaymentErrorHtml();
    expect(html).toContain("Le paiement n'a pas abouti");
    expect(html).toContain("Aucune donnée n'est perdue ; le studio reste en lecture seule.");
    expect(html).toContain("Réessayer");
    expect(html).toContain("Changer de carte");
  });

  it("dit qu'il n'y a rien à consulter", () => {
    const html = studioSuspendedEmptyHtml();
    expect(html).toContain("Rien à consulter pour l'instant");
    expect(html).toContain("Ce studio ne contient encore aucun projet.");
  });
});

describe("N5 · état limite", () => {
  it("bloque les écritures et garde l'export possible", () => {
    const html = studioSuspendedBlockedHtml("Atelier Phare");
    expect(html).toContain("Action indisponible : studio suspendu");
    expect(html).toContain("Créer, envoyer et inviter sont désactivés.");
    expect(html).toContain("Consulter et exporter restent possibles.");
    expect(html).toContain("Voir comment rouvrir");
    expect(html).toContain("disabled aria-disabled=\"true\"");
  });
});

describe("N5 · accessibilité", () => {
  it("annonce la suspension comme une alerte", () => {
    expect(studioSuspendedOwnerHtml("Atelier Phare", ROWS)).toContain('role="alert"');
    expect(studioSuspendedPaymentErrorHtml()).toContain('role="alert"');
  });

  it("nomme chaque action du bandeau", () => {
    expect(studioSuspendedOwnerHtml("Atelier Phare", ROWS)).toContain("Exporter mes données");
    expect(studioSuspendedMemberHtml("Atelier Phare", "Flo", ROWS)).toContain("Prévenir Flo");
  });
});
