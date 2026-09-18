/**
 * Application shell (UI-2, DEC-0079).
 *
 * AppShell : sidebar bleu nuit + topbar minimale + contenu principal.
 * Le shell est construit UNE fois (mountShell) ; render() ne remplace
 * que #view et synchronise l'état actif — jamais de reconstruction qui
 * fermerait le drawer ou perdrait le focus.
 *
 * Anti-race (arbitrage UI-2) : chaque render() prend un jeton
 * (renderGuard) et peint dans un nœud détaché ; seul le rendu encore
 * courant est attaché. Une ancienne route ne repeint jamais la courante.
 *
 * Routes : voir src/router.ts. #/design-system = démo interne (aucune
 * entrée nav). Activity/Worklogs sortis de la nav (Activité reviendra
 * comme onglet projet en UI-4). Token : mémoire seule, déconnexion =
 * retour à l'écran de connexion.
 */
import { apiBaseUrl, createApiClient } from "./api";
import { resolveApiUrl } from "./config";
import { clearToken, getToken, hasToken, setToken } from "./auth";
import { subscribe, uiState } from "./store";
import { renderOverview } from "./views/overview";
import { renderProjects } from "./views/projects";
import { renderProjectDetail } from "./views/projectDetail";
import { renderTaskDetail } from "./views/taskDetail";
import { renderTasksInto } from "./views/tasks";
import { renderAgentDetail, renderAgents } from "./views/agents";
import { renderMachines } from "./views/machines";
import { renderDecisionsV2 as renderDecisions } from "./views/decisionsV2";
import { renderTransfers } from "./views/transfers";
import { renderLibrary, renderLibraryDetail } from "./views/library";
import { renderBindings, renderProjectConfig, renderRuntimeDetail, renderRuntimes } from "./views/configuration";
import { renderInspector } from "./views/inspector";
import { renderDesignSystem } from "./views/designSystem";
import { renderNotFound } from "./views/notFound";
import { loginOverlayHtml, renderLogin } from "./login";
import { parseRoute } from "./router";
import { shellHtml, syncAuthState, syncNav } from "./shell";
import { createRenderGuard } from "./renderGuard";
import { startRealtimeConnection, type RealtimeConnection } from "./realtime";
import type { components } from "./openapi-schema";
import "./ds/tokens.css";
import "./ds/components.css";
import "./shell.css";
import "./views/overview.css";
import "./views/projects.css";
import "./views/library.css";
import "./views/workspace.css";
import "./views/decisions.css";
import "./styles.css";

type EventEnvelope = components["schemas"]["EventEnvelope"];

const renderGuard = createRenderGuard();
let shellListenersMounted = false;

async function render(): Promise<void> {
  const my = renderGuard.next();
  const route = parseRoute(location.hash);
  const baseUrl = resolveApiUrl(apiBaseUrl());
  const client = createApiClient(baseUrl);
  const authed = hasToken();
  const staging = document.createElement("div");
  switch (route.name) {
    case "projects":
      await renderProjects(staging, { client, authed });
      break;
    case "project":
      await renderProjectDetail(staging, { client, authed }, route.id, route.tab);
      break;
    case "tasks":
      await renderTasksInto(staging, {
        client,
        authed,
        projectId: uiState.selectedProjectId ?? undefined,
        scopeLabel: uiState.selectedProjectId ? "Projet sélectionné (à changer dans Vue d'ensemble ou Projets)" : "Tous les projets",
      });
      break;
    case "task":
      await renderTaskDetail(staging, { client, authed }, route.id);
      break;
    case "agents":
      await renderAgents(staging, { client, authed });
      break;
    case "agent":
      await renderAgentDetail(staging, { client, authed }, route.id);
      break;
    case "machines":
      await renderMachines(staging, { client, baseUrl, authed });
      break;
    case "decisions":
      await renderDecisions(staging, { client, authed });
      break;
    case "transfers":
      await renderTransfers(staging, { client, authed });
      break;
    case "library":
      await renderLibrary(staging, { client, authed }, route.kind);
      break;
    case "libraryDetail":
      await renderLibraryDetail(staging, { client, authed }, route.kind, route.id);
      break;
    case "configRuntimes":
      await renderRuntimes(staging, { client, authed });
      break;
    case "configRuntime":
      await renderRuntimeDetail(staging, { client, authed }, route.id);
      break;
    case "configBindings":
      await renderBindings(staging, { client, authed });
      break;
    case "configProject":
      await renderProjectConfig(staging, { client, authed }, route.tab);
      break;
    case "inspector":
      await renderInspector(staging, { client, authed, stableKey: route.stableKey });
      break;
    case "designSystem":
      renderDesignSystem(staging);
      break;
    case "notFound":
      renderNotFound(staging, route.hash);
      break;
    case "dashboard":
    default:
      await renderOverview(staging, { client, baseUrl, authed });
      break;
  }
  if (!renderGuard.isCurrent(my)) return;
  // Le staging DEVIENT #view : les vues capturent la racine en closure
  // pour leurs requêtes différées (handlers) — déplacer les enfants seuls
  // casserait ces requêtes. Remplacer le nœud préserve les listeners.
  const old = document.getElementById("view");
  if (old === null) return;
  staging.id = "view";
  staging.tabIndex = -1;
  old.replaceWith(staging);
  syncNav(route, document);
  syncAuthState(authed, document);
}

