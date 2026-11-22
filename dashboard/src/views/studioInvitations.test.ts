/**
 * Fiche N2 — Invitations : envoi et acceptation (vitest, node).
 *
 * Les états de la maquette sont vérifiés un par un : dialogue d'envoi,
 * confirmation, erreur d'adresse, limite de places, liste en attente vide,
 * puis acceptation valide / expirée / déjà utilisée / inconnue.
 */
import { describe, expect, it } from "vitest";
import { parseRoute } from "../router";
import {
  invitationAcceptHtml,
  invitationAcceptLoadingHtml,
  invitationExpiredHtml,
  invitationUnknownHtml,
  invitationUsedHtml,
  inviteDialogHtml,
  inviteFormHtml,
  inviteSentHtml,
  pendingInvitationsHtml,
  studioInvitationsPageHtml,
} from "./studioInvitations";
import type { StudioInvitation } from "../studioLifecycleApi";

const invitation = (over: Partial<StudioInvitation> = {}): StudioInvitation => ({
  id: "inv_1",
  studio_id: "s1",
  email: "lucie@exemple.fr",
  role: "member",
  expires_at: "2026-11-28T10:00:00Z",
  consumed_at: null,
  invited_by_user_id: "u1",
  created_at: "2026-11-21T10:00:00Z",
  ...over,
});

const DIALOG = {
  studioName: "Atelier Phare",
  seatsUsed: 3,
  seatsTotal: 5,
};

describe("route d'acceptation", () => {
  it("ne porte que le jeton — aucune information en query", () => {
    expect(parseRoute("#/invitations/accept/tok")).toEqual({ name: "invitationAccept", token: "tok" });
    expect(parseRoute("#/invitations/accept")).toEqual({ name: "invitationAccept", token: null });
  });
});

describe("N2 · dialogue d'envoi", () => {
  it("demande l'adresse, le rôle et rappelle les places restantes", () => {
    const html = inviteFormHtml(DIALOG);
    expect(html).toContain("Adresse e-mail");
    expect(html).toContain("Rôle");
    expect(html).toContain("3 sur 5 places utilisées");
    expect(html).toContain("Le lien expire dans 7 jours et ne sert qu'une fois.");
    expect(html).toContain("Envoyer l'invitation");
    expect(html).toContain("Annuler");
  });

  it("explicite le sens de chaque rôle", () => {
    const html = inviteFormHtml(DIALOG);
    expect(html).toContain("Membre : travaille sur les projets.");
    expect(html).toContain("Administrateur : gère aussi l'équipe et les appareils.");
  });

  it("propose Membre par défaut et jamais Propriétaire", () => {
    const html = inviteFormHtml(DIALOG);
    expect(html).toContain('<option value="member" selected>');
    expect(html).not.toContain(">Propriétaire</option>");
  });

  it("annonce le studio dans le titre accessible du dialogue", () => {
    const html = inviteDialogHtml(DIALOG);
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain("Inviter dans Atelier Phare");
  });
});

describe("N2 · état « envoi confirmé »", () => {
  it("confirme l'envoi et propose la suite", () => {
    const html = inviteSentHtml("lucie@exemple.fr");
    expect(html).toContain("Invitation envoyée à lucie@exemple.fr");
    expect(html).toContain("Elle apparaît en attente dans Équipe et accès.");
    expect(html).toContain("Inviter quelqu'un d'autre");
    expect(html).toContain("Terminer");
  });
});

describe("N2 · état « erreur »", () => {
  it("marque le champ et désactive l'envoi quand l'adresse est incomplète", () => {
    const html = inviteFormHtml({ ...DIALOG, initialEmail: "lucie@exemple", emailError: "Cette adresse e-mail semble incomplète." });
    expect(html).toContain("Cette adresse e-mail semble incomplète.");
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain("data-invite-send disabled aria-disabled=\"true\"");
  });

  it("explique le cas du compte connecté différent", () => {
    const html = inviteFormHtml({ ...DIALOG, mismatch: { invitedEmail: "karim@exemple.fr", currentEmail: "flo@exemple.fr" } });
    expect(html).toContain("Connecté avec un autre compte ?");
    expect(html).toContain("Cette invitation est destinée à karim@exemple.fr.");
    expect(html).toContain("Vous êtes connecté avec flo@exemple.fr.");
    expect(html).toContain("Changer de compte");
  });
});

