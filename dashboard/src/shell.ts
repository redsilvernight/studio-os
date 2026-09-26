/**
 * AppShell StudiOS (UI-2).
 *
 * Sidebar bleu nuit + topbar minimale + contenu principal. Rendu en
 * chaînes HTML (architecture vanilla conservée), comportements au clavier
 * via addEventListener (montés par main.ts). Aucune recherche globale ni
 * cloche de notifications : aucun backend ne les supporte.
 *
 * Navigation = routes existantes uniquement. « Agents IA » (UI-6) pointe
 * vers la vraie page #/agents. Activity/Workloads, jamais fonctionnels,
 * sortent de la nav (l'Activité reviendra comme onglet projet en UI-4).
 */
import type { Route } from "./router";
import { esc } from "./ui";
import { workspaceNavEntry } from "./workspaces/workspaces";

export interface ShellNavItem {
  href: string;
  label: string;
  icon: string;
  active: boolean;
}

export interface ShellNavGroup {
  title: string;
  items: ShellNavItem[];
}

function icon(name: string): string {
  const paths: Record<string, string> = {
    home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
    folder: '<path d="M3 6h6l2 2h10v9H3z"/><path d="M3 6v12h18"/>',
    tasks: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 12l3 3 5-6"/>',
    agents: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1-4 4-5.5 7-5.5s6 1.5 7 5.5"/><path d="M18 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1z"/>',
    book: '<path d="M5 4h11a3 3 0 013 3v13H8a3 3 0 01-3-3z"/><path d="M5 17a3 3 0 013-3h11"/>',
    decision: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    transfers: '<path d="M4 9h13l-3-3M20 15H7l3 3"/>',
    machines: '<rect x="4" y="4" width="16" height="7" rx="2"/><rect x="4" y="13" width="16" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
    inspector: '<circle cx="11" cy="11" r="6"/><path d="M16 16l5 5"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    logout: '<path d="M14 4h5v16h-5M10 8l-4 4 4 4M6 12h11"/>',
  };
  const body = paths[name] ?? '<circle cx="12" cy="12" r="8"/>';
  return `<svg class="app-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

/** Groupes de navigation : routes existantes uniquement. */
/** `desktop` adds the « Dossiers » entry; the web navigation is unchanged. */
export function shellNavGroups(route: Route, desktop = false): ShellNavGroup[] {
  const is = (...names: Route["name"][]): boolean => names.includes(route.name);
  const groups: ShellNavGroup[] = [
    {
      title: "Principal",
      items: [
        { href: "#/", label: "Accueil", icon: "home", active: is("dashboard", "notFound") },
        { href: "#/projects", label: "Projets", icon: "folder", active: is("projects", "project") },
        { href: "#/tasks", label: "Tâches", icon: "tasks", active: is("tasks", "task") },
        { href: "#/agents", label: "Agents IA", icon: "agents", active: is("agents", "agent") },
      ],
    },
    {
      title: "Connaissances",
      items: [
        { href: "#/library", label: "Bibliothèque", icon: "book", active: is("library", "libraryDetail") },
        { href: "#/decisions", label: "Décisions", icon: "decision", active: is("decisions") },
        { href: "#/graphs/knowledge", label: "Graphes", icon: "inspector", active: is("graphs") },
      ],
    },
    {
      title: "Infrastructure",
      items: [
        { href: "#/transfers", label: "Transferts", icon: "transfers", active: is("transfers") },
        { href: "#/machines", label: "Machines", icon: "machines", active: is("machines") },
      ],
    },
    {
      title: "Outils",
      items: [
        { href: "#/inspector", label: "Inspecteur", icon: "inspector", active: is("inspector") },
      ],
    },
  ];
  if (desktop) {
    const entry = workspaceNavEntry();
    groups[0]?.items.splice(2, 0, { href: entry.hash, label: entry.label, icon: "folder", active: is("workspaces") });
  }
  return groups;
}

function navItemHtml(item: ShellNavItem): string {
  const current = item.active ? ' aria-current="page"' : "";
  return `<li><a class="app-navlink${item.active ? " active" : ""}" href="${esc(item.href)}"${current}>${icon(item.icon)}<span>${esc(item.label)}</span></a></li>`;
}

function navGroupHtml(group: ShellNavGroup, index: number): string {
  const items = group.items.map(navItemHtml).join("");
  return `<section class="app-navgroup" aria-labelledby="app-navgroup-${index}"><h2 id="app-navgroup-${index}">${esc(group.title)}</h2><ul>${items}</ul></section>`;
}

/**
 * Coquille complète. `authed` pilote le bloc compte (jamais de contenu
 * inventé : état jeton + déconnexion = mécanisme existant relocalisé).
 */
export function shellHtml(route: Route, authed: boolean, desktop = false): string {
  const groups = shellNavGroups(route, desktop)
    .map((group, index) => navGroupHtml(group, index))
    .join("");
  const configActive = route.name === "configRuntimes" || route.name === "configRuntime" || route.name === "configBindings" || route.name === "configProject" || route.name === "configApplication" || route.name === "configIntegrations";
  const accountBlock = authed
    ? `<div class="app-account"><span class="app-account-state">Connecté · jeton masqué</span><button class="app-logout" type="button" id="token-clear">${icon("logout")}<span>Se déconnecter</span></button></div>`
    : `<div class="app-account"><span class="app-account-state">Non connecté</span><div class="app-tokenrow"><label class="ds-sr-only" for="token-input">Jeton machine</label><input id="token-input" type="password" autocomplete="off" spellcheck="false" placeholder="Jeton machine (mémoire seule)" /><button class="app-tokenbtn" type="button" id="token-set">Connecter</button></div><p class="app-tokenhint">Mémoire seule · jamais stocké</p></div>`;
  return `<a class="ds-skip-link" href="#view">Aller au contenu</a>
<div class="app-shell">
  <div class="app-scrim" id="app-scrim" hidden></div>
  <aside class="app-sidebar" id="app-sidebar">
    <div class="app-brand"><span class="app-brand-mark" aria-hidden="true">S</span><span class="app-brand-name">Studi'OS</span><button class="app-iconbtn" type="button" id="nav-close" aria-label="Fermer la navigation">${icon("close")}</button></div>
    <nav class="app-nav" aria-label="Navigation principale">${groups}</nav>
    <div class="app-sidebar-foot">
      <a class="app-navlink${configActive ? " active" : ""}" href="#/configuration/runtimes"${configActive ? ' aria-current="page"' : ""}>${icon("settings")}<span>Paramètres</span></a>
      ${accountBlock}
    </div>
  </aside>
  <div class="app-col">
    <header class="app-topbar">
      <button class="app-iconbtn app-iconbtn--light" type="button" id="nav-open" aria-label="Ouvrir la navigation" aria-controls="app-sidebar" aria-expanded="false">${icon("menu")}</button>
      <span class="app-topbar-state" id="token-state"></span>
    </header>
    <div id="conflict-banner" class="conflict-banner" role="status" hidden></div>
    <div id="client-update-banner" class="client-update-banner" role="status" aria-live="polite" hidden></div>
    <main id="view" tabindex="-1"></main>
  </div>
</div>
<div id="ds-toast-region" class="ds-toasts" role="status" aria-live="polite"></div>`;
}

/** État actif seul (évite de reconstruire le shell à chaque rendu). */
export function syncNav(route: Route, root: ParentNode, desktop = false): void {
  const links = root.querySelectorAll<HTMLAnchorElement>(".app-sidebar a.app-navlink");
  const targets = new Map<string, boolean>();
  for (const group of shellNavGroups(route, desktop)) {
    for (const item of group.items) targets.set(item.href, item.active);
  }
  const configActive = route.name === "configRuntimes" || route.name === "configRuntime" || route.name === "configBindings" || route.name === "configProject" || route.name === "configApplication" || route.name === "configIntegrations";
  targets.set("#/configuration/runtimes", configActive);
  for (const link of links) {
    const active = targets.get(link.getAttribute("href") ?? "") ?? false;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

/** Pastille d'état d'authentification dans la topbar (réelle, pas décorative). */
export function syncAuthState(authed: boolean, root: ParentNode): void {
  const state = root.querySelector("#token-state");
  if (state !== null) state.textContent = authed ? "Connecté" : "Non connecté";
}
