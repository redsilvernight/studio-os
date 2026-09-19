/**
 * StudiOS Design System — helpers (UI-1, DEC-0078).
 *
 * Chaînes HTML échappées par défaut, aucun style inline, aucune logique
 * métier : ces primitives seront la base des pages UI-2 → UI-16.
 * Comportements DOM (onglets, modale, tiroir, toasts) via
 * addEventListener uniquement (contrainte CSP, DEC-0061).
 */
import { esc } from "../ui";

export type DsTone = "neutral" | "success" | "warning" | "danger" | "ai" | "info";

export type DsStatusState = "success" | "warning" | "danger" | "ai" | "info" | "idle";

const TONE_CLASS: Record<DsTone, string> = {
  neutral: "",
  success: "ds-badge--success",
  warning: "ds-badge--warning",
  danger: "ds-badge--danger",
  ai: "ds-badge--ai",
  info: "ds-badge--info",
};

/** Pastille + libellé (la couleur n'est jamais le seul signal). */
export function dsBadge(label: string, tone: DsTone = "neutral"): string {
  const modifier = TONE_CLASS[tone];
  const cls = modifier === "" ? "ds-badge" : `ds-badge ${modifier}`;
  return `<span class="${cls}">${esc(label)}</span>`;
}

/** Statut : point coloré + libellé explicite obligatoire. */
export function dsStatus(state: DsStatusState, label: string): string {
  const modifier = state === "idle" ? "" : ` ds-status--${state}`;
  return `<span class="ds-status${modifier}"><span class="dot" aria-hidden="true"></span>${esc(label)}</span>`;
}

export interface DsPageAction {
  label: string;
  href?: string;
  id?: string;
  variant?: "primary" | "secondary" | "ghost" | "danger";
}

/** En-tête de page : un titre, une description courte, des actions rares. */
export function dsPageHeader(title: string, description = "", actions: DsPageAction[] = []): string {
  const buttons = actions
    .map((action) => {
      const variant = action.variant ?? "secondary";
      const cls = variant === "secondary" ? "ds-btn" : `ds-btn ds-btn--${variant}`;
      const id = action.id !== undefined ? ` id="${esc(action.id)}"` : "";
      if (action.href !== undefined) {
        return `<a class="${cls}" href="${esc(action.href)}"${id}>${esc(action.label)}</a>`;
      }
      return `<button class="${cls}" type="button"${id}>${esc(action.label)}</button>`;
    })
    .join("");
  const desc = description === "" ? "" : `<p>${esc(description)}</p>`;
  const acts = actions.length === 0 ? "" : `<div class="ds-page-actions">${buttons}</div>`;
  return `<div class="ds-page-header"><div class="grow"><h1>${esc(title)}</h1>${desc}</div>${acts}</div>`;
}

/** En-tête de section avec lien « Voir tout » optionnel. */
export function dsSectionHeader(title: string, seeAll?: { label: string; href: string }): string {
  const link =
    seeAll === undefined ? "" : `<a href="${esc(seeAll.href)}">${esc(seeAll.label)}</a>`;
  return `<div class="ds-section-header"><h2>${esc(title)}</h2>${link}</div>`;
}

/** Indicateur : un chiffre fort + un libellé, jamais de micro-KPI. */
export function dsMetric(label: string, value: string | number): string {
  return `<div class="ds-metric"><span class="ds-metric-value">${esc(String(value))}</span><span class="ds-metric-label">${esc(label)}</span></div>`;
}

/** État vide : explication + action. */
export function dsEmptyState(title: string, message: string, action?: { label: string; href: string }): string {
  const link =
    action === undefined
      ? ""
      : `<a class="ds-btn ds-btn--primary" href="${esc(action.href)}">${esc(action.label)}</a>`;
  return `<div class="ds-empty" role="status"><span class="ds-empty-icon" aria-hidden="true">○</span><h3>${esc(title)}</h3><p>${esc(message)}</p>${link}</div>`;
}

