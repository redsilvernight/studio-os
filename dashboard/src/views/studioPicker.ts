/**
 * Fiche N1 — Choix et création de studio (docs/maquettes-atelier/nouveaux.html).
 *
 * États de la fiche : choisir (N studios), créer, vide (aucun studio, aucune
 * invitation), chargement, erreur (nom non autorisé), limite (studios par
 * compte). Écran solitaire : carte centrée, hiérarchie et libellés repris de
 * la maquette ; composants du design system uniquement (ds-card, ds-list,
 * dsField, dsSkeleton, ds-banner), aucun style inline.
 *
 * Le rôle et le plan sont toujours écrits en toutes lettres à côté du nom
 * (décision de maquette N1). « Ouvrir » fait du studio choisi le studio actif
 * (studioContext) puis retourne à l'accueil.
 */
import { describeError, esc } from "../ui";
import { ApiError } from "../api";
import { dsErrorState, dsField, dsNotify, dsSkeleton } from "../ds/ds";
import { dsActorAvatar, dsIcon } from "../ds/lot1";
import { createStudio, listStudios, type StudioSummary } from "../studioLifecycleApi";
import {
  studioPlanLabel,
  studioRoleLabel,
  studioSlugify,
  validateStudioName,
} from "../studioLifecycleFormat";
import { setActiveStudioId } from "../studioContext";
import "./studioLifecycle.css";

export interface StudioPickerContext {
  baseUrl: string;
  authed: boolean;
}

/** `used`/`total` absents = le serveur ne les a pas fournis : texte sans chiffres. */
export interface StudioLimitInfo {
  used?: number;
  total?: number;
  planLabel: string;
}

export const STUDIO_PICKER_RETRY_ID = "studio-picker-retry";

function soloCard(inner: string): string {
  return `<div class="studio-solo"><section class="ds-card studio-solo-card" aria-label="Studio">${inner}</section></div>`;
}

function studioRowHtml(studio: StudioSummary): string {
  // Un studio suspendu s'ouvre sur son écran dédié (fiche N5) : il n'y a
  // rien à y écrire, et le bandeau y explique la situation.
  const suspended = studio.status === "suspended";
  const href = suspended ? `#/studios/${encodeURIComponent(studio.id)}/suspended` : "#/";
  const state = suspended ? " · Suspendu" : "";
  return (
    `<li class="ds-list-item">${dsActorAvatar(studio.name)}` +
    `<div class="grow"><div class="ds-list-title">${esc(studio.name)}</div>` +
    `<div class="ds-list-sub">${esc(studioRoleLabel(studio.role))} · ${esc(studioPlanLabel(studio.plan))}${esc(state)}</div></div>` +
    `<button type="button" class="ds-btn ds-btn--primary" data-open-studio="${esc(studio.id)}" ` +
    `data-suspended="${suspended ? "true" : "false"}" aria-label="Ouvrir ${esc(studio.name)}">Ouvrir</button></li>`
  );
}

/**
 * État « Choisir · N studios » : liste + création. « Voir mes invitations (n) »
 * n'apparaît que si le compteur est connu et non nul : l'API n'expose pas les
 * invitations reçues par le compte (elles arrivent par lien e-mail).
 */
export function studioChoiceHtml(studios: StudioSummary[], pendingInvitations?: number): string {
  const rows = studios.map(studioRowHtml).join("");
  const invitations =
    pendingInvitations === undefined || pendingInvitations <= 0
      ? ""
      : `<a class="ds-btn ds-btn--ghost" href="#/studios/invitations">Voir mes invitations (${esc(String(pendingInvitations))})</a>`;
  return soloCard(
    `<h1>Choisissez un studio</h1>` +
      `<p class="ds-list-sub">Vous appartenez à ${esc(String(studios.length))} studios.</p>` +
      `<ul class="ds-list studio-rows" aria-label="Vos studios">${rows}</ul>` +
      `<div class="studio-actions"><button type="button" class="ds-btn" data-studio-create>＋ Créer un studio</button>${invitations}</div>`,
  );
}

export function limitTitle(limit: StudioLimitInfo): string {
  return limit.used !== undefined && limit.total !== undefined
    ? `Limite atteinte : ${limit.used} studios sur ${limit.total} avec le plan ${limit.planLabel}`
    : `Limite de studios atteinte avec le plan ${limit.planLabel}`;
}

