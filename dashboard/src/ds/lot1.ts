/**
 * Design System — composants du lot 1 (R1-composants) : icônes, avatar typé,
 * sélecteur d'entité, état vide illustré, notification persistante,
 * pagination, bascule segmentée. Même contrat que ds.ts : chaînes HTML
 * échappées, aucun style inline, comportements par addEventListener (CSP).
 */
import { esc } from "../ui";

/**
 * Icônes Lucide (ISC, https://lucide.dev) : tracés intégrés pour éviter une
 * dépendance, décoratives (`aria-hidden`) ; le libellé reste porté par le
 * texte voisin ou par l'`aria-label` du bouton.
 */
const ICON_PATHS = {
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  "alert-triangle":
    '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  "chevron-down": '<path d="m6 9 6 6 6-6"/>',
  "chevron-left": '<path d="m15 18-6-6 6-6"/>',
  "chevron-right": '<path d="m9 18 6-6-6-6"/>',
  inbox:
    '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  bot: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
} as const;

export type DsIconName = keyof typeof ICON_PATHS;

export function dsIcon(name: DsIconName, size = 16): string {
  const px = Number.isInteger(size) && size > 0 && size <= 64 ? size : 16;
  return `<svg class="ds-icon" width="${px}" height="${px}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICON_PATHS[name]}</svg>`;
}

function initials(name: string): string {
  return (
    name
      .trim()
      .split(/\s+/)
      .map((part) => part.slice(0, 1))
      .join("")
      .slice(0, 2)
      .toUpperCase() || "?"
  );
}

/** Avatar typé : initiales (humain) ou icône robot (agent IA), nom accessible. */
export function dsActorAvatar(name: string, kind: "human" | "agent" = "human"): string {
  const inner = kind === "agent" ? dsIcon("bot") : esc(initials(name));
  const cls = kind === "agent" ? "ds-avatar ds-avatar--agent" : "ds-avatar";
  const label = kind === "agent" ? `Agent ${name}` : name;
  return `<span class="${cls}" role="img" title="${esc(name)}" aria-label="${esc(label)}">${inner}</span>`;
}

/** État vide illustré : icône, titre, explication, action unique. */
export function dsIllustratedEmpty(
  icon: DsIconName,
  title: string,
  message: string,
  action?: { label: string; href: string },
): string {
  const link =
    action === undefined ? "" : `<a class="ds-btn ds-btn--primary" href="${esc(action.href)}">${esc(action.label)}</a>`;
  return `<div class="ds-empty ds-empty--illustrated" role="status"><span class="ds-empty-art" aria-hidden="true">${dsIcon(icon, 40)}</span><h3>${esc(title)}</h3><p>${esc(message)}</p>${link}</div>`;
}

export interface DsEntityOption {
  id: string;
  label: string;
  /** Texte secondaire (rôle, type…). */
  meta?: string;
  kind?: "human" | "agent";
}

/**
 * Sélecteur d'entité (studio, projet, agent) : bouton + liste d'options.
 * Ouverture Entrée/Espace/Flèche bas ; flèches, Home, End parcourent ;
 * Entrée/Espace choisit ; Échap ferme et rend le focus. À câbler avec
 * `initDsEntitySelect`.
 */
export function dsEntitySelect(id: string, label: string, options: DsEntityOption[], selectedId: string): string {
  const selected = options.find((option) => option.id === selectedId) ?? options[0];
  const items = options
    .map((option) => {
      const isSelected = option.id === selected?.id;
      const meta = option.meta === undefined ? "" : `<span class="ds-entity-meta">${esc(option.meta)}</span>`;
      return `<li role="option" class="ds-entity-option" id="${esc(id)}-opt-${esc(option.id)}" data-value="${esc(option.id)}" tabindex="-1" aria-selected="${isSelected ? "true" : "false"}">${dsActorAvatar(option.label, option.kind)}<span class="ds-entity-text"><span>${esc(option.label)}</span>${meta}</span>${isSelected ? dsIcon("check") : ""}</li>`;
    })
    .join("");
  const current = selected === undefined ? "" : esc(selected.label);
  return `<div class="ds-entity" data-ds-entity="${esc(id)}"><span class="ds-entity-label" id="${esc(id)}-label">${esc(label)}</span><button type="button" class="ds-entity-trigger" id="${esc(id)}-trigger" aria-haspopup="listbox" aria-expanded="false" aria-labelledby="${esc(id)}-label ${esc(id)}-trigger"><span class="ds-entity-current">${current}</span>${dsIcon("chevron-down")}</button><ul class="ds-entity-list" role="listbox" id="${esc(id)}-list" aria-labelledby="${esc(id)}-label" hidden>${items}</ul></div>`;
}

