/**
 * Membres d'un projet (onglet du workspace, A0 / DEC-0100).
 *
 * - Liste : GET /projects/{id}/members, avec le nom et l'e-mail de chaque
 *   membre. Ajout : recherche dans l'annuaire admin (GET /users, nom ou
 *   e-mail) puis PUT .../members/{user_id} (201 créé, 200 déjà membre —
 *   l'accès d'origine est conservé). Retrait : DELETE → 204, idempotent,
 *   confirmation demandée ; les flux temps réel ouverts par ce membre sur le
 *   projet se ferment.
 * - Réservé au rôle admin côté serveur (403 sinon) : un non-admin voit une
 *   note explicite, sans appel voué à l'échec.
 */
import type { StudioClient } from "../api";
import { dsEmptyState, dsField, dsSectionHeader, focusDsErrorBox } from "../ds/ds";
import {
  grantMember,
  listMembers,
  revokeMember,
  searchUsers,
  type DirectoryUser,
  type ProjectMember,
} from "../membersApi";
import { describeError, esc, fmtTime, idCell } from "../ui";

export interface MembersContext {
  client: StudioClient;
  projectId: string;
  authed: boolean;
  isAdmin: boolean;
  selfId?: string | null;
}

export const CONFIRM_REVOKE_MEMBER =
  "Retirer ce membre ? Il perd immédiatement l'accès au projet et ses flux temps réel se ferment.";

function memberLabel(m: ProjectMember): string {
  return m.user_display_name ?? m.user_email ?? m.user_id;
}

function userCell(name: string | null | undefined, email: string | null | undefined, id: string): string {
  return (
    `<strong>${esc(name ?? "Utilisateur inconnu")}</strong>` +
    `<div class="ds-list-sub">${email ? esc(email) : idCell(id)}</div>`
  );
}

function grantedByCell(grantedBy: string | null | undefined, members: ProjectMember[]): string {
  if (!grantedBy) return `<span class="ds-list-sub">système (migration)</span>`;
  const known = members.find((m) => m.user_id === grantedBy);
  return known !== undefined ? esc(memberLabel(known)) : idCell(grantedBy);
}

function revokeCell(m: ProjectMember, selfId: string | null): string {
  if (m.user_id === selfId) return `<span class="ds-list-sub">Votre compte</span>`;
  return `<button type="button" class="ds-btn ds-btn--sm" data-revoke="${esc(m.user_id)}" aria-label="Retirer ${esc(memberLabel(m))} du projet">Retirer</button>`;
}

function rowsHtml(members: ProjectMember[], selfId: string | null): string {
  return members
    .map(
      (m) =>
        `<tr><td>${userCell(m.user_display_name, m.user_email, m.user_id)}</td>` +
        `<td>${grantedByCell(m.granted_by_user_id, members)}</td>` +
        `<td>${esc(fmtTime(m.created_at))}</td>` +
        `<td class="actions">${revokeCell(m, selfId)}</td></tr>`,
    )
    .join("");
}

function searchFormHtml(): string {
  return (
    `<form data-user-search class="members-form" role="search">` +
    dsField(
      "member-search",
      "Rechercher un utilisateur",
      `<input class="ds-input" id="FIELD" name="q" type="search" maxlength="200" placeholder="Nom ou e-mail" autocomplete="off" spellcheck="false" />`,
      "Laisser vide pour lister les premiers utilisateurs.",
    ) +
    `<button type="submit" class="ds-btn">Rechercher</button>` +
    `<div data-grant-msg class="ds-list-sub" role="status"></div>` +
    `<div data-candidates></div></form>`
  );
}

/** Résultats de recherche : bouton « Ajouter », ou « Déjà membre ». */
export function candidatesHtml(
  users: DirectoryUser[],
  memberIds: ReadonlySet<string>,
  selfId: string | null = null,
): string {
  if (users.length === 0) return `<p class="ds-list-sub">Aucun utilisateur trouvé.</p>`;
  const items = users
    .map((u) => {
      const action = memberIds.has(u.id)
        ? `<span class="ds-list-sub">Déjà membre</span>`
        : u.id === selfId
          ? `<span class="ds-list-sub">Votre compte</span>`
        : `<button type="button" class="ds-btn ds-btn--sm ds-btn--primary" data-grant-user="${esc(u.id)}" aria-label="Ajouter ${esc(u.display_name)} au projet">Ajouter</button>`;
      return `<li class="members-candidate"><div>${userCell(u.display_name, u.email, u.id)}</div>${action}</li>`;
    })
    .join("");
  return `<ul class="ds-list" aria-label="Utilisateurs trouvés">${items}</ul>`;
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

export function membersPanelHtml(members: ProjectMember[], selfId: string | null = null): string {
  const table =
    members.length === 0
      ? dsEmptyState("Aucun membre", "Personne n'a encore accès à ce projet, hormis les administrateurs.")
      : `<div class="ds-table-wrap"><table class="ds-table"><caption class="ds-sr-only">Membres du projet</caption><thead><tr><th scope="col">Utilisateur</th><th scope="col">Accordé par</th><th scope="col">Depuis</th><th scope="col">Actions</th></tr></thead><tbody>${rowsHtml(members, selfId)}</tbody></table></div>`;
  return panelHtml(
    `${members.length} membre(s) · les administrateurs accèdent à tous les projets`,
    `${table}<div class="members-grant">${dsSectionHeader("Ajouter un membre")}${searchFormHtml()}</div>` +
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
    const members = await listMembers(ctx.client, ctx.projectId);
    root.innerHTML = membersPanelHtml(members, ctx.selfId ?? null);
    bind(root, ctx, new Set(members.map((m) => m.user_id)), reload);
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

function bind(
  root: HTMLElement,
  ctx: MembersContext,
  memberIds: ReadonlySet<string>,
  reload: (notice?: string) => Promise<void>,
): void {
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
  const form = root.querySelector<HTMLFormElement>("[data-user-search]");
  if (form === null) return;
  const msg = form.querySelector<HTMLElement>("[data-grant-msg]");
  const results = form.querySelector<HTMLElement>("[data-candidates]");
  const fail = (text: string): void => {
    if (msg === null) return;
    msg.textContent = text;
    focusDsErrorBox(msg);
  };
  const bindCandidates = (): void => {
    results?.querySelectorAll<HTMLButtonElement>("[data-grant-user]").forEach((button) => {
      button.addEventListener("click", () => {
        button.disabled = true;
        grantMember(ctx.client, ctx.projectId, button.dataset["grantUser"] ?? "")
          .then(({ created }) => reload(created ? "Membre ajouté." : "Déjà membre : accès inchangé."))
          .catch((error: unknown) => {
            button.disabled = false;
            fail(describeError(error));
          });
      });
    });
  };
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = String(new FormData(form).get("q") ?? "").trim();
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    if (submit !== null) submit.disabled = true;
    if (msg !== null) msg.textContent = "Recherche…";
    searchUsers(ctx.client, query)
      .then((users) => {
        if (msg !== null) msg.textContent = "";
        if (results !== null) results.innerHTML = candidatesHtml(users, memberIds, ctx.selfId ?? null);
        bindCandidates();
      })
      .catch((error: unknown) => fail(describeError(error)))
      .finally(() => {
        if (submit !== null) submit.disabled = false;
      });
  });
}
