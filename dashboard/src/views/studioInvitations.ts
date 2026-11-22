/**
 * Fiche N2 — Invitations : envoi et acceptation (docs/maquettes-atelier/nouveaux.html).
 *
 * Deux surfaces :
 * - Côté propriétaire : dialogue d'invitation depuis « Équipe et accès »
 *   (états envoi, confirmé, adresse invalide, plus de place libre) et liste
 *   des invitations en attente (état vide inclus ; renvoyer/annuler depuis la
 *   ligne, décision de maquette N2).
 * - Côté destinataire : page d'acceptation à usage unique liée par e-mail
 *   (états chargement, lien valide, expiré, déjà utilisée).
 *
 * Contrat : POST/GET/DELETE /studios/{id}/invitations ; POST
 * /invitations/preview {token} -> {state: 'valid'|'expired'|'used'|'unknown',
 * studio_name, role, inviter_display_name} ; POST /invitations/accept {token}
 * -> 200 {status:'accepted', studio_id, role} ou 410 avec error_code
 * « invitation_expired » (expirée) / « invitation_used » (déjà utilisée).
 *
 * Le lien d'acceptation ne porte aucune information en query : tout est lu
 * via /invitations/preview avant l'acceptation.
 */
import { describeError, esc } from "../ui";
import { ApiError } from "../api";
import { confirmDs } from "../ds/confirm";
import {
  closeDsDialog,
  dsEmptyState,
  dsErrorState,
  dsField,
  dsNotify,
  dsPageHeader,
  dsSkeleton,
  openDsDialog,
} from "../ds/ds";
import { dsIcon } from "../ds/lot1";
import {
  acceptInvitation,
  createStudioInvitation,
  getStudio,
  listStudioInvitations,
  listStudioMembers,
  listStudios,
  previewInvitation,
  revokeStudioInvitation,
  type InvitationPreview,
  type MemberRole,
  type StudioInvitation,
  type StudioRole,
} from "../studioLifecycleApi";
import {
  formatDayLabel,
  INVITABLE_ROLES,
  studioRoleLabel,
  studioSeatLimit,
  validateInviteEmail,
} from "../studioLifecycleFormat";
import { getActiveStudioId, setActiveStudioId } from "../studioContext";
import "./studioLifecycle.css";

export interface StudioInvitationsContext {
  baseUrl: string;
  authed: boolean;
}

export const INVITE_DIALOG_ID = "studio-invite-dialog";

export interface InviteDialogOptions {
  studioName: string;
  seatsUsed: number;
  seatsTotal: number;
  /** État « Erreur » : adresse incomplète (champ marqué + envoi désactivé). */
  emailError?: string | null;
  initialEmail?: string;
  /** État « Erreur » : compte connecté différent du destinataire visé. */
  mismatch?: { invitedEmail: string; currentEmail: string } | null;
  /** État « Limite » : plus de place libre (envoi désactivé). */
  full?: boolean;
}

/** Bandeau ds-banner avec titre gras + corps (message éventuel riche). */
function bannerHtml(tone: "info" | "warning" | "danger" | "success", title: string, body: string, actions = ""): string {
  const icon = tone === "info" ? "info" : tone === "success" ? "check" : "alert-triangle";
  return (
    `<div class="ds-banner ds-banner--${tone}" role="${tone === "danger" ? "alert" : "status"}">${dsIcon(icon, 20)}` +
    `<div class="ds-banner-body"><strong>${esc(title)}</strong><span>${body}</span></div>${actions}</div>`
  );
}

/**
 * Formulaire du dialogue « Inviter dans <studio> » : e-mail, rôle, places
 * disponibles. Rendu aussi bien dans l'overlay initial qu'après re-rendu
 * (erreur d'adresse, places épuisées) sans perdre le câblage de l'overlay.
 */