function limitBannerHtml(limit: StudioLimitInfo): string {
  return (
    `<div class="ds-banner ds-banner--warning" role="status">${dsIcon("alert-triangle", 20)}` +
    `<div class="ds-banner-body"><strong>${esc(limitTitle(limit))}</strong>` +
    `<span>Rejoindre un studio n'est jamais limité. Pour en créer un de plus, passez à Pro ou archivez un studio inutilisé.</span></div>` +
    `<div class="studio-banner-actions"><button type="button" class="ds-btn ds-btn--primary" data-studio-limit-subscribe>Voir l'abonnement</button>` +
    `<button type="button" class="ds-btn" data-studio-limit-archive>Archiver un studio</button></div></div>`
  );
}

/**
 * État « Créer » (aussi « Erreur » et « Limite » de la fiche) : nom, rôle
 * figé « Propriétaire », aperçu du slug, plan initial free. Avec `limit`, la
 * création est désactivée et le bandeau explique comment libérer de la place.
 */
export function studioCreateFormHtml(
  options: { initialName?: string; nameError?: string | null; limit?: StudioLimitInfo | null } = {},
): string {
  const initialName = options.initialName ?? "";
  const limit = options.limit ?? null;
  const nameField = dsField(
    "studio-name",
    "Nom du studio",
    `<input class="ds-input" id="FIELD" name="name" type="text" required maxlength="80" autocomplete="off" placeholder="Nom du studio" value="${esc(initialName)}">`,
    "",
    options.nameError ?? "",
  );
  const roleField = dsField(
    "studio-role",
    "Votre rôle",
    `<input class="ds-input" id="FIELD" name="role_display" type="text" value="Propriétaire" readonly>`,
    "Vous pourrez transférer la propriété plus tard.",
  );
  const slug = studioSlugify(initialName);
  const actions =
    limit !== null
      ? `<div class="studio-actions"><button type="submit" class="ds-btn ds-btn--primary" data-studio-submit disabled aria-disabled="true">Créer le studio</button></div>`
      : `<div class="studio-actions"><button type="submit" class="ds-btn ds-btn--primary" data-studio-submit>Créer le studio</button>` +
        `<button type="button" class="ds-btn ds-btn--ghost" data-studio-cancel>Annuler</button></div>`;
  return soloCard(
    `<h1>Créer un studio</h1>` +
      `<p class="ds-list-sub">Un studio réunit votre équipe, ses projets et ses fichiers. Vous en êtes propriétaire.</p>` +
      (limit !== null ? limitBannerHtml(limit) : "") +
      `<form data-studio-create-form>${nameField}${roleField}` +
      `<p class="ds-list-sub mono studio-tech-line" data-studio-slug-preview>slug: ${esc(slug)} · plan initial: free</p>` +
      `${actions}` +
      `<div data-studio-create-msg class="ds-list-sub" role="status"></div></form>`,
  );
}

/** État « Vide · aucun studio, aucune invitation ». */
export function studioPickerEmptyHtml(): string {
  return soloCard(
    `<div class="ds-empty ds-empty--illustrated" role="status">` +
      `<span class="ds-empty-art" aria-hidden="true">${dsIcon("inbox", 40)}</span>` +
      `<h3>Vous n'avez pas encore de studio</h3>` +
      `<p>Créez le vôtre, ou demandez à quelqu'un de vous inviter dans le sien.</p>` +
      `<div class="studio-actions"><button type="button" class="ds-btn ds-btn--primary" data-studio-create>Créer un studio</button>` +
      `<button type="button" class="ds-btn ds-btn--ghost" data-studio-invitation-link>J'ai reçu un lien d'invitation</button></div></div>`,
  );
}

/** État « Chargement ». */
export function studioPickerLoadingHtml(): string {
  return soloCard(`<h1>Vos studios…</h1>${dsSkeleton(4)}`);
}

/** Erreur de chargement de la liste (gabarit d'erreur standard du DS). */
export function studioPickerErrorHtml(message: string): string {
  return soloCard(
    dsErrorState("Impossible de charger vos studios", message, { label: "Réessayer", id: STUDIO_PICKER_RETRY_ID }),
  );
}

function showCreateForm(root: HTMLElement, ctx: StudioPickerContext, reload: () => Promise<void>, options?: Parameters<typeof studioCreateFormHtml>[0]): void {
  root.innerHTML = studioCreateFormHtml(options);
  wireCreateForm(root, ctx, reload);
}

