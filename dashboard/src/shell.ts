/**
 * AppShell StudiOS (UI-2, refondu en UX V2 P03-shell).
 *
 * Barre latérale adaptative : tiroir sous 900 px, rail d'icônes jusqu'à
 * 1400 px, barre complète au-delà (wireframes P02). Rendu en chaînes HTML
 * (architecture vanilla conservée), comportements montés par main.ts.
 *
 * Navigation = routes existantes uniquement ; cinq destinations
 * quotidiennes, « Administration » (vue d'ensemble + 6 familles) et
 * « Outils experts » repliés en pied, palette « Aller à… »
 * (Ctrl K) sur ces mêmes destinations — pas de recherche globale : aucun
 * backend ne la supporte. Un seul statut de connexion, sous l'avatar (C4).
 */
import type { UiMode } from "./uiMode";
import type { Route } from "./router";
import { THEME_LABELS, THEME_MODES, type ThemeMode } from "./theme";
import { esc } from "./ui";
import { studioRoleLabel, type Studio, type StudioRole } from "./studiosApi";
import brandLogoUrl from "./assets/studio-os-logo.png";

export interface ShellNavItem {
  href: string;
  label: string;
  /** Libellé court du rail d'icônes (défaut : `label`). */
  short?: string;
  icon: string;
  active: boolean;
  /** Pastille de formule (Abonnement) : texte seul, jamais la couleur seule. */
  pill?: string;
}

export interface ShellNavGroup {
  title: string;
  /** Groupe secondaire replié par défaut (ouvert si un de ses liens est actif). */
  collapsible?: boolean;
  items: ShellNavItem[];
}