export function inviteFormHtml(options: InviteDialogOptions): string {
  const emailError = options.emailError ?? null;
  const full = options.full === true;
  const emailField = dsField(
    "invite-email",
    "Adresse e-mail",
    `<input class="ds-input" id="FIELD" name="email" type="email" required autocomplete="off" placeholder="lucie@exemple.fr" value="${esc(options.initialEmail ?? "")}">`,
    "",
    emailError ?? "",
  );
  const roleOptions = INVITABLE_ROLES.map(
    (role) => `<option value="${esc(role)}"${role === "member" ? " selected" : ""}>${esc(studioRoleLabel(role))}</option>`,
  ).join("");
  const roleField = dsField(
    "invite-role",
    "Rôle",
    `<select class="ds-select" id="FIELD" name="role">${roleOptions}</select>`,
    "Membre : travaille sur les projets. Administrateur : gère aussi l'équipe et les appareils.",
  );
  const seats = full
    ? bannerHtml(
        "warning",
        `Toutes les places sont prises : ${esc(String(options.seatsTotal))} sur ${esc(String(options.seatsTotal))}`,
        `Libérez une place en retirant un membre, ou passez à Pro pour accueillir plus de monde.` +
          `<div class="studio-banner-actions"><button type="button" class="ds-btn ds-btn--primary" data-invite-limit-subscribe>Voir l'abonnement</button>` +
          `<button type="button" class="ds-btn" data-invite-manage-members>Gérer les membres</button></div>`,
      )
    : `<p class="ds-list-sub">${esc(String(options.seatsUsed))} sur ${esc(String(options.seatsTotal))} places utilisées. Le lien expire dans 7 jours et ne sert qu'une fois.</p>`;
  const mismatch =
    options.mismatch == null
      ? ""
      : bannerHtml(
          "warning",
          "Connecté avec un autre compte ?",
          `À l'acceptation : « Cette invitation est destinée à ${esc(options.mismatch.invitedEmail)}. ` +
            `Vous êtes connecté avec ${esc(options.mismatch.currentEmail)}. » ` +
            `<a href="#/accounts">Changer de compte</a>`,
        );
  const disabled = emailError !== null || full;
  return (
    `<form data-invite-form>${emailField}${roleField}${seats}${mismatch}` +
    `<div class="ds-dialog-actions">` +
    `<button type="submit" class="ds-btn ds-btn--primary" data-invite-send${disabled ? ` disabled aria-disabled="true"` : ""}>Envoyer l'invitation</button>` +
    `<button type="button" class="ds-btn" data-ds-close>Annuler</button></div>` +
    `<div data-invite-msg class="ds-list-sub" role="status"></div></form>`
  );
}

/** Dialogue complet (overlay ds, fermé par défaut) contenant le formulaire. */
export function inviteDialogHtml(options: InviteDialogOptions): string {
  return (
    `<div class="ds-overlay" id="${INVITE_DIALOG_ID}" hidden><div class="ds-modal" role="dialog" aria-modal="true" ` +
    `aria-labelledby="${INVITE_DIALOG_ID}-title"><h2 id="${INVITE_DIALOG_ID}-title">Inviter dans ${esc(options.studioName)}</h2>` +
    `<div data-invite-body>${inviteFormHtml(options)}</div></div></div>`
  );
}

/** État « Envoi · confirmé » : corps du dialogue une fois l'invitation partie. */
export function inviteSentHtml(email: string): string {
  return (
    `<div class="ds-empty ds-empty--illustrated" role="status">` +
    `<span class="ds-empty-art" aria-hidden="true">${dsIcon("check", 40)}</span>` +
    `<h3>Invitation envoyée à ${esc(email)}</h3>` +
    `<p>Elle apparaît en attente dans Équipe et accès. Vous pouvez la renvoyer ou l'annuler.</p>` +
    `<div class="studio-actions"><button type="button" class="ds-btn ds-btn--primary" data-invite-another>Inviter quelqu'un d'autre</button>` +
    `<button type="button" class="ds-btn" data-ds-close>Terminer</button></div></div>`
  );
}

