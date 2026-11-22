/**
 * Cycle de vie des studios — formatage pur (vitest, node).
 *
 * Les libellés ne reposent jamais sur la seule couleur (fiche N1), le slug
 * est déterministe, les validations de formulaire reprennent les messages
 * exacts des maquettes.
 */
import { describe, expect, it } from "vitest";
import {
  formatDayLabel,
  INVITABLE_ROLES,
  INVITE_EMAIL_INVALID_MESSAGE,
  STUDIO_NAME_INVALID_MESSAGE,
  studioPlanLabel,
  studioRoleLabel,
  studioSeatLimit,
  studioSlugify,
  validateInviteEmail,
  validateStudioName,
} from "./studioLifecycleFormat";

describe("libellés de rôle et de plan", () => {
  it("écrit le rôle en toutes lettres, jamais par une pastille de couleur", () => {
    expect(studioRoleLabel("owner")).toBe("Propriétaire");
    expect(studioRoleLabel("admin")).toBe("Administrateur");
    expect(studioRoleLabel("member")).toBe("Membre");
    expect(studioRoleLabel("viewer")).toBe("Lecture seule");
  });

  it("écrit le plan en toutes lettres", () => {
    expect(studioPlanLabel("free")).toBe("Gratuit");
    expect(studioPlanLabel("pro")).toBe("Pro");
  });
});

describe("slug de studio", () => {
  it("transforme un nom en slug affiché avant création", () => {
    expect(studioSlugify("Atelier Phare")).toBe("atelier-phare");
    expect(studioSlugify("  Binaweb  ")).toBe("binaweb");
    expect(studioSlugify("ForkandFood")).toBe("forkandfood");
  });

  it("retire les accents et les caractères non alphanumériques", () => {
    expect(studioSlugify("Créativité Studio")).toBe("creativite-studio");
    expect(studioSlugify("A/B")).toBe("a-b");
    expect(studioSlugify("...")).toBe("");
  });
});

describe("validation du nom de studio", () => {
  it("accepte un nom ordinaire", () => {
    expect(validateStudioName("Atelier Phare")).toBeNull();
    expect(validateStudioName("Studio 2026")).toBeNull();
  });

  it("refuse les caractères interdits avec le message de la fiche N1", () => {
    expect(validateStudioName("Atelier <Phare>")).toBe(STUDIO_NAME_INVALID_MESSAGE);
    expect(validateStudioName("Atelier/Phare")).toBe(STUDIO_NAME_INVALID_MESSAGE);
    expect(STUDIO_NAME_INVALID_MESSAGE).toContain("lettres, chiffres, espaces et tirets");
  });

  it("refuse un nom sans contenu exploitable", () => {
    expect(validateStudioName("   ")).toBe(STUDIO_NAME_INVALID_MESSAGE);
    expect(validateStudioName("---")).toBe(STUDIO_NAME_INVALID_MESSAGE);
  });
});

describe("validation de l'adresse e-mail d'invitation", () => {
  it("accepte une adresse plausible", () => {
    expect(validateInviteEmail("lucie@exemple.fr")).toBeNull();
  });

  it("refuse une adresse incomplète avec le message de la fiche N2", () => {
    expect(validateInviteEmail("lucie@exemple")).toBe(INVITE_EMAIL_INVALID_MESSAGE);
    expect(validateInviteEmail("")).toBe(INVITE_EMAIL_INVALID_MESSAGE);
    expect(validateInviteEmail("lucie exemple.fr")).toBe(INVITE_EMAIL_INVALID_MESSAGE);
  });
});

describe("places et dates", () => {
  it("donne un plafond de places par plan (valeurs d'illustration)", () => {
    expect(studioSeatLimit("free")).toBe(5);
    expect(studioSeatLimit("pro")).toBe(50);
  });

  it("écrit une date en clair pour les bandeaux", () => {
    expect(formatDayLabel("2026-12-05T10:00:00Z")).toContain("5");
    expect(formatDayLabel("pas-une-date")).toBe("pas-une-date");
  });
});

describe("rôles proposables à une invitation", () => {
  it("propose membre, administrateur et lecture seule — jamais propriétaire", () => {
    expect(INVITABLE_ROLES).toEqual(["member", "admin", "viewer"]);
    expect(INVITABLE_ROLES).not.toContain("owner");
  });
});