describe("N2 · état « limite »", () => {
  it("explique que toutes les places sont prises et bloque l'envoi", () => {
    const html = inviteFormHtml({ ...DIALOG, seatsUsed: 5, seatsTotal: 5, full: true });
    expect(html).toContain("Toutes les places sont prises : 5 sur 5");
    expect(html).toContain("Libérez une place en retirant un membre, ou passez à Pro");
    expect(html).toContain("Voir l'abonnement");
    expect(html).toContain("Gérer les membres");
    expect(html).toContain("data-invite-send disabled aria-disabled=\"true\"");
  });
});

describe("N2 · liste des invitations en attente", () => {
  it("dit clairement qu'aucune invitation n'est en attente", () => {
    const html = pendingInvitationsHtml([]);
    expect(html).toContain("Invitations en attente");
    expect(html).toContain("Aucune invitation en attente.");
  });

  it("permet de renvoyer et d'annuler depuis la ligne", () => {
    const html = pendingInvitationsHtml([invitation()]);
    expect(html).toContain("lucie@exemple.fr");
    expect(html).toContain("Membre · expire le");
    expect(html).toContain('data-invitation-resend="inv_1"');
    expect(html).toContain('data-invitation-revoke="inv_1"');
    expect(html).toContain('aria-label="Annuler l\'invitation de lucie@exemple.fr"');
  });
});

describe("N2 · page « Équipe et accès »", () => {
  it("porte l'action d'invitation et la liste en attente", () => {
    const html = studioInvitationsPageHtml(DIALOG, [invitation()]);
    expect(html).toContain("Équipe et accès");
    expect(html).toContain("Inviter quelqu'un");
    expect(html).toContain("Invitations en attente");
  });
});

describe("N2 · acceptation", () => {
  it("annonce la vérification sans afficher de contenu", () => {
    const html = invitationAcceptLoadingHtml();
    expect(html).toContain("Vérification de l'invitation…");
    expect(html).toContain("ds-skeleton");
  });

  it("nomme l'invitant, le studio et le rôle quand le lien est valide", () => {
    const html = invitationAcceptHtml({ inviterName: "Marie", studioName: "Atelier Phare", roleLabel: "Membre" });
    expect(html).toContain("Marie vous invite dans Atelier Phare");
    expect(html).toContain("Vous y serez Membre");
    expect(html).toContain("Accepter et rejoindre");
    expect(html).toContain("Refuser");
  });

  it("reste acceptable même sans informations lisibles", () => {
    const html = invitationAcceptHtml();
    expect(html).toContain("Accepter et rejoindre");
    expect(html).toContain("Vous êtes invité dans un studio");
  });

  it("explique l'expiration et propose de demander un nouveau lien", () => {
    const html = invitationExpiredHtml("Marie");
    expect(html).toContain("Cette invitation a expiré");
    expect(html).toContain("Elle n'était valable que 7 jours.");
    expect(html).toContain("Demandez à Marie de vous en envoyer une nouvelle.");
    expect(html).toContain("Écrire à Marie");
  });

  it("explique l'invitation déjà utilisée sans reproche", () => {
    const html = invitationUsedHtml("Atelier Phare");
    expect(html).toContain("Cette invitation a déjà été utilisée");
    expect(html).toContain("Vous êtes déjà membre de Atelier Phare : rien d'autre à faire.");
    expect(html).toContain("Ouvrir Atelier Phare");
  });

  it("distingue le jeton inconnu de l'invitation expirée", () => {
    const html = invitationUnknownHtml();
    expect(html).toContain("Invitation inconnue");
    expect(html).not.toContain("a expiré");
  });

  it("explique le refus pour un compte différent et propose de changer", () => {
    const html = invitationWrongAccountHtml();
    expect(html).toContain("Cette invitation est destinée à une autre adresse");
    expect(html).toContain("Changer de compte");
    expect(html).not.toContain("a expiré");
  });
});

describe("N2 · accessibilité", () => {
  it("annonce les états par une région live", () => {
    expect(inviteSentHtml("lucie@exemple.fr")).toContain('role="status"');
    expect(invitationExpiredHtml("Marie")).toContain('role="status"');
    expect(invitationUsedHtml("Atelier Phare")).toContain('role="status"');
  });

  it("nomme chaque action de la liste en attente", () => {
    const html = pendingInvitationsHtml([invitation()]);
    expect(html).toContain('aria-label="Renvoyer l\'invitation à lucie@exemple.fr"');
    expect(html).toContain('aria-label="Annuler l\'invitation de lucie@exemple.fr"');
  });
});