function invitationRowHtml(invitation: StudioInvitation): string {
  return (
    `<li class="ds-list-item"><div class="grow"><div class="ds-list-title">${esc(invitation.email)}</div>` +
    `<div class="ds-list-sub">${esc(studioRoleLabel(invitation.role))} · expire le ${esc(formatDayLabel(invitation.expires_at))}</div></div>` +
    `<button type="button" class="ds-btn ds-btn--sm" data-invitation-resend="${esc(invitation.id)}" aria-label="Renvoyer l'invitation à ${esc(invitation.email)}">Renvoyer</button>` +
    `<button type="button" class="ds-btn ds-btn--sm" data-invitation-revoke="${esc(invitation.id)}" aria-label="Annuler l'invitation de ${esc(invitation.email)}">Annuler</button></li>`
  );
}

/** Carte « Invitations en attente » (état vide de la fiche inclus). */
export function pendingInvitationsHtml(invitations: StudioInvitation[]): string {
  const body =
    invitations.length === 0
      ? `<p class="ds-list-sub">Aucune invitation en attente.</p>`
      : `<ul class="ds-list">${invitations.map(invitationRowHtml).join("")}</ul>`;
  return `<section class="ds-card studio-pending" aria-label="Invitations en attente"><h2>Invitations en attente</h2>${body}</section>`;
}

/** Page « Équipe et accès » : en-tête, action d'invitation, liste en attente. */
export function studioInvitationsPageHtml(dialog: InviteDialogOptions, invitations: StudioInvitation[]): string {
  return (
    dsPageHeader("Équipe et accès", "", [{ label: "Inviter quelqu'un", variant: "primary", id: "invite-open" }]) +
    `<div class="studio-sections">${pendingInvitationsHtml(invitations)}</div>` +
    inviteDialogHtml(dialog)
  );
}

/* ------------------------------------------------------------------ */
/* Page d'acceptation (destinataire)                                   */
/* ------------------------------------------------------------------ */

export interface InvitationAcceptInfo {
  inviterName?: string;
  studioName?: string;
  roleLabel?: string;
}

function acceptSolo(inner: string): string {
  return `<div class="studio-solo"><section class="ds-card studio-solo-card studio-solo-card--accept" aria-label="Invitation">${inner}</section></div>`;
}

/** État « Acceptation · chargement ». */
export function invitationAcceptLoadingHtml(): string {
  return acceptSolo(`<h1>Vérification de l'invitation…</h1>${dsSkeleton(3)}`);
}

/**
 * État « Acceptation · lien valide » : qui invite, dans quel studio, avec
 * quel rôle. Les informations viennent de POST /invitations/preview ; sans
 * studio connu, un libellé neutre remplace le nom — l'acceptation reste
 * possible.
 */
export function invitationAcceptHtml(info: InvitationAcceptInfo = {}): string {
  const known = info.studioName !== undefined && info.studioName !== "";
  const inviter = info.inviterName === undefined || info.inviterName === "" ? "On" : info.inviterName;
  const title = known
    ? `${esc(inviter)} vous invite dans ${esc(info.studioName as string)}`
    : "Vous êtes invité dans un studio";
  const role = info.roleLabel === undefined ? "membre" : esc(info.roleLabel);
  const body = known
    ? `Vous y serez ${role} : vous verrez ses projets et pourrez travailler avec son équipe et ses agents.`
    : `Vous y serez ${role} : vous verrez les projets du studio et pourrez travailler avec son équipe et ses agents.`;
  return acceptSolo(
    `<h1>${title}</h1><p class="ds-list-sub">${body}</p>` +
      `<div class="studio-actions"><button type="button" class="ds-btn ds-btn--primary" data-invitation-accept>Accepter et rejoindre</button>` +
      `<button type="button" class="ds-btn ds-btn--ghost" data-invitation-refuse>Refuser</button></div>`,
  );
}