/** Squelette de chargement : annonce unique, barres décoratives. */
export function dsSkeleton(lines = 3): string {
  const bars = [`<div class="ds-skeleton-bar ds-skeleton-bar--title"></div>`];
  for (let i = 0; i < lines; i += 1) {
    bars.push(`<div class="ds-skeleton-bar${i === lines - 1 ? " ds-skeleton-bar--short" : ""}"></div>`);
  }
  return `<div class="ds-skeleton" role="status"><span class="ds-sr-only">Chargement en cours…</span><div aria-hidden="true">${bars.join("")}</div></div>`;
}

/** Champ + label + aide/erreur associés (aria-describedby). */
export function dsField(inputId: string, label: string, control: string, hint = "", error = ""): string {
  const describedBy: string[] = [];
  let hintHtml = "";
  let errorHtml = "";
  if (hint !== "") {
    describedBy.push(`${inputId}-hint`);
    hintHtml = `<span class="ds-field-hint" id="${esc(inputId)}-hint">${esc(hint)}</span>`;
  }
  if (error !== "") {
    describedBy.push(`${inputId}-error`);
    errorHtml = `<span class="ds-field-error" id="${esc(inputId)}-error">${esc(error)}</span>`;
  }
  const described = describedBy.length === 0 ? "" : ` aria-describedby="${esc(describedBy.join(" "))}"`;
  const invalid = error === "" ? "" : ` aria-invalid="true"`;
  const accessibleControl = control.replace('id="FIELD"', `id="${esc(inputId)}"${described}${invalid}`);
  return `<label class="ds-field" for="${esc(inputId)}"><span>${esc(label)}</span>${accessibleControl}${hintHtml}${errorHtml}</label>`;
}

/** Progression : élément natif + libellé texte (pas de % couleur seule). */
export function dsProgress(value: number, max: number, label: string): string {
  const safeMax = max <= 0 ? 100 : max;
  const safeValue = Math.min(Math.max(value, 0), safeMax);
  return `<div class="ds-progress"><progress value="${safeValue}" max="${safeMax}">${esc(label)}</progress><span class="ds-progress-label">${esc(label)}</span></div>`;
}

/** Initiales d'un nom (avatar), jamais d'image sans alternative. */
function avatarInitials(name: string): string {
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

/** Avatar : initiales + nom accessible (image informative). */
export function dsAvatar(name: string): string {
  return `<span class="ds-avatar" role="img" title="${esc(name)}" aria-label="${esc(name)}">${esc(avatarInitials(name))}</span>`;
}

/** Badge agent IA : pastille violette + avatar décoratif + nom (annoncé une fois). */
export function dsAgentBadge(name: string): string {
  return `<span class="ds-agent"><span class="ds-avatar" aria-hidden="true">${esc(avatarInitials(name))}</span><span>${dsBadge(`IA · ${name}`, "ai")}</span></span>`;
}

export interface DsTab {
  id: string;
  label: string;
  panel: string;
}

/**
 * Onglets accessibles : tablist/tab/tabpanel, sélection au clic et au
 * clavier (flèches gauche/droite, Début/Fin). Activer avec initDsTabs().
 * `label` nomme le tablist en français ; à défaut, l'identifiant technique
 * est conservé (compatibilité, jamais un nom vide).
 */
export function dsTabsHtml(groupId: string, tabs: DsTab[], activeId?: string, label?: string): string {
  const current = tabs.some((tab) => tab.id === activeId) ? (activeId as string) : tabs[0]?.id;
  const buttons = tabs
    .map(
      (tab) =>
        `<button class="ds-tab" type="button" role="tab" id="${esc(groupId)}-tab-${esc(tab.id)}" aria-controls="${esc(groupId)}-panel-${esc(tab.id)}" aria-selected="${tab.id === current ? "true" : "false"}" tabindex="${tab.id === current ? "0" : "-1"}" data-ds-tab="${esc(tab.id)}">${esc(tab.label)}</button>`,
    )
    .join("");
  const panels = tabs
    .map(
      (tab) =>
        `<div class="ds-tabpanel" role="tabpanel" id="${esc(groupId)}-panel-${esc(tab.id)}" aria-labelledby="${esc(groupId)}-tab-${esc(tab.id)}"${tab.id === current ? "" : " hidden"}>${tab.panel}</div>`,
    )
    .join("");
  return `<div data-ds-tabs="${esc(groupId)}"><div class="ds-tabs" role="tablist" aria-label="${esc(label ?? groupId)}">${buttons}</div>${panels}</div>`;
}

/** Câble le clavier et le clic d'un groupe d'onglets rendu par dsTabsHtml. */
export function initDsTabs(root: ParentNode, groupId: string): void {
  const group = root.querySelector(`[data-ds-tabs="${CSS.escape(groupId)}"]`);
  if (group === null) return;
  const tabs = [...group.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  if (tabs.length === 0) return;

  const select = (tab: HTMLButtonElement, focus: boolean): void => {
    for (const other of tabs) {
      const selected = other === tab;
      other.setAttribute("aria-selected", selected ? "true" : "false");
      other.tabIndex = selected ? 0 : -1;
      const panel = group.querySelector(`#${CSS.escape(other.getAttribute("aria-controls") ?? "")}`);
      if (panel !== null) {
        if (selected) panel.removeAttribute("hidden");
        else panel.setAttribute("hidden", "");
      }
    }
    if (focus) tab.focus();
  };

  for (const [index, tab] of tabs.entries()) {
    tab.addEventListener("click", () => select(tab, false));
    tab.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const next =
          event.key === "ArrowRight"
            ? tabs[(index + 1) % tabs.length]
            : tabs[(index - 1 + tabs.length) % tabs.length];
        if (next !== undefined) select(next, true);
        return;
      }
      if (event.key === "Home") {
        event.preventDefault();
        const first = tabs[0];
        if (first !== undefined) select(first, true);
        return;
      }
      if (event.key === "End") {
        event.preventDefault();
        const last = tabs[tabs.length - 1];
        if (last !== undefined) select(last, true);
      }
    });
  }
}