let conflictBannerTimer: ReturnType<typeof setTimeout> | null = null;

function showConflictBanner(event: EventEnvelope): void {
  const banner = document.getElementById("conflict-banner");
  if (banner === null) return;
  const resourcePath = typeof event.payload?.["resource_path"] === "string" ? event.payload["resource_path"] : "unknown resource";
  banner.textContent = `Resource conflict: ${resourcePath}`;
  banner.hidden = false;
  if (conflictBannerTimer !== null) clearTimeout(conflictBannerTimer);
  conflictBannerTimer = setTimeout(() => {
    banner.hidden = true;
    conflictBannerTimer = null;
  }, 8000);
}

let realtimeConnection: RealtimeConnection | null = null;
let realtimeKey: string | null = null;

/** One live connection per tab, opened/closed as the selected project or
 * token changes — never per-view (the backend has exactly one stream per
 * project, `project` required, DEC-0018). Every live message triggers the
 * same `render()` a manual navigation would (debounced in realtime.ts). */
function syncRealtimeConnection(): void {
  const token = getToken();
  const projectId = uiState.selectedProjectId;
  const key = token !== null && projectId !== null ? `${projectId}::${token}` : null;
  if (key === realtimeKey) return;
  realtimeConnection?.close();
  realtimeConnection = null;
  realtimeKey = key;
  if (token === null || projectId === null) return;
  const baseUrl = resolveApiUrl(apiBaseUrl());
  realtimeConnection = startRealtimeConnection(
    baseUrl,
    token,
    projectId,
    {
      onRefetch: () => {
        void render();
      },
      onConflict: (event) => {
        showConflictBanner(event);
      },
    },
  );
}

function openDrawer(): void {
  const sidebar = document.getElementById("app-sidebar");
  const scrim = document.getElementById("app-scrim");
  const openBtn = document.getElementById("nav-open");
  if (sidebar === null || scrim === null) return;
  sidebar.classList.add("open");
  scrim.hidden = false;
  openBtn?.setAttribute("aria-expanded", "true");
  sidebar.querySelector<HTMLAnchorElement>("a.app-navlink")?.focus();
}

function closeDrawer(restoreFocus = true): void {
  const sidebar = document.getElementById("app-sidebar");
  const scrim = document.getElementById("app-scrim");
  const openBtn = document.getElementById("nav-open") as HTMLButtonElement | null;
  if (sidebar === null || scrim === null) return;
  if (!sidebar.classList.contains("open")) return;
  sidebar.classList.remove("open");
  scrim.hidden = true;
  openBtn?.setAttribute("aria-expanded", "false");
  if (restoreFocus) openBtn?.focus();
}

export function isDrawerOpen(): boolean {
  return document.getElementById("app-sidebar")?.classList.contains("open") ?? false;
}

function mountShell(): void {
  const app = document.getElementById("app");
  if (app === null) throw new Error("#app missing");
  app.innerHTML = shellHtml(parseRoute(location.hash), hasToken());

  document.getElementById("nav-open")?.addEventListener("click", () => openDrawer());
  document.getElementById("nav-close")?.addEventListener("click", () => closeDrawer());
  document.getElementById("app-scrim")?.addEventListener("click", () => closeDrawer());
  app.querySelector(".ds-skip-link")?.addEventListener("click", (event) => {
    event.preventDefault();
    document.getElementById("view")?.focus();
  });
  if (!shellListenersMounted) {
    shellListenersMounted = true;
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !isDrawerOpen()) return;
      if ((event.target as HTMLElement | null)?.closest(".ds-overlay") !== null) return;
      closeDrawer();
    });
    subscribe(() => {
      syncRealtimeConnection();
      void render();
    });
    window.addEventListener("hashchange", () => {
      if (isDrawerOpen()) closeDrawer(false);
      void render();
    });
  }
  const input = document.getElementById("token-input") as HTMLInputElement | null;
  const applyInputToken = (): void => {
    if (input === null) return;
    setToken(input.value);
    input.value = "";
    mountShell();
  };
  document.getElementById("token-set")?.addEventListener("click", applyInputToken);
  input?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") applyInputToken();
  });
  document.getElementById("token-clear")?.addEventListener("click", () => {
    clearToken();
    syncRealtimeConnection();
    mountLogin();
  });

  syncRealtimeConnection();
  void render();
}

function mountLogin(): void {
  const app = document.getElementById("app");
  if (app === null) throw new Error("#app missing");
  app.innerHTML = loginOverlayHtml();
  renderLogin(app, () => {
    syncRealtimeConnection();
    mountShell();
  });
}

export function boot(): void {
  if (hasToken()) {
    mountShell();
  } else {
    mountLogin();
  }
}

boot();
