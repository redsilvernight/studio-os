/**
 * Comptes (A3, TECH/02 « Administration des comptes ») — réservé au rôle admin.
 *
 * - Annuaire : GET /users (nom ou e-mail), avec l'état dérivé de chaque
 *   compte (en attente de vérification, actif, désactivé).
 * - Actions : désactiver (confirmation : sessions révoquées, machines
 *   bloquées), réactiver, révoquer les sessions (confirmation). Jamais sur son
 *   propre compte : le serveur refuserait (403), l'écran ne le propose pas.
 * - Accès : GET /users/{id}/memberships liste les projets accessibles ; ils se
 *   gèrent dans l'onglet Membres de chaque projet.
 * - Non-admin : note explicite, aucun appel voué au 403.
 */
import type { StudioClient } from "../api";
import { applyAccountAction, listUserMemberships, type AccountAction } from "../accountsApi";
import { dsBadge, dsEmptyState, dsField, dsPageHeader, focusDsErrorBox, type DsTone } from "../ds/ds";
import { fetchIdentity } from "../identityApi";
import { searchUsers, type DirectoryUser, type ProjectMember } from "../membersApi";
import { describeError, esc, idCell } from "../ui";

export interface AccountsContext {
  client: StudioClient;
  authed: boolean;
}

export const CONFIRM_DISABLE_ACCOUNT =
  "Désactiver ce compte ? Ses sessions sont révoquées immédiatement et ses machines sont refusées jusqu'à réactivation.";
export const CONFIRM_REVOKE_SESSIONS =
  "Révoquer toutes les sessions de ce compte ? Il devra se reconnecter ; ses machines ne sont pas touchées.";

const STATUS_LABEL: Record<string, { label: string; tone: DsTone }> = {
  active: { label: "Actif", tone: "success" },
  pending: { label: "En attente de vérification", tone: "warning" },
  disabled: { label: "Désactivé", tone: "danger" },
};

const ROLE_LABEL: Record<string, string> = {
  admin: "Administrateur",
  developer: "Développeur",
  agent: "Agent",
  readonly: "Lecture seule",
};

function statusBadge(status: string | undefined): string {
  const entry = STATUS_LABEL[status ?? "active"] ?? { label: status ?? "", tone: "neutral" };
  return dsBadge(entry.label, entry.tone);
}

function actionsHtml(user: DirectoryUser, selfId: string | null): string {
  if (user.id === selfId) return `<span class="ds-list-sub">Votre compte</span>`;
  const name = esc(user.display_name);
  const toggle =
    user.status === "disabled"
      ? `<button type="button" class="ds-btn ds-btn--sm" data-account-action="enable" data-user="${esc(user.id)}" aria-label="Réactiver ${name}">Réactiver</button>`
      : `<button type="button" class="ds-btn ds-btn--sm ds-btn--danger" data-account-action="disable" data-user="${esc(user.id)}" aria-label="Désactiver ${name}">Désactiver</button>`;
  return (
    toggle +
    ` <button type="button" class="ds-btn ds-btn--sm" data-account-action="revoke-sessions" data-user="${esc(user.id)}" aria-label="Révoquer les sessions de ${name}">Révoquer les sessions</button>` +
    ` <button type="button" class="ds-btn ds-btn--sm" data-access="${esc(user.id)}" aria-expanded="false" aria-label="Voir les accès de ${name}">Accès</button>`
  );
}