export interface DsDialog {
  id: string;
  title: string;
  body: string;
  actions?: DsPageAction[];
}

/** Modale : role=dialog + aria-modal, fermée par défaut (hidden). */
export function dsModalHtml(dialog: DsDialog): string {
  const actions = (dialog.actions ?? [])
    .map((action) => {
      const variant = action.variant ?? "secondary";
      const cls = variant === "secondary" ? "ds-btn" : `ds-btn ds-btn--${variant}`;
      const id = action.id !== undefined ? ` id="${esc(action.id)}"` : "";
      return `<button class="${cls}" type="button"${id} data-ds-close>${esc(action.label)}</button>`;
    })
    .join("");
  return `<div class="ds-overlay" id="${esc(dialog.id)}" hidden><div class="ds-modal" role="dialog" aria-modal="true" aria-labelledby="${esc(dialog.id)}-title"><h2 id="${esc(dialog.id)}-title">${esc(dialog.title)}</h2><div>${dialog.body}</div><div class="ds-dialog-actions">${actions}</div></div></div>`;
}

/** Tiroir : même contrat que la modale, ancré à droite. */
export function dsDrawerHtml(dialog: DsDialog): string {
  const actions = (dialog.actions ?? [])
    .map((action) => {
      const variant = action.variant ?? "secondary";
      const cls = variant === "secondary" ? "ds-btn" : `ds-btn ds-btn--${variant}`;
      const id = action.id !== undefined ? ` id="${esc(action.id)}"` : "";
      return `<button class="${cls}" type="button"${id} data-ds-close>${esc(action.label)}</button>`;
    })
    .join("");
  return `<div class="ds-overlay ds-drawer-overlay" id="${esc(dialog.id)}" hidden><div class="ds-drawer" role="dialog" aria-modal="true" aria-labelledby="${esc(dialog.id)}-title"><h2 id="${esc(dialog.id)}-title">${esc(dialog.title)}</h2><div>${dialog.body}</div><div class="ds-dialog-actions">${actions}</div></div></div>`;
}

let dsLastTrigger: HTMLElement | null = null;

const DS_FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