/** État « Acceptation · lien expiré » (410 invitation_expired). */
export function invitationExpiredHtml(inviterName?: string): string {
  const who = inviterName === undefined || inviterName === "" ? "la personne qui vous a invité" : esc(inviterName);
  const action =
    inviterName === undefined || inviterName === ""
      ? ""
      : `<div class="studio-actions"><button type="button" class="ds-btn ds-btn--primary" data-write-inviter>Écrire à ${who}</button></div>`;
  return acceptSolo(
    `<div class="ds-empty ds-empty--illustrated" role="status">` +
      `<span class="ds-empty-art" aria-hidden="true">${dsIcon("alert-triangle", 40)}</span>` +
      `<h3>Cette invitation a expiré</h3>` +
      `<p>Elle n'était valable que 7 jours. Demandez à ${who} de vous en envoyer une nouvelle.</p>${action}</div>`,
  );
}

/** État « Acceptation · déjà utilisée » (410 invitation_used). */
export function invitationUsedHtml(studioName?: string, studioId?: string): string {
  const name = studioName === undefined || studioName === "" ? "ce studio" : esc(studioName);
  const id = studioId === undefined ? "" : esc(studioId);
  return acceptSolo(
    bannerHtml(
      "info",
      "Cette invitation a déjà été utilisée",
      `Vous êtes déjà membre de ${name} : rien d'autre à faire.` +
        `<div class="studio-banner-actions"><button type="button" class="ds-btn ds-btn--primary" data-open-accepted-studio="${id}">Ouvrir ${name}</button></div>`,
    ),
  );
}

/* ------------------------------------------------------------------ */
/* Rendus                                                              */
/* ------------------------------------------------------------------ */

interface InvitePageState extends InviteDialogOptions {
  studioId: string;
  invitations: StudioInvitation[];
}

function dialogBody(root: HTMLElement): HTMLElement | null {
  return root.querySelector<HTMLElement>(`#${INVITE_DIALOG_ID} [data-invite-body]`);
}

function wireInviteForm(root: HTMLElement, ctx: StudioInvitationsContext, state: InvitePageState): void {
  const form = root.querySelector<HTMLFormElement>("[data-invite-form]");
  if (form === null) return;
  // Corriger l'adresse rouvre l'envoi (le serveur revalide à la soumission).
  form.querySelector<HTMLInputElement>('input[name="email"]')?.addEventListener("input", () => {
    const send = form.querySelector<HTMLButtonElement>("[data-invite-send]");
    if (send !== null && form.querySelector("[data-invite-limit-subscribe]") === null) {
      send.disabled = false;
      send.removeAttribute("aria-disabled");
    }
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const email = String(new FormData(form).get("email") ?? "").trim();
    const role = String(new FormData(form).get("role") ?? "member") as MemberRole;
    const emailError = validateInviteEmail(email);
    if (emailError !== null) {
      // État « Erreur » de la fiche : champ marqué, envoi désactivé, focus.
      const body = dialogBody(root);
      if (body !== null) {
        body.innerHTML = inviteFormHtml({ ...state, initialEmail: email, emailError, mismatch: null });
      }
      wireInviteForm(root, ctx, state);
      root.querySelector<HTMLInputElement>('input[name="email"]')?.focus();
      return;
    }
    const send = form.querySelector<HTMLButtonElement>("[data-invite-send]");
    if (send !== null) send.disabled = true;
    createStudioInvitation(ctx.baseUrl, state.studioId, email, role)
      .then(() => {
        const body = dialogBody(root);
        if (body !== null) body.innerHTML = inviteSentHtml(email);
        wireInviteSent(root, ctx, state);
        void reloadPending(root, ctx, state);
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 409) {
          // État « Limite » : plus de place libre (le serveur est la vérité).
          const body = dialogBody(root);
          if (body !== null) body.innerHTML = inviteFormHtml({ ...state, initialEmail: email, emailError: null, full: true });
          wireInviteForm(root, ctx, state);
          return;
        }
        const msg = form.querySelector<HTMLElement>("[data-invite-msg]");
        if (send !== null) send.disabled = false;
        if (msg !== null) msg.textContent = describeError(error);
      });
  });
  form.querySelector("[data-invite-limit-subscribe]")?.addEventListener("click", () => {
    dsNotify("Passer à Pro n'est pas encore disponible depuis cette page.", "info");
  });
  form.querySelector("[data-invite-manage-members]")?.addEventListener("click", () => {
    closeDsDialog(root, INVITE_DIALOG_ID);
  });
}