export function initDsEntitySelect(root: ParentNode, id: string, onChange?: (value: string) => void): void {
  const host = root.querySelector<HTMLElement>(`[data-ds-entity="${CSS.escape(id)}"]`);
  const trigger = host?.querySelector<HTMLButtonElement>(".ds-entity-trigger");
  const list = host?.querySelector<HTMLElement>(".ds-entity-list");
  if (host == null || trigger == null || list == null) return;
  const options = [...list.querySelectorAll<HTMLElement>('[role="option"]')];
  if (options.length === 0) return;
  let active = 0;

  const focusOption = (index: number): void => {
    active = (index + options.length) % options.length;
    options[active]?.focus();
  };
  const close = (returnFocus: boolean): void => {
    list.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    if (returnFocus) trigger.focus();
  };
  const open = (): void => {
    list.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    focusOption(Math.max(0, options.findIndex((option) => option.getAttribute("aria-selected") === "true")));
  };
  const choose = (option: HTMLElement): void => {
    for (const other of options) {
      other.setAttribute("aria-selected", other === option ? "true" : "false");
      other.querySelector(":scope > .ds-icon")?.remove();
    }
    option.insertAdjacentHTML("beforeend", dsIcon("check"));
    const text = option.querySelector(".ds-entity-text > span");
    const current = trigger.querySelector(".ds-entity-current");
    if (text !== null && current !== null) current.textContent = text.textContent;
    close(true);
    onChange?.(option.dataset.value ?? "");
  };

  trigger.addEventListener("click", () => (list.hidden ? open() : close(false)));
  trigger.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (list.hidden) open();
    }
  });
  list.addEventListener("keydown", (event) => {
    const actions: Record<string, () => void> = {
      ArrowDown: () => focusOption(active + 1),
      ArrowUp: () => focusOption(active - 1),
      Home: () => focusOption(0),
      End: () => focusOption(options.length - 1),
      Escape: () => close(true),
      Tab: () => close(false),
      Enter: () => options[active] !== undefined && choose(options[active] as HTMLElement),
      " ": () => options[active] !== undefined && choose(options[active] as HTMLElement),
    };
    const action = actions[event.key];
    if (action === undefined) return;
    if (event.key !== "Tab") event.preventDefault();
    action();
  });
  for (const [index, option] of options.entries()) {
    option.addEventListener("click", () => {
      active = index;
      choose(option);
    });
  }
  document.addEventListener("click", (event) => {
    if (!list.hidden && !host.contains(event.target as Node)) close(false);
  });
}

export type DsNoticeTone = "info" | "success" | "warning" | "danger";

const NOTICE_ICON: Record<DsNoticeTone, DsIconName> = {
  info: "info",
  success: "check",
  warning: "alert-triangle",
  danger: "alert-triangle",
};

/**
 * Notification persistante : reste affichée tant que la cause demeure
 * (limite de plan, studio suspendu…). Danger = `alert`, le reste `status`.
 * `dismissible` ajoute un bouton de fermeture (à câbler avec
 * `initDsPersistentNotice`). L'icône accompagne toujours le texte.
 */
export function dsPersistentNotice(
  id: string,
  tone: DsNoticeTone,
  title: string,
  message: string,
  options: { action?: { label: string; href: string }; dismissible?: boolean } = {},
): string {
  const role = tone === "danger" ? "alert" : "status";
  const action =
    options.action === undefined
      ? ""
      : `<a class="ds-btn ds-btn--sm" href="${esc(options.action.href)}">${esc(options.action.label)}</a>`;
  const close =
    options.dismissible === true
      ? `<button type="button" class="ds-icon-btn" data-ds-dismiss="${esc(id)}" aria-label="Masquer : ${esc(title)}">${dsIcon("x")}</button>`
      : "";
  return `<div class="ds-banner ds-banner--${tone}" id="${esc(id)}" role="${role}">${dsIcon(NOTICE_ICON[tone], 20)}<div class="ds-banner-body"><strong>${esc(title)}</strong><span>${esc(message)}</span></div>${action}${close}</div>`;
}

export function initDsPersistentNotice(root: ParentNode, id: string): void {
  root.querySelector(`[data-ds-dismiss="${CSS.escape(id)}"]`)?.addEventListener("click", () => {
    root.querySelector(`#${CSS.escape(id)}`)?.remove();
  });
}

/**
 * Pagination : page courante `aria-current="page"`, fenêtre autour d'elle,
 * précédent/suivant désactivés aux bords (pas de lien mort).
 */
export function dsPagination(current: number, total: number, hrefFor: (page: number) => string): string {
  const last = Math.max(1, Math.trunc(total));
  const page = Math.min(Math.max(1, Math.trunc(current)), last);
  const shown = [...new Set([1, last, page - 1, page, page + 1])].filter((n) => n >= 1 && n <= last).sort((a, b) => a - b);
  const edge = (target: number, icon: DsIconName, label: string, disabled: boolean): string =>
    disabled
      ? `<li><span class="ds-page-link" role="link" aria-disabled="true" aria-label="${label}">${dsIcon(icon)}</span></li>`
      : `<li><a class="ds-page-link" href="${esc(hrefFor(target))}" aria-label="${label}">${dsIcon(icon)}</a></li>`;
  const numbers = shown
    .map((value, index) => {
      const gap = index > 0 && value - (shown[index - 1] ?? 0) > 1 ? `<li class="ds-page-gap" aria-hidden="true">…</li>` : "";
      const here = value === page ? ' aria-current="page"' : "";
      return `${gap}<li><a class="ds-page-link" href="${esc(hrefFor(value))}" aria-label="Page ${value}"${here}>${value}</a></li>`;
    })
    .join("");
  return `<nav class="ds-pagination" aria-label="Pagination"><ul>${edge(page - 1, "chevron-left", "Page précédente", page <= 1)}${numbers}${edge(page + 1, "chevron-right", "Page suivante", page >= last)}</ul></nav>`;
}

/** Bascule segmentée : `radiogroup` natif (flèches, un seul tabstop). */
export function dsSegmented(
  name: string,
  legend: string,
  options: { value: string; label: string }[],
  selected: string,
): string {
  const inputs = options
    .map(
      (option) =>
        `<label class="ds-seg-item"><input type="radio" name="${esc(name)}" value="${esc(option.value)}"${option.value === selected ? " checked" : ""}><span>${esc(option.label)}</span></label>`,
    )
    .join("");
  return `<fieldset class="ds-seg"><legend class="ds-sr-only">${esc(legend)}</legend>${inputs}</fieldset>`;
}
