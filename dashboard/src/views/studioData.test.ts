/**
 * Fiche N7 — Export et suppression d'un studio (vitest, node).
 *
 * « Le client possède ses données » : export d'abord, suppression ensuite,
 * jamais silencieuse. Chaque état de la maquette est vérifié.
 */
import { describe, expect, it } from "vitest";
import { parseRoute } from "../router";
import {
  DELETION_CONSEQUENCES_DEFAULT,
  studioDangerZoneHtml,
  studioDataEmptyHtml,
  studioDataPageHtml,
  studioDeletionDialogHtml,
  studioDeletionGraceHtml,
  studioExportCardHtml,
  studioExportErrorHtml,
  studioExportLimitHtml,
  studioExportPreparingHtml,
  studioExportReadyHtml,
} from "./studioData";

describe("route N7", () => {
  it("expose l'écran par identifiant de studio", () => {
    expect(parseRoute("#/studios/s1/data")).toEqual({ name: "studioData", id: "s1" });
  });
});

describe("N7 · export", () => {
  it("décrit l'archive et sa durée de validité", () => {
    const html = studioExportCardHtml();
    expect(html).toContain("Exporter le studio");
    expect(html).toContain("Une archive datée de tout votre studio : projets, notes, fichiers, journal.");
    expect(html).toContain("Le lien est valable 15 minutes.");
    expect(html).toContain("Préparer l'export");
  });

  it("annonce la préparation et autorise à quitter la page", () => {
    const html = studioExportPreparingHtml();
    expect(html).toContain("Export en préparation");
    expect(html).toContain("Vous pouvez quitter cette page : nous vous prévenons quand c'est prêt.");
    expect(html).toContain("ds-skeleton");
  });

  it("donne le lien de téléchargement quand l'export est prêt", () => {
    const html = studioExportReadyHtml({ fileName: "Atelier-Phare-2026-11-21.zip", downloadUrl: "https://storage.example/x.zip", size: "1,8 Gio" });
    expect(html).toContain("Votre export est prêt");
    expect(html).toContain("Atelier-Phare-2026-11-21.zip · 1,8 Gio · lien valable 15 minutes.");
    expect(html).toContain('href="https://storage.example/x.zip"');
    expect(html).toContain("Télécharger");
    expect(html).toContain("Préparer un nouvel export");
  });

  it("dit ce qui n'a pas été fait quand l'export échoue", () => {
    const html = studioExportErrorHtml("Stockage indisponible.");
    expect(html).toContain("Impossible de charger cette page");
    expect(html).toContain("L'export n'a pas pu être préparé. Rien n'a été modifié.");
    expect(html).toContain("Relancer l'export");
    expect(html).toContain("Stockage indisponible.");
  });

  it("explique qu'un seul export à la fois", () => {
    const html = studioExportLimitHtml();
    expect(html).toContain("Un export est déjà en cours");
    expect(html).toContain("Un seul export à la fois.");
    expect(html).toContain("Voir l'avancement");
  });

  it("dit qu'il n'y a rien à exporter", () => {
    const html = studioDataEmptyHtml();
    expect(html).toContain("Studio vide");
    expect(html).toContain("Il n'y a encore rien à exporter dans ce studio.");
  });
});

describe("N7 · suppression", () => {
  it("réserve la zone sensible au propriétaire", () => {
    const owner = studioDangerZoneHtml({ isOwner: true });
    expect(owner).toContain("Supprimer le studio");
    expect(owner).toContain("Effacement définitif après un délai de grâce de 14 jours. Réservé au propriétaire.");
    expect(owner).not.toContain("disabled");
  });

  it("désactive la suppression pour qui n'est pas propriétaire", () => {
    const other = studioDangerZoneHtml({ isOwner: false });
    expect(other).toContain("Réservé au propriétaire.");
    expect(other).toContain("disabled aria-disabled=\"true\"");
  });

  it("liste les conséquences avant de demander confirmation", () => {
    const html = studioDeletionDialogHtml("Atelier Phare");
    expect(html).toContain("Supprimer Atelier Phare ?");
    expect(html).toContain(DELETION_CONSEQUENCES_DEFAULT);
    expect(html).toContain("Tapez le nom du studio pour confirmer");
    expect(html).toContain("Supprimer définitivement dans 14 jours");
    expect(html).toContain("Annuler");
  });

  it("utilise un alertdialog et bloque la confirmation tant que le nom n'est pas retapé", () => {
    const html = studioDeletionDialogHtml("Atelier Phare");
    expect(html).toContain('role="alertdialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('data-delete-confirm disabled aria-disabled="true"');
  });

  it("donne la date d'effacement et la porte d'annulation pendant le délai de grâce", () => {
    const html = studioDeletionGraceHtml("2026-12-05T10:00:00Z");
    expect(html).toContain("Suppression programmée le 5 décembre");
    expect(html).toContain("Le studio est en lecture seule.");
    expect(html).toContain("Annuler la suppression");
    expect(html).toContain("Exporter avant");
  });
});

describe("N7 · page complète", () => {
  it("enchaîne l'export puis la zone sensible, et porte le délai de grâce", () => {
    const html = studioDataPageHtml({
      studioName: "Atelier Phare",
      deletionScheduledAt: "2026-12-05T10:00:00Z",
      exportState: { kind: "none" },
      isOwner: true,
    });
    expect(html).toContain("Confidentialité");
    expect(html).toContain("Qui peut voir quoi, et les accès exceptionnels au studio.");
    expect(html).toContain("Suppression programmée le 5 décembre");
    expect(html.indexOf("Exporter le studio")).toBeLessThan(html.indexOf("Supprimer le studio"));
  });

  it("affiche l'état vide quand le studio n'a rien à exporter", () => {
    const html = studioDataPageHtml({
      studioName: "Atelier Phare",
      deletionScheduledAt: null,
      exportState: { kind: "none" },
      isOwner: true,
      empty: true,
    });
    expect(html).toContain("Studio vide");
    expect(html).not.toContain("Exporter le studio</h2>");
  });

  it("affiche l'export prêt sans repasser par la carte de préparation", () => {
    const html = studioDataPageHtml({
      studioName: "Atelier Phare",
      deletionScheduledAt: null,
      exportState: { kind: "ready", fileName: "a.zip", downloadUrl: "https://storage.example/a.zip" },
      isOwner: true,
    });
    expect(html).toContain("Votre export est prêt");
    expect(html).not.toContain("Export en préparation");
  });
});

describe("N7 · accessibilité", () => {
  it("annonce les états par une région live", () => {
    expect(studioExportReadyHtml({ fileName: "a.zip", downloadUrl: "https://s/a.zip" })).toContain('role="status"');
    expect(studioExportErrorHtml("x")).toContain('role="alert"');
    expect(studioExportLimitHtml()).toContain('role="status"');
    expect(studioDeletionGraceHtml("2026-12-05T10:00:00Z")).toContain('role="status"');
  });

  it("associe le champ de confirmation à son étiquette", () => {
    expect(studioDeletionDialogHtml("Atelier Phare")).toContain('for="delete-confirm-name"');
  });
});

describe("N7 · dialogue de suppression sans chiffres inventés", () => {
  it("ne cite aucun volume propre à un autre studio", () => {
    const html = studioDeletionDialogHtml("Atelier Phare");
    expect(html).not.toMatch(/1 240|1,8 Gio|4 projets/);
  });
});