function wireInviteSent(root: HTMLElement, ctx: StudioInvitationsContext, state: InvitePageState): void {
  root.querySelector("[data-invite-another]")?.addEventListener("click", () => {
    const body = dialogBody(root);
    if (body !== null) body.innerHTML = inviteFormHtml({ ...state, initialEmail: "", emailError: null, full: false, mismatch: null });
    wireInviteForm(root, ctx, state);
    root.querySelector<HTMLInputElement>('input[name="email"]')?.focus();
  });
}

async function reloadPending(root: HTMLElement, ctx: StudioInvitationsContext, state: InvitePageState): Promise<void> {
  try {
    const invitations = await listStudioInvitations(ctx.baseUrl, state.studioId);
    state.invitations = invitations;
    const card = root.querySelector(".studio-pending");
    if (card !== null) card.outerHTML = pendingInvitationsHtml(invitations);
    wirePendingRows(root, ctx, state);
  } catch {
    // La liste reste telle qu'affichée ; l'envoi vient d'être confirmé.
  }
}

function wirePendingRows(root: HTMLElement, ctx: StudioInvitationsContext, state: InvitePageState): void {
  root.querySelectorAll<HTMLButtonElement>("[data-invitation-revoke]").forEach((button) => {
    button.addEventListener("click", async () => {
      const ok = await confirmDs("Annuler cette invitation ? Le lien ne pourra plus être utilisé.", {
        title: "Annuler l'invitation",
        confirmLabel: "Annuler l'invitation",
        danger: true,
      });
      if (!ok) return;
      button.disabled = true;
      try {
        await revokeStudioInvitation(ctx.baseUrl, state.studioId, button.dataset["invitationRevoke"] ?? "");
        dsNotify("Invitation annulée.", "success");
        await reloadPending(root, ctx, state);
      } catch (error) {
        button.disabled = false;
        dsNotify(describeError(error), "danger");
      }
    });
  });
  root.querySelectorAll<HTMLButtonElement>("[data-invitation-resend]").forEach((button) => {
    button.addEventListener("click", () => {
      const invitation = state.invitations.find((item) => item.id === (button.dataset["invitationResend"] ?? ""));
      if (invitation === undefined) return;
      button.disabled = true;
      createStudioInvitation(ctx.baseUrl, state.studioId, invitation.email, invitation.role as MemberRole)
        .then(async () => {
          dsNotify("Invitation renvoyée.", "success");
          await reloadPending(root, ctx, state);
        })
        .catch((error: unknown) => {
          button.disabled = false;
          dsNotify(describeError(error), "danger");
        });
    });
  });
}

/**
 * Résout le studio courant : studio actif du contexte de session sinon le
 * premier studio où l'on peut inviter (owner/admin). `null` si aucun studio.
 */
