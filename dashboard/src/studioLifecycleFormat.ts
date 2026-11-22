/**
 * Formatage du cycle de vie des studios (atelier N1/N2/N5/N7).
 *
 * Pur (vitest, node) : libellés en toutes lettres (le rôle et le plan ne
 * reposent jamais sur la seule couleur, fiche N1), slug déterministe,
 * validations de formulaire côté client. Les seuils de places sont des
 * valeurs d'illustration (M-seuils, DEC-0387) : les valeurs définitives
 * viennent du serveur.
 */
import type { InvitationPreviewState, MemberRole, StudioPlan, StudioRole } from "./studioLifecycleApi";

/** Rôles écrits en toutes lettres (fiche N1 : « Propriétaire · Gratuit »). */
export const STUDIO_ROLE_LABEL: Record<StudioRole, string> = {
  owner: "Propriétaire",
  admin: "Administrateur",
  member: "Membre",
  viewer: "Lecture seule",
};

export const STUDIO_PLAN_LABEL: Record<StudioPlan, string> = {
  free: "Gratuit",
  pro: "Pro",
};

export function studioRoleLabel(role: StudioRole): string {
  return STUDIO_ROLE_LABEL[role] ?? role;
}

export function studioPlanLabel(plan: StudioPlan): string {
  return STUDIO_PLAN_LABEL[plan] ?? plan;
}

/** « Atelier Phare » -> « atelier-phare » (affiché avant création, fiche N1). */
export function studioSlugify(name: string): string {
  return (
    name
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48)
  );
}

export const STUDIO_NAME_FORBIDDEN_CHARS = /[<>/]/;

export const STUDIO_NAME_INVALID_MESSAGE =
  "Ce nom contient des caractères non autorisés (< > /). Utilisez des lettres, chiffres, espaces et tirets.";

/**
 * Validation du nom (fiche N1, état « Erreur ») : `null` quand le nom est
 * acceptable. Le champ est `required` côté formulaire (nom vide bloqué par
 * le navigateur), donc seul le contenu est vérifié ici.
 */
export function validateStudioName(name: string): string | null {
  if (STUDIO_NAME_FORBIDDEN_CHARS.test(name)) return STUDIO_NAME_INVALID_MESSAGE;
  if (studioSlugify(name) === "") return STUDIO_NAME_INVALID_MESSAGE;
  return null;
}

/** Adresse e-mail : contrôle minimal, message de la fiche N2. */
export const INVITE_EMAIL_INVALID_MESSAGE = "Cette adresse e-mail semble incomplète.";

export function validateInviteEmail(email: string): string | null {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim()) ? null : INVITE_EMAIL_INVALID_MESSAGE;
}

/**
 * Places par plan — valeurs d'illustration (M-seuils, DEC-0387), comme les
 * « 3 sur 5 places utilisées » de la fiche N2. Le serveur reste la vérité :
 * un refus 409 place_full prime sur ce calcul.
 */
export const STUDIO_SEAT_LIMIT: Record<StudioPlan, number> = { free: 5, pro: 50 };

export function studioSeatLimit(plan: StudioPlan): number {
  return STUDIO_SEAT_LIMIT[plan] ?? STUDIO_SEAT_LIMIT.free;
}

/** « 2026-12-05T… » -> « 5 décembre » (bandeaux N2/N7 : dates en clair). */
export function formatDayLabel(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
}

/** Rôles proposés à l'invitation (fiche N2 : Membre par défaut). */
export const INVITABLE_ROLES: MemberRole[] = ["member", "admin", "viewer"];

/**
 * Libellé de l'état d'un lien d'invitation (fiche N2). L'état est porté par
 * le texte, jamais par la seule couleur.
 */
export const INVITATION_PREVIEW_TITLE: Record<InvitationPreviewState, string> = {
  valid: "Invitation valide",
  expired: "Cette invitation a expiré",
  used: "Cette invitation a déjà été utilisée",
  unknown: "Invitation inconnue",
};
