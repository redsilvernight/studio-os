/**
 * Membres d'un projet (onglet du workspace, A0 / DEC-0100).
 *
 * - Liste : GET /projects/{id}/members. Ajout : PUT .../members/{user_id}
 *   (201 créé, 200 déjà membre — l'accès d'origine est conservé). Retrait :
 *   DELETE → 204, idempotent, confirmation demandée ; les flux temps réel
 *   ouverts par ce membre sur le projet se ferment.
 * - Réservé au rôle admin côté serveur (403 sinon) : un non-admin voit une
 *   note explicite, sans appel voué à l'échec.
 * - Pas d'annuaire d'utilisateurs dans le contrat : on affiche et on ajoute
 *   par identifiant d'utilisateur (UUID). La CLI `studio-admin project grant`
 *   accepte un e-mail.
 */
import type { StudioClient } from "../api";
import { isUuid } from "../creationsApi";
import { dsEmptyState, dsField, dsSectionHeader, focusDsErrorBox } from "../ds/ds";
import { grantMember, listMembers, revokeMember, type ProjectMember } from "../membersApi";
import { describeError, esc, fmtTime, idCell } from "../ui";

export interface MembersContext {
  client: StudioClient;
  projectId: string;
  authed: boolean;
  isAdmin: boolean;
}

export const CONFIRM_REVOKE_MEMBER =
  "Retirer ce membre ? Il perd immédiatement l'accès au projet et ses flux temps réel se ferment.";

function rowsHtml(members: ProjectMember[]): string {
  return members
    .map(
      (m) =>
        `<tr><td><code class="mono">${esc(m.user_id)}</code></td>` +
        `<td>${m.granted_by_user_id ? idCell(m.granted_by_user_id) : `<span class="ds-list-sub">système (migration)</span>`}</td>` +
        `<td>${esc(fmtTime(m.created_at))}</td>` +
        `<td class="actions"><button type="button" class="ds-btn ds-btn--sm" data-revoke="${esc(m.user_id)}" aria-label="Retirer le membre ${esc(m.user_id)}">Retirer</button></td></tr>`,
    )
    .join("");
}

function grantFormHtml(): string {
  return (
    `<form data-grant class="members-form">` +
    dsField(
      "member-user",
      "Identifiant de l'utilisateur",
      `<input class="ds-input" id="FIELD" name="user_id" required placeholder="00000000-0000-0000-0000-000000000000" autocomplete="off" spellcheck="false" />`,
      "UUID de l'utilisateur. Par e-mail : studio-admin project grant.",
    ) +
    `<button type="submit" class="ds-btn ds-btn--primary">Ajouter au projet</button>` +
    `<div data-grant-msg class="ds-list-sub" role="status"></div></form>`
  );
}

function panelHtml(subtitle: string, body: string): string {
  return `<section class="ds-panel" aria-label="Membres"><header><h2>Membres</h2><span class="ds-list-sub">${esc(subtitle)}</span></header><div class="body">${body}</div></section>`;
}

/** Non-admin (ou déconnecté) : note explicite, aucun appel voué au 403. */
export function membersRestrictedHtml(): string {
  return panelHtml(
    "",
    `<p class="ds-list-sub" role="note">La gestion des membres est réservée au rôle admin. Demandez à un administrateur de vous accorder ou retirer l'accès.</p>`,
  );
}

export function membersPanelHtml(members: ProjectMember[]): string {
  const table =
    members.length === 0
      ? dsEmptyState("Aucun membre", "Personne n'a encore accès à ce projet, hormis les administrateurs.")
      : `<div class="ds-table-wrap"><table class="ds-table"><caption class="ds-sr-only">Membres du projet</caption><thead><tr><th scope="col">Utilisateur</th><th scope="col">Accordé par</th><th scope="col">Depuis</th><th scope="col">Actions</th></tr></thead><tbody>${rowsHtml(members)}</tbody></table></div>`;
  return panelHtml(
    `${members.length} membre(s) · les administrateurs accèdent à tous les projets`,
    `${table}<div class="members-grant">${dsSectionHeader("Ajouter un membre")}${grantFormHtml()}</div>` +
      `<div data-msg class="ds-list-sub" role="status"></div>`,
  );
}

export async function renderMembersInto(root: HTMLElement, ctx: MembersContext): Promise<void> {
  if (!ctx.authed || !ctx.isAdmin) {
    root.innerHTML = membersRestrictedHtml();
    return;
  }
  root.innerHTML = panelHtml("", `<div class="ds-list-sub" role="status" aria-busy="true">Chargement…</div>`);
  const reload = async (notice = ""): Promise<void> => {
    await renderMembersInto(root, ctx);
    const node = root.querySelector("[data-msg]");
    if (node !== null) node.textContent = notice;
  };
  try {
    root.innerHTML = membersPanelHtml(await listMembers(ctx.client, ctx.projectId));
    bind(root, ctx, reload);
  } catch (error) {
    root.innerHTML = panelHtml(
      "",
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Membres indisponibles.</strong> ${esc(describeError(error))}</div>`,
    );
  }
}

function setMsg(root: HTMLElement, text: string): void {
  const node = root.querySelector("[data-msg]");
  if (node === null) return;
  node.textContent = text;
  if (text !== "" && node instanceof HTMLElement) focusDsErrorBox(node);
}

function bind(root: HTMLElement, ctx: MembersContext, reload: (notice?: string) => Promise<void>): void {
  root.querySelectorAll<HTMLButtonElement>("[data-revoke]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!window.confirm(CONFIRM_REVOKE_MEMBER)) return;
      button.disabled = true;
      revokeMember(ctx.client, ctx.projectId, button.dataset["revoke"] ?? "")
        .then(() => reload("Membre retiré."))
        .catch((error: unknown) => {
          button.disabled = false;
          setMsg(root, describeError(error));
        });
    });
  });
  const form = root.querySelector<HTMLFormElement>("[data-grant]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const userId = String(new FormData(form).get("user_id") ?? "").trim();
    const msg = form.querySelector<HTMLElement>("[data-grant-msg]");
    const fail = (text: string): void => {
      if (msg === null) return;
      msg.textContent = text;
      focusDsErrorBox(msg);
    };
    if (!isUuid(userId)) {
      fail("Identifiant invalide : un UUID d'utilisateur est attendu.");
      return;
    }
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    if (submit !== null) submit.disabled = true;
    grantMember(ctx.client, ctx.projectId, userId)
      .then(({ created }) => reload(created ? "Membre ajouté." : "Déjà membre : accès inchangé."))
      .catch((error: unknown) => {
        fail(describeError(error));
        if (submit !== null) submit.disabled = false;
      });
  });
}