export async function resolveInvitationStudio(
  baseUrl: string,
): Promise<{ studioId: string; studioName: string; seatsUsed: number; seatsTotal: number } | null> {
  const studios = await listStudios(baseUrl);
  const activeId = getActiveStudioId();
  const studio =
    studios.find((item) => item.id === activeId) ??
    studios.find((item) => item.role === "owner" || item.role === "admin") ??
    studios[0];
  if (studio === undefined) return null;
  const detail = await getStudio(baseUrl, studio.id);
  let seatsUsed = 0;
  try {
    seatsUsed = (await listStudioMembers(baseUrl, studio.id)).length;
  } catch {
    seatsUsed = 0;
  }
  return { studioId: studio.id, studioName: detail.name, seatsUsed, seatsTotal: studioSeatLimit(detail.plan) };
}

/** Rendu de la page « Équipe et accès » (envoi + liste des invitations). */
export async function renderStudioInvitations(root: HTMLElement, ctx: StudioInvitationsContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = dsErrorState("Session requise", "Ouvrez une session pour gérer les invitations de votre studio.");
    return;
  }
  root.innerHTML = `<div class="studio-sections">${dsSkeleton(3)}</div>`;
  let resolved: Awaited<ReturnType<typeof resolveInvitationStudio>>;
  try {
    resolved = await resolveInvitationStudio(ctx.baseUrl);
  } catch (error) {
    root.innerHTML = dsErrorState("Invitations indisponibles", describeError(error), { label: "Réessayer", href: "#/studios/invitations" });
    return;
  }
  if (resolved === null) {
    root.innerHTML =
      dsPageHeader("Équipe et accès") +
      `<div class="studio-sections">${dsEmptyState("Vous n'avez pas encore de studio", "Créez le vôtre, ou demandez à quelqu'un de vous inviter dans le sien.", { label: "Choisir un studio", href: "#/studios" })}</div>`;
    return;
  }
  let invitations: StudioInvitation[] = [];
  try {
    invitations = await listStudioInvitations(ctx.baseUrl, resolved.studioId);
  } catch (error) {
    root.innerHTML = dsErrorState("Invitations indisponibles", describeError(error), { label: "Réessayer", href: "#/studios/invitations" });
    return;
  }
  const state: InvitePageState = {
    studioId: resolved.studioId,
    studioName: resolved.studioName,
    seatsUsed: resolved.seatsUsed,
    seatsTotal: resolved.seatsTotal,
    invitations,
  };
  root.innerHTML = studioInvitationsPageHtml(state, invitations);
  const open = root.querySelector<HTMLElement>("#invite-open");
  if (open !== null) open.addEventListener("click", () => openDsDialog(root, INVITE_DIALOG_ID, open));
  wireInviteForm(root, ctx, state);
  wirePendingRows(root, ctx, state);
}

export interface InvitationAcceptRoute {
  token: string | null;
}

function wireAcceptFallbacks(root: HTMLElement): void {
  const openButton = root.querySelector<HTMLButtonElement>("[data-open-accepted-studio]");
  openButton?.addEventListener("click", () => {
    const studioId = openButton.dataset["openAcceptedStudio"];
    if (studioId !== undefined && studioId !== "") setActiveStudioId(studioId);
    location.hash = "#/";
  });
  root.querySelector("[data-write-inviter]")?.addEventListener("click", () => {
    dsNotify("Répondez à l'e-mail d'invitation pour demander un nouveau lien.", "info");
  });
}

/** État « Acceptation · lien inconnu » (jeton absent du serveur). */
export function invitationUnknownHtml(): string {
  return acceptSolo(
    `<div class="ds-empty ds-empty--illustrated" role="status">` +
      `<span class="ds-empty-art" aria-hidden="true">${dsIcon("alert-triangle", 40)}</span>` +
      `<h3>Invitation inconnue</h3>` +
      `<p>Ce lien ne correspond à aucune invitation. Demandez une nouvelle invitation à la personne qui vous a invité.</p></div>`,
  );
}

/**
 * État « Erreur · compte différent » (403 à l'acceptation) : l'invitation
 * vise une adresse précise ; le serveur refuse un compte différent. On
 * l'explique et on propose de changer de compte — jamais un refus muet.
 */