export function accountsTableHtml(users: DirectoryUser[], selfId: string | null): string {
  if (users.length === 0) return dsEmptyState("Aucun compte trouvé", "Modifiez la recherche pour élargir les résultats.");
  const rows = users
    .map(
      (u) =>
        `<tr data-account-row="${esc(u.id)}"><td><strong>${esc(u.display_name)}</strong><div class="ds-list-sub">${esc(u.email)}</div></td>` +
        `<td>${esc(ROLE_LABEL[u.role] ?? u.role)}</td><td>${statusBadge(u.status)}</td>` +
        `<td class="actions">${actionsHtml(u, selfId)}</td></tr>` +
        `<tr hidden data-access-row="${esc(u.id)}"><td colspan="4"><div data-access-body="${esc(u.id)}"></div></td></tr>`,
    )
    .join("");
  return `<div class="ds-table-wrap"><table class="ds-table"><caption class="ds-sr-only">Comptes</caption><thead><tr><th scope="col">Compte</th><th scope="col">Rôle</th><th scope="col">État</th><th scope="col">Actions</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

export function membershipsHtml(memberships: ProjectMember[]): string {
  if (memberships.length === 0) {
    return `<p class="ds-list-sub">Aucun projet accessible. Un compte actif sans accès se connecte et voit des listes vides ; donnez-lui accès depuis l'onglet Membres d'un projet.</p>`;
  }
  const items = memberships
    .map((m) => `<li><a href="#/projects/${esc(m.project_id)}/members">${idCell(m.project_id)}</a></li>`)
    .join("");
  return `<ul class="ds-list" aria-label="Projets accessibles">${items}</ul>`;
}

function pageHtml(body: string): string {
  return (
    dsPageHeader("Comptes", "État des comptes, sessions et accès aux projets. Les administrateurs accèdent à tous les projets.") +
    body
  );
}

export function accountsRestrictedHtml(): string {
  return pageHtml(
    `<p class="ds-list-sub" role="note">La gestion des comptes est réservée au rôle admin. Demandez à un administrateur de désactiver, réactiver un compte ou de modifier ses accès.</p>`,
  );
}

function searchFormHtml(query: string): string {
  return (
    `<form data-account-search class="members-form" role="search">` +
    dsField(
      "account-search",
      "Rechercher un compte",
      `<input class="ds-input" id="FIELD" name="q" type="search" maxlength="200" placeholder="Nom ou e-mail" autocomplete="off" spellcheck="false" value="${esc(query)}" />`,
      "Laisser vide pour lister les premiers comptes.",
    ) +
    `<button type="submit" class="ds-btn">Rechercher</button></form>`
  );
}

const ACTION_DONE: Record<AccountAction, string> = {
  disable: "Compte désactivé : sessions révoquées, machines bloquées.",
  enable: "Compte réactivé : ses machines fonctionnent de nouveau ; il doit se reconnecter.",
  "revoke-sessions": "Sessions révoquées : le compte devra se reconnecter.",
};

export async function renderAccounts(root: HTMLElement, ctx: AccountsContext, query = "", notice = ""): Promise<void> {
  const identity = ctx.authed ? await fetchIdentity(ctx.client) : null;
  if (identity === null || identity.role !== "admin") {
    root.innerHTML = accountsRestrictedHtml();
    return;
  }
  try {
    const users = await searchUsers(ctx.client, query, 100);
    root.innerHTML = pageHtml(
      searchFormHtml(query) +
        `<div data-msg class="ds-list-sub" role="status">${esc(notice)}</div>` +
        accountsTableHtml(users, identity.user_id),
    );
    bind(root, ctx, query);
  } catch (error) {
    root.innerHTML = pageHtml(
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Comptes indisponibles.</strong> ${esc(describeError(error))}</div>`,
    );
  }
}

function bind(root: HTMLElement, ctx: AccountsContext, query: string): void {
  const msg = root.querySelector<HTMLElement>("[data-msg]");
  const fail = (text: string): void => {
    if (msg === null) return;
    msg.textContent = text;
    focusDsErrorBox(msg);
  };
  root.querySelector<HTMLFormElement>("[data-account-search]")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    void renderAccounts(root, ctx, String(new FormData(form).get("q") ?? "").trim());
  });
  root.querySelectorAll<HTMLButtonElement>("[data-account-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset["accountAction"] as AccountAction;
      if (action === "disable" && !window.confirm(CONFIRM_DISABLE_ACCOUNT)) return;
      if (action === "revoke-sessions" && !window.confirm(CONFIRM_REVOKE_SESSIONS)) return;
      button.disabled = true;
      applyAccountAction(ctx.client, button.dataset["user"] ?? "", action)
        .then(() => renderAccounts(root, ctx, query, ACTION_DONE[action]))
        .catch((error: unknown) => {
          button.disabled = false;
          fail(describeError(error));
        });
    });
  });
  root.querySelectorAll<HTMLButtonElement>("[data-access]").forEach((button) => {
    button.addEventListener("click", () => {
      const userId = button.dataset["access"] ?? "";
      const row = root.querySelector<HTMLElement>(`[data-access-row="${CSS.escape(userId)}"]`);
      const body = root.querySelector<HTMLElement>(`[data-access-body="${CSS.escape(userId)}"]`);
      if (row === null || body === null) return;
      const open = row.hidden;
      row.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
      if (!open) return;
      body.textContent = "Chargement…";
      listUserMemberships(ctx.client, userId)
        .then((memberships) => {
          body.innerHTML = membershipsHtml(memberships);
        })
        .catch((error: unknown) => {
          body.textContent = describeError(error);
        });
    });
  });
}