/** Éléments atteignables au clavier dans un dialogue ouvert. */
function dsDialogFocusables(overlay: Element): HTMLElement[] {
  return [...overlay.querySelectorAll<HTMLElement>(DS_FOCUSABLE)].filter(
    (node) => node.closest("[hidden]") === null,
  );
}

/**
 * Câble un dialogue UNE fois (marqueur data-ds-wired) : Échap ferme,
 * Tab/Shift+Tab restent piégés dans le dialogue, les boutons
 * [data-ds-close] ferment. Idempotent entre réouvertures.
 */
function wireDsDialog(root: ParentNode, dialogId: string): void {
  const overlay = root.querySelector(`#${CSS.escape(dialogId)}`);
  if (overlay === null || overlay.hasAttribute("data-ds-wired")) return;
  overlay.setAttribute("data-ds-wired", "true");
  overlay.addEventListener("keydown", (event) => {
    if (!(event instanceof KeyboardEvent)) return;
    if (event.key === "Escape") {
      closeDsDialog(root, dialogId);
      return;
    }
    if (event.key !== "Tab") return;
    const items = dsDialogFocusables(overlay);
    if (items.length === 0) {
      event.preventDefault();
      return;
    }
    const first = items[0] as HTMLElement;
    const last = items[items.length - 1] as HTMLElement;
    const active = overlay.ownerDocument.activeElement;
    if (event.shiftKey && (active === first || !overlay.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  });
  overlay.querySelectorAll("[data-ds-close]").forEach((button) => {
    button.addEventListener("click", () => closeDsDialog(root, dialogId));
  });
}

/** Ouvre un dialogue : mémorise le déclencheur, focus le titre, piège Tab, Échap ferme. */
export function openDsDialog(root: ParentNode, dialogId: string, trigger: HTMLElement | null = null): void {
  const overlay = root.querySelector(`#${CSS.escape(dialogId)}`);
  if (overlay === null) return;
  wireDsDialog(root, dialogId);
  dsLastTrigger = trigger;
  overlay.removeAttribute("hidden");
  const title = overlay.querySelector<HTMLElement>("h2[tabindex], h2");
  if (title !== null) {
    title.setAttribute("tabindex", "-1");
    title.focus();
  }
}

export function closeDsDialog(root: ParentNode, dialogId: string): void {
  const overlay = root.querySelector(`#${CSS.escape(dialogId)}`);
  if (overlay === null) {
    dsLastTrigger = null;
    return;
  }
  overlay.setAttribute("hidden", "");
  const trigger = dsLastTrigger;
  dsLastTrigger = null;
  if (trigger !== null && root.contains(trigger)) {
    trigger.focus();
  }
}

/**
 * Erreur de formulaire : rend le bloc atteignable au clavier puis le
 * focalise (le bloc porte déjà role="alert" : annonce + point de reprise).
 */
export function focusDsErrorBox(box: HTMLElement): void {
  box.setAttribute("tabindex", "-1");
  box.focus();
}

export type DsToastTone = "success" | "warning" | "danger" | "info";

/**
 * Toast : ajouté à la région aria-live du shell (#ds-toast-region),
 * refermable, disparition automatique. Une erreur (danger) est annoncée en
 * alerte et persiste plus longtemps ; jamais d'information critique
 * uniquement en toast (doubler d'une surface persistante).
 */
export function dsNotify(message: string, tone: DsToastTone = "info", timeoutMs?: number): void {
  const region = document.getElementById("ds-toast-region");
  if (region === null) return;
  const toast = document.createElement("div");
  toast.className = `ds-toast ds-toast--${tone}`;
  if (tone === "danger") toast.setAttribute("role", "alert");
  const text = document.createElement("p");
  text.textContent = message;
  const close = document.createElement("button");
  close.className = "ds-icon-btn";
  close.type = "button";
  close.setAttribute("aria-label", "Fermer la notification");
  close.textContent = "×";
  close.addEventListener("click", () => toast.remove());
  toast.append(text, close);
  region.append(toast);
  window.setTimeout(() => toast.remove(), timeoutMs ?? (tone === "danger" ? 12000 : 6000));
}