export function icon(name: string): string {
  const paths: Record<string, string> = {
    home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
    folder: '<path d="M3 6h6l2 2h10v9H3z"/><path d="M3 6v12h18"/>',
    tasks: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 12l3 3 5-6"/>',
    agents: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1-4 4-5.5 7-5.5s6 1.5 7 5.5"/><path d="M18 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1z"/>',
    person: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1-4 4-5.5 7-5.5s6 1.5 7 5.5"/>',
    book: '<path d="M5 4h11a3 3 0 013 3v13H8a3 3 0 01-3-3z"/><path d="M5 17a3 3 0 013-3h11"/>',
    vault: '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="12" cy="12" r="3.5"/><path d="M12 8.5V7M12 16.5V17M15.5 12H17M7 12h1.5"/>',
    decision: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    transfers: '<path d="M4 9h13l-3-3M20 15H7l3 3"/>',
    machines: '<rect x="4" y="4" width="16" height="7" rx="2"/><rect x="4" y="13" width="16" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
    inspector: '<circle cx="11" cy="11" r="6"/><path d="M16 16l5 5"/>',
    graph: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="10" cy="18" r="2.5"/><path d="M8.2 7.2l7.4 1.2M7 8.3l2.2 7.4M16.5 10.2l-4.8 6"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    logout: '<path d="M14 4h5v16h-5M10 8l-4 4 4 4M6 12h11"/>',
    goto: '<path d="M5 12h12M13 7l5 5-5 5"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    card: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
    help: '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/>',
    chev: '<path d="M6 9l6 6 6-6"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
  };
  const body = paths[name] ?? '<circle cx="12" cy="12" r="8"/>';
  return `<svg class="app-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

/**
 * Groupes de navigation (R2-coque, fiche E1) : 7 entrées quotidiennes puis
 * le groupe « Studio » (Réglages, Abonnement, Aide). Libellés et ordre de la
 * maquette : Aujourd'hui, Projets, Tâches, À valider, Équipe IA,
 * Connaissances, Fichiers — Réglages, Abonnement, Aide.
 *
 * Correspondances : Équipe IA → Agents (+ Inspecteur historique) ;
 * Connaissances → Bibliothèque ; Fichiers → Vault (+ atlas). Les routes
 * expertes et d'administration historiques restent routées (liens directs,
 * palette) et activent l'entrée Studio la plus proche — jamais de page sans
 * repère actif. `role` pilote l'entrée Abonnement (propriétaire seul, E1) ;
 * `plan` habille sa pastille (texte, jamais la couleur seule).
 */
export function shellNavGroups(
  route: Route,
  desktop = false,
  mode: UiMode = "simple",
  role: StudioRole = "owner",
  plan = "Gratuit",
): ShellNavGroup[] {
  const is = (...names: Route["name"][]): boolean => names.includes(route.name);
  void desktop;
  void mode;
  const main: ShellNavItem[] = [
    { href: "#/", label: "Aujourd'hui", short: "Auj.", icon: "home", active: is("dashboard") },
    { href: "#/projets", label: "Projets", icon: "folder", active: is("projects", "project") },
    { href: "#/taches", label: "Tâches", icon: "tasks", active: is("tasks", "task") },
    { href: "#/a-valider", label: "À valider", short: "Valider", icon: "decision", active: is("decisions") },
    { href: "#/equipe-ia", label: "Équipe IA", short: "Équipe", icon: "agents", active: is("agents", "agent", "inspector") },
    { href: "#/connaissances/savoir-faire", label: "Connaissances", short: "Savoirs", icon: "book", active: is("library", "libraryDetail") },
    { href: "#/connaissances/notes", label: "Fichiers", icon: "file", active: is("vault", "vaultDetail", "vaultAtlas") },
  ];
  const studio: ShellNavItem[] = [
    {
      href: "#/reglages",
      label: "Réglages",
      icon: "settings",
      active: is(
        "admin",
        "adminMeasures",
        "machines",
        "accounts",
        "transfers",
        "configRuntimes",
        "configRuntime",
        "configBindings",
        "configProject",
        "configApplication",
        "configIntegrations",
        "workspaces",
      ),
    },
    { href: "#/aide", label: "Aide", icon: "help", active: is("help") },
  ];
  if (role === "owner") {
    studio.splice(1, 0, {
      href: "#/abonnement",
      label: "Abonnement",
      short: "Abon.",
      icon: "card",
      active: is("subscription"),
      pill: plan,
    });
  }
  return [
    { title: "Principal", items: main },
    { title: "Studio", items: studio },
  ];
}

/**
 * Libellé complet + libellé court (rail) ; un seul est visible à la fois. Le
 * complet reste le nom accessible (masqué visuellement en rail, jamais retiré).
 */
function labelHtml(label: string, short?: string): string {
  if (short === undefined || short === label) return `<span class="app-navlabel">${esc(label)}</span>`;
  return `<span class="app-navlabel app-lbl-full">${esc(label)}</span><span class="app-navlabel app-lbl-short" aria-hidden="true">${esc(short)}</span>`;
}

function navItemHtml(item: ShellNavItem): string {
  const current = item.active ? ' aria-current="page"' : "";
  const pill = item.pill === undefined ? "" : `<span class="app-navpill">${esc(item.pill)}</span>`;
  return `<li><a class="app-navlink${item.active ? " active" : ""}" href="${esc(item.href)}"${current}>${icon(item.icon)}${labelHtml(item.label, item.short)}${pill}</a></li>`;
}

function navGroupHtml(group: ShellNavGroup, index: number): string {
  const items = group.items.map(navItemHtml).join("");
  // Le groupe « Studio » est repoussé en pied (même placement que
  // l'Administration historique) ; « Principal » reste sans titre visible.
  const placement = group.title === "Studio" ? " app-navgroup--admin" : "";
  const titleClass = group.title === "Principal" ? "ds-sr-only" : "app-navgroup-title";
  return `<section class="app-navgroup${placement}" aria-labelledby="app-navgroup-${index}"><h2 id="app-navgroup-${index}" class="${titleClass}">${esc(group.title)}</h2><ul>${items}</ul></section>`;
}

/**
 * Sélecteur de studio (E1) : bouton de menu + rôle sous le nom. Clavier :
 * Entrée/Espace ouvre, flèches haut/bas déplacent, Entrée choisit, Échap
 * ferme (câblé par main.ts). Changer de studio ne recharge pas la page.
 * Studio unique → pas de menu, pas de flèche. Suspendu → mention textuelle.
 */

export type StudioSelectorState =
  | { status: "loading" }
  | { status: "ready"; studios: Studio[]; activeId: string }
  | { status: "error" };

function studioInitial(name: string): string {
  const letter = name.trim().slice(0, 1).toUpperCase();
  return letter === "" ? "?" : letter;
}

function studioRoleLine(studio: Studio): string {
  const role = studioRoleLabel(studio.role);
  return studio.status === "suspended" ? `${role} · Suspendu` : role;
}

export function studioSelectorHtml(state: StudioSelectorState): string {
  if (state.status === "loading") {
    return `<div class="app-studio" data-testid="studio-selector"><span class="app-studio-loading" role="status">Chargement du studio…</span></div>`;
  }
  if (state.status === "error") {
    return (
      `<div class="app-studio" data-testid="studio-selector">` +
      `<p class="app-studio-error" role="alert">Studios indisponibles</p>` +
      `<button class="app-studio-retry" type="button" id="studio-retry">Réessayer</button></div>`
    );
  }
  const active = state.studios.find((studio) => studio.id === state.activeId) ?? state.studios[0];
  if (active === undefined) {
    return `<div class="app-studio" data-testid="studio-selector"><span class="app-studio-loading" role="status">Aucun studio</span></div>`;
  }
  const avatar = `<span class="app-studio-avatar" aria-hidden="true">${esc(studioInitial(active.name))}</span>`;
  const text =
    `<span class="app-studio-text"><span class="app-studio-name">${esc(active.name)}</span>` +
    `<span class="app-studio-role">${esc(studioRoleLine(active))}</span></span>`;
  if (state.studios.length === 1) {
    return (
      `<div class="app-studio" data-testid="studio-selector" title="Studio unique">` +
      `<span class="app-studio-current">${avatar}${text}</span></div>`
    );
  }
  const options = state.studios
    .map(
      (studio) =>
        `<li role="none"><button class="app-studio-option${studio.id === active.id ? " active" : ""}" type="button" role="menuitemradio" ` +
        `aria-checked="${studio.id === active.id ? "true" : "false"}" data-studio-id="${esc(studio.id)}">` +
        `<span class="app-studio-avatar" aria-hidden="true">${esc(studioInitial(studio.name))}</span>` +
        `<span class="app-studio-text"><span class="app-studio-name">${esc(studio.name)}</span>` +
        `<span class="app-studio-role">${esc(studioRoleLabel(studio.role))} · ${esc(studio.plan)}</span></span></button></li>`,
    )
    .join("");
  return (
    `<div class="app-studio" data-testid="studio-selector">` +
    `<button class="app-studio-btn" type="button" id="studio-button" aria-haspopup="menu" aria-expanded="false" aria-controls="studio-menu">` +
    `${avatar}${text}${icon("chev")}</button>` +
    `<ul class="app-studio-menu" id="studio-menu" role="menu" aria-labelledby="studio-button" hidden>${options}</ul></div>`
  );
}

/** Remplace le sélecteur en place (changement de studio, erreur, chargement). */
export function syncStudioSelector(root: ParentNode, state: StudioSelectorState): void {
  const slot = root.querySelector("#studio-slot");
  if (slot === null) return;
  const holder = document.createElement("template");
  holder.innerHTML = studioSelectorHtml(state);
  slot.replaceChildren(...Array.from(holder.content.childNodes));
}

/**
 * Sélecteur de thème (clair / sombre / système), pied de barre latérale.
 * Contrôle natif : clavier et lecteurs d'écran sans code additionnel ;
 * le mode est appliqué et mémorisé par main.ts via theme.ts.
 */
function themeSelectorHtml(mode: ThemeMode): string {
  const options = THEME_MODES.map(
    (value) => `<option value="${value}"${value === mode ? " selected" : ""}>${esc(THEME_LABELS[value])}</option>`,
  ).join("");
  return (
    `<div class="app-theme"><label class="app-theme-label app-lbl-full" for="theme-select">Thème</label>` +
    `<select class="app-theme-select" id="theme-select" data-testid="theme-select" aria-label="Thème">${options}</select></div>`
  );
}

type ConnectionLevel = "ok" | "info" | "warn" | "error";

export interface ConnectionView {
  level: ConnectionLevel;
  label: string;
  /** Raison machine (Desktop) — absente côté navigateur. */
  reason?: string;
  /** Lien vers le détail (Desktop : Paramètres › Application). */
  href?: string;
  /** Infobulle de détail (santé serveur / assistant local / synchronisation). */
  title?: string;
  /** Action explicite d'un état dégradé (P03-status). */
  action?: ConnectionAction | null;
}

export interface ConnectionAction {
  kind: "retry" | "reconnect" | "detail";
  label: string;
}

/** Bouton ou lien d'action placé juste après l'indicateur. */
function connectionActionHtml(action: ConnectionAction, href: string | undefined): string {
  if (action.kind === "detail" && href !== undefined) {
    return `<a class="app-connection-action" id="connection-action" href="${esc(href)}">${esc(action.label)}</a>`;
  }
  return `<button class="app-connection-action" id="connection-action" type="button" data-action="${action.kind}-status">${esc(action.label)}</button>`;
}

/** État de connexion côté navigateur : seul le jeton est connu. */
function webConnection(authed: boolean): ConnectionView {
  return authed ? { level: "ok", label: "Connecté" } : { level: "info", label: "Non connecté" };
}

/**
 * L'unique indicateur de connexion/santé (C4). Le libellé reste dans le DOM
 * en mode rail (visuellement masqué) : point de couleur + texte accessible.
 */
export function connectionStatusHtml(view: ConnectionView): string {
  const tag = view.href === undefined ? "span" : "a";
  const href = view.href === undefined ? "" : ` href="${esc(view.href)}"`;
  const reason = view.reason === undefined ? "" : ` data-reason="${esc(view.reason)}"`;
  return (
    `<${tag} class="app-connection app-connection--${view.level}" id="connection-status" data-testid="connection-status" ` +
    `role="status"${reason}${href} title="${esc(view.title ?? view.label)}">` +
    `<span class="app-connection-dot" aria-hidden="true"></span><span class="app-connection-label">${esc(view.label)}</span></${tag}>` +
    (view.action ? connectionActionHtml(view.action, view.href) : "")
  );
}

/** Palette « Aller à… » : rendue fermée, remplie et câblée par commandPalette.ts. */
function paletteHtml(): string {
  return (
    `<div class="ds-overlay app-palette-overlay" id="app-palette" hidden>` +
    `<div class="app-palette" role="dialog" aria-modal="true" aria-labelledby="app-palette-title">` +
    `<h2 id="app-palette-title" class="ds-sr-only">Aller à une page</h2>` +
    `<label class="ds-sr-only" for="app-palette-input">Nom de la page</label>` +
    `<input id="app-palette-input" class="app-palette-input" type="text" autocomplete="off" spellcheck="false" ` +
    `role="combobox" aria-expanded="true" aria-controls="app-palette-list" aria-autocomplete="list" placeholder="Aller à…" />` +
    `<ul class="app-palette-list" id="app-palette-list" role="listbox" aria-label="Pages"></ul>` +
    `<p class="app-palette-hint">↑ ↓ pour choisir · Entrée pour ouvrir · Échap pour fermer</p>` +
    `</div></div>`
  );
}

/**
 * Coquille complète. `authed` pilote le bloc compte (jamais de contenu
 * inventé : état jeton + déconnexion = mécanisme existant relocalisé).
 */
export function shellHtml(route: Route, authed: boolean, desktop = false, mode: UiMode = "simple", theme: ThemeMode = "system"): string {
  const groups = shellNavGroups(route, desktop, mode)
    .map((group, index) => navGroupHtml(group, index))
    .join("");
  const account = authed
    ? `<button class="app-iconbtn app-logout" type="button" id="token-clear" aria-label="Se déconnecter" title="Se déconnecter">${icon("logout")}</button>`
    : `<div class="app-tokenrow"><label class="ds-sr-only" for="token-input">Jeton machine</label><input id="token-input" type="password" autocomplete="off" spellcheck="false" placeholder="Jeton machine (mémoire seule)" /><button class="app-tokenbtn" type="button" id="token-set">Connecter</button></div>`;
  return `<a class="ds-skip-link" href="#view">Aller au contenu</a>
<div class="app-shell">
  <div class="app-scrim" id="app-scrim" hidden></div>
  <aside class="app-sidebar" id="app-sidebar">
    <div class="app-brand"><img class="app-brand-mark" src="${esc(brandLogoUrl)}" alt="" aria-hidden="true" width="36" height="36"><span class="app-brand-name">Studi'OS</span><button class="app-iconbtn" type="button" id="nav-close" aria-label="Fermer la navigation">${icon("close")}</button></div>
    <div id="studio-slot">${studioSelectorHtml({ status: "loading" })}</div>
    <button class="app-cmdk" type="button" id="palette-open" aria-haspopup="dialog" aria-controls="app-palette" aria-keyshortcuts="Control+K" title="Aller à… (Ctrl K)">${icon("goto")}<span class="app-lbl-full">Aller à…</span><kbd class="app-lbl-full" aria-hidden="true">Ctrl K</kbd></button>
    <nav class="app-nav" aria-label="Navigation principale">${groups}</nav>
    ${themeSelectorHtml(theme)}
    <div class="app-me${authed ? "" : " app-me--guest"}">
      <span class="app-avatar" aria-hidden="true">${icon("person")}</span>
      ${connectionStatusHtml(webConnection(authed))}
      ${account}
    </div>
  </aside>
  <div class="app-col">
    <header class="app-topbar">
      <button class="app-iconbtn app-iconbtn--light" type="button" id="nav-open" aria-label="Ouvrir la navigation" aria-controls="app-sidebar" aria-expanded="false">${icon("menu")}</button>
      <span class="app-brand-name app-topbar-brand">Studi'OS</span>
    </header>
    <div id="conflict-banner" class="conflict-banner" role="status" hidden></div>
    <div id="studio-suspended-banner" class="studio-suspended-banner" hidden></div>
    <div id="client-update-banner" class="client-update-banner" role="status" aria-live="polite" hidden></div>
    <div id="desktop-update-banner" class="client-update-banner" role="status" aria-live="polite" hidden></div>
    <div id="breadcrumb-slot"></div>
    <main id="view" tabindex="-1"></main>
  </div>
</div>
${paletteHtml()}
<div id="ds-toast-region" class="ds-toasts" role="status" aria-live="polite"></div>`;
}

/** État actif seul (évite de reconstruire le shell à chaque rendu). */
export function syncNav(
  route: Route,
  root: ParentNode,
  desktop = false,
  mode: UiMode = "simple",
  role: StudioRole = "owner",
  plan = "Gratuit",
): void {
  const links = root.querySelectorAll<HTMLAnchorElement>(".app-sidebar a.app-navlink");
  const targets = new Map<string, boolean>();
  for (const group of shellNavGroups(route, desktop, mode, role, plan)) {
    for (const item of group.items) targets.set(item.href, item.active);
  }
  for (const link of links) {
    const active = targets.get(link.getAttribute("href") ?? "") ?? false;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

const RAIL_QUERY = "(min-width: 901px) and (max-width: 1399.98px)";

/** Rail d'icônes (901–1399 px) : l'Administration y sort en volet flottant. */
function railMode(): boolean {
  return typeof matchMedia === "function" && matchMedia(RAIL_QUERY).matches;
}

let flyoutListeners = false;

/**
 * Volets repliés du rail : fermés par défaut (même sur une page du groupe,
 * pour ne jamais couvrir le contenu), refermés après un choix, un clic
 * ailleurs ou Échap. En barre complète, ils se déplient en place.
 */
export function mountAdminFlyout(root: ParentNode = document): void {
  const admins = (): HTMLDetailsElement[] =>
    [...root.querySelectorAll<HTMLDetailsElement>("details.app-navgroup--secondary")];
  const fit = (): void => {
    for (const node of admins()) {
      node.open = railMode() ? false : node.querySelector(".app-navlink.active") !== null;
    }
  };
  fit();
  if (flyoutListeners || typeof matchMedia !== "function") return;
  flyoutListeners = true;
  matchMedia(RAIL_QUERY).addEventListener("change", fit);
  document.addEventListener("click", (event) => {
    if (!railMode()) return;
    const target = event.target as Element | null;
    for (const node of admins()) {
      if (!node.open) continue;
      if (target?.closest(".app-navgroup--secondary > ul a") || !node.contains(target)) node.open = false;
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !railMode()) return;
    for (const node of admins()) {
      if (!node.open || !node.contains(event.target as Node)) continue;
      node.open = false;
      node.querySelector("summary")?.focus();
    }
  });
}

/** Remplace l'unique indicateur de connexion (navigateur ou Desktop). */
export function paintConnection(view: ConnectionView, root: ParentNode): void {
  const existing = root.querySelector("#connection-status");
  if (existing === null) return;
  root.querySelector("#connection-action")?.remove();
  const holder = document.createElement("template");
  holder.innerHTML = connectionStatusHtml(view);
  existing.replaceWith(...Array.from(holder.content.childNodes));
}

/** État d'authentification côté navigateur (le Desktop le repeint ensuite). */
export function syncAuthState(authed: boolean, root: ParentNode): void {
  paintConnection(webConnection(authed), root);
}