function wireCreateForm(root: HTMLElement, ctx: StudioPickerContext, reload: () => Promise<void>): void {
  const form = root.querySelector<HTMLFormElement>("[data-studio-create-form]");
  if (form === null) return;
  const nameInput = form.querySelector<HTMLInputElement>('input[name="name"]');
  const preview = form.querySelector<HTMLElement>("[data-studio-slug-preview]");
  const msg = form.querySelector<HTMLElement>("[data-studio-create-msg]");
  nameInput?.addEventListener("input", () => {
    if (preview !== null) preview.textContent = `slug: ${studioSlugify(nameInput?.value ?? "")} · plan initial: free`;
  });
  root.querySelector("[data-studio-cancel]")?.addEventListener("click", () => void reload());
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const name = String(new FormData(form).get("name") ?? "").trim();
    const nameError = validateStudioName(name);
    if (nameError !== null) {
      // Fiche N1 « Erreur » : le champ reprend le nom tapé et l'erreur est
      // annoncée (aria-invalid + role via dsField), focus sur le champ.
      showCreateForm(root, ctx, reload, { initialName: name, nameError });
      root.querySelector<HTMLInputElement>('input[name="name"]')?.focus();
      return;
    }
    const submit = form.querySelector<HTMLButtonElement>("[data-studio-submit]");
    if (submit !== null) submit.disabled = true;
    createStudio(ctx.baseUrl, name)
      .then((studio) => {
        setActiveStudioId(studio.id);
        location.hash = "#/";
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && (error.status === 409 || error.status === 403)) {
          // Limite « studios par compte » : le serveur est la vérité ; les
          // compteurs affichés viennent du détail d'erreur quand il les donne.
          const details = (error.details ?? {}) as Record<string, unknown>;
          const used = typeof details["studios_used"] === "number" ? details["studios_used"] : undefined;
          const total = typeof details["studios_limit"] === "number" ? details["studios_limit"] : undefined;
          showCreateForm(root, ctx, reload, {
            initialName: name,
            limit: { used, total, planLabel: "Gratuit" },
          });
          return;
        }
        if (submit !== null) submit.disabled = false;
        if (msg !== null) msg.textContent = describeError(error);
      });
  });
  // Limite : les deux portes de sortie sont hors de ce lot (N3, archivage).
  root.querySelector("[data-studio-limit-subscribe]")?.addEventListener("click", () => {
    dsNotify("Passer à Pro n'est pas encore disponible depuis cette page.", "info");
  });
  root.querySelector("[data-studio-limit-archive]")?.addEventListener("click", () => {
    dsNotify("L'archivage d'un studio n'est pas encore disponible.", "info");
  });
}

function wireChoice(root: HTMLElement, ctx: StudioPickerContext, reload: () => Promise<void>): void {
  root.querySelectorAll<HTMLButtonElement>("[data-open-studio]").forEach((button) => {
    button.addEventListener("click", () => {
      const studioId = button.dataset["openStudio"] ?? null;
      setActiveStudioId(studioId);
      // Fiche N5 : un studio suspendu s'ouvre sur son écran dédié.
      location.hash =
        button.dataset["suspended"] === "true" && studioId !== null
          ? `#/studios/${encodeURIComponent(studioId)}/suspended`
          : "#/";
    });
  });
  root.querySelectorAll<HTMLElement>("[data-studio-create]").forEach((button) => {
    button.addEventListener("click", () => showCreateForm(root, ctx, reload));
  });
  root.querySelector("[data-studio-invitation-link]")?.addEventListener("click", () => {
    dsNotify("Ouvrez le lien reçu par e-mail dans votre navigateur pour voir l'invitation.", "info");
  });
}

/**
 * Rendu complet de la fiche N1 : chargement → liste/vide/erreur ; le bouton
 * « Créer un studio » bascule sur le formulaire (état « crea » de la fiche),
 * `startOnCreate` ouvre directement le formulaire (deep link #/studios/create).
 */
export async function renderStudioPicker(
  root: HTMLElement,
  ctx: StudioPickerContext,
  startOnCreate = false,
): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = studioPickerErrorHtml("Ouvrez une session pour retrouver vos studios.");
    return;
  }
  const reload = async (): Promise<void> => {
    await renderStudioPicker(root, ctx, false);
  };
  if (startOnCreate) {
    root.innerHTML = studioPickerLoadingHtml();
    showCreateForm(root, ctx, reload);
    return;
  }
  root.innerHTML = studioPickerLoadingHtml();
  try {
    const studios = await listStudios(ctx.baseUrl);
    root.innerHTML = studios.length === 0 ? studioPickerEmptyHtml() : studioChoiceHtml(studios);
  } catch (error) {
    root.innerHTML = studioPickerErrorHtml(describeError(error));
    root.querySelector(`#${STUDIO_PICKER_RETRY_ID}`)?.addEventListener("click", () => void reload());
    return;
  }
  wireChoice(root, ctx, reload);
}
