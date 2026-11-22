/**
 * Fiche N1 — Choix et création de studio (vitest, node).
 *
 * Chaque état de la maquette a son assertion : structure, libellés et
 * accessibilité. Les rendus sont purs (chaînes HTML) : aucun réseau ici.
 */
import { describe, expect, it } from "vitest";
import { parseRoute } from "../router";
import {
  studioChoiceHtml,
  studioCreateFormHtml,
  studioPickerEmptyHtml,
  studioPickerErrorHtml,
  studioPickerLoadingHtml,
} from "./studioPicker";
import type { StudioSummary } from "../studioLifecycleApi";

const studio = (over: Partial<StudioSummary> = {}): StudioSummary => ({
  id: "s1",
  slug: "atelier-phare",
  name: "Atelier Phare",
  plan: "free",
  status: "active",
  role: "owner",
  ...over,
});

describe("route N1", () => {
  it("expose l'écran de choix et son raccourci de création", () => {
    expect(parseRoute("#/studios")).toEqual({ name: "studios" });
    expect(parseRoute("#/studios/create")).toEqual({ name: "studios", create: true });
    expect(parseRoute("#/studios/invitations")).toEqual({ name: "studioInvitations" });
  });

  it("ne confond pas le lien d'acceptation avec une route du sélecteur", () => {
    expect(parseRoute("#/studios/invitations/acc")).toEqual({ name: "notFound", hash: "#/studios/invitations/acc" });
  });
});

describe("N1 · état « choisir »", () => {
  it("annonce le nombre de studios et le rôle en toutes lettres", () => {
    const html = studioChoiceHtml([
      studio(),
      studio({ id: "s2", name: "Binaweb", role: "member", plan: "pro" }),
      studio({ id: "s3", name: "ForkandFood", role: "viewer", plan: "free" }),
    ]);
    expect(html).toContain("Choisissez un studio");
    expect(html).toContain("Vous appartenez à 3 studios.");
    expect(html).toContain("Propriétaire · Gratuit");
    expect(html).toContain("Membre · Pro");
    expect(html).toContain("Lecture seule · Gratuit");
  });

  it("donne à chaque studio une action « Ouvrir » nommée", () => {
    const html = studioChoiceHtml([studio()]);
    expect(html).toContain('data-open-studio="s1"');
    expect(html).toContain('aria-label="Ouvrir Atelier Phare"');
  });

  it("signale un studio suspendu et l'ouvre sur son écran dédié (fiche N5)", () => {
    const html = studioChoiceHtml([studio({ status: "suspended" })]);
    expect(html).toContain("Suspendu");
    expect(html).toContain('data-suspended="true"');
  });

  it("propose la création et l'accès aux invitations reçues", () => {
    const html = studioChoiceHtml([studio()], 1);
    expect(html).toContain("＋ Créer un studio");
    expect(html).toContain("Voir mes invitations (1)");
  });

  it("masque le lien d'invitations quand il n'y en a aucune", () => {
    expect(studioChoiceHtml([studio()], 0)).not.toContain("Voir mes invitations");
  });
});

describe("N1 · état « créer »", () => {
  it("affiche le nom, le rôle figé et l'aperçu du slug", () => {
    const html = studioCreateFormHtml({ initialName: "Atelier Phare" });
    expect(html).toContain("Créer un studio");
    expect(html).toContain("Nom du studio");
    expect(html).toContain("Propriétaire");
    expect(html).toContain("Vous pourrez transférer la propriété plus tard.");
    expect(html).toContain("slug: atelier-phare · plan initial: free");
    expect(html).toContain("Créer le studio");
    expect(html).toContain("Annuler");
  });

  it("associe l'erreur au champ et le signale à l'assistance technique", () => {
    const html = studioCreateFormHtml({ initialName: "Atelier <Phare>", nameError: "Ce nom contient des caractères non autorisés (< > /)." });
    expect(html).toContain("aria-invalid=\"true\"");
    expect(html).toContain("Ce nom contient des caractères non autorisés");
    expect(html).toContain("Atelier &lt;Phare&gt;");
  });

  it("désactive la création et explique la limite quand le plan est atteint", () => {
    const html = studioCreateFormHtml({ limit: { used: 2, total: 2, planLabel: "Gratuit" } });
    expect(html).toContain("Limite atteinte : 2 studios sur 2 avec le plan Gratuit");
    expect(html).toContain("Voir l'abonnement");
    expect(html).toContain("Archiver un studio");
    expect(html).toContain("disabled aria-disabled=\"true\"");
  });
});

describe("N1 · états vide, chargement et erreur", () => {
  it("explique l'absence de studio et propose une issue", () => {
    const html = studioPickerEmptyHtml();
    expect(html).toContain("Vous n'avez pas encore de studio");
    expect(html).toContain("Créez le vôtre, ou demandez à quelqu'un de vous inviter dans le sien.");
    expect(html).toContain("Créer un studio");
    expect(html).toContain("J'ai reçu un lien d'invitation");
  });

  it("annonce le chargement sans le faire à l'écran", () => {
    const html = studioPickerLoadingHtml();
    expect(html).toContain("Vos studios…");
    expect(html).toContain("ds-skeleton");
  });

  it("donne la cause de l'erreur et une action de reprise", () => {
    const html = studioPickerErrorHtml("Serveur injoignable.");
    expect(html).toContain("Impossible de charger vos studios");
    expect(html).toContain("Serveur injoignable.");
    expect(html).toContain("Réessayer");
  });
});

describe("N1 · accessibilité", () => {
  it("nomme la liste des studios et la zone d'état vide", () => {
    expect(studioChoiceHtml([studio()])).toContain('aria-label="Vos studios"');
    expect(studioPickerEmptyHtml()).toContain('role="status"');
  });

  it("ne propose jamais un état vide sans action", () => {
    expect(studioPickerEmptyHtml()).not.toContain("href=\"#\"");
  });
});