export function invitationWrongAccountHtml(): string {
  return acceptSolo(
    bannerHtml(
      "warning",
      "Cette invitation est destinée à une autre adresse",
      `Vous êtes connecté avec un autre compte que celui visé par l'invitation.` +
        `<div class="studio-banner-actions"><a class="ds-btn ds-btn--primary" href="#/accounts">Changer de compte</a></div>`,
    ),
  );
}

/**
 * Rendu de la page d'acceptation (fiche N2, côté destinataire).
 *
 * L'état du lien est lu via POST /invitations/preview avant toute action :
 * valide, expirée, déjà utilisée ou inconnue. Le jeton ne transite jamais
 * dans l'URL affichée à l'utilisateur.
 */
export async function renderInvitationAccept(root: HTMLElement, ctx: { baseUrl: string }, route: InvitationAcceptRoute): Promise<void> {
  root.innerHTML = invitationAcceptLoadingHtml();
  if (route.token === null || route.token === "") {
    root.innerHTML = dsErrorState("Lien d'invitation incomplet", "Ouvrez le lien reçu par e-mail : il contient votre invitation.");
    return;
  }
  const token = route.token;
  let preview: InvitationPreview;
  try {
    preview = await previewInvitation(ctx.baseUrl, token);
  } catch (error) {
    root.innerHTML = dsErrorState("Invitation impossible", describeError(error), {
      label: "Réessayer",
      id: "invitation-accept-retry",
    });
    root.querySelector("#invitation-accept-retry")?.addEventListener("click", () => {
      void renderInvitationAccept(root, ctx, route);
    });
    return;
  }
  const info: InvitationAcceptInfo = {
    inviterName: preview.inviter_display_name ?? undefined,
    studioName: preview.studio_name ?? undefined,
    roleLabel: preview.role === null ? undefined : studioRoleLabel(preview.role as StudioRole),
  };
  if (preview.state === "expired") {
    root.innerHTML = invitationExpiredHtml(info.inviterName);
    wireAcceptFallbacks(root);
    return;
  }
  if (preview.state === "used") {
    root.innerHTML = invitationUsedHtml(info.studioName);
    wireAcceptFallbacks(root);
    return;
  }
  if (preview.state === "unknown") {
    root.innerHTML = invitationUnknownHtml();
    wireAcceptFallbacks(root);
    return;
  }
  root.innerHTML = invitationAcceptHtml(info);
  const acceptButton = root.querySelector<HTMLButtonElement>("[data-invitation-accept]");
  acceptButton?.addEventListener("click", () => {
    acceptButton.disabled = true;
    acceptInvitation(ctx.baseUrl, token)
      .then((result) => {
        setActiveStudioId(result.studio_id);
        location.hash = "#/";
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 410) {
          // 410 : « invitation_expired » (expirée) ou « invitation_used »
          // (déjà utilisée). Le code d'erreur tranche, jamais le statut seul.
          const used = error.errorCode === "invitation_used";
          root.innerHTML = used ? invitationUsedHtml(info.studioName) : invitationExpiredHtml(info.inviterName);
          wireAcceptFallbacks(root);
          return;
        }
        if (error instanceof ApiError && error.status === 403) {
          // Fiche N2 « Erreur · compte différent » : l'invitation vise une
          // adresse précise, le compte connecté n'est pas le bon.
          root.innerHTML = invitationWrongAccountHtml();
          wireAcceptFallbacks(root);
          return;
        }
        acceptButton.disabled = false;
        root.innerHTML = dsErrorState("Invitation impossible", describeError(error), {
          label: "Réessayer",
          id: "invitation-accept-retry",
        });
        root.querySelector("#invitation-accept-retry")?.addEventListener("click", () => {
          void renderInvitationAccept(root, ctx, route);
        });
      });
  });
  root.querySelector("[data-invitation-refuse]")?.addEventListener("click", () => {
    location.hash = "#/studios";
  });
}
