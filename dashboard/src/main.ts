/**
 * Application shell (DASH-0/2).
 *
 * Routes: #/ (Dashboard overview), #/projects, #/projects/<id>[/tasks|/claims],
 * #/tasks, #/tasks/<id>, #/machines, #/decisions, #/transfers, #/library…,
 * #/configuration/…, #/inspector[…]. Activity/Worklogs stay DISABLED
 * (no fake content). #/design-system is the internal Design System demo
 * (DEC-0078, no nav entry). Token bar: manual Bearer, memory-only,
 * one-click clear.
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
import { renderMachines } from "./views/machines";
import { renderDecisions } from "./views/decisions";
import { renderTransfers } from "./views/transfers";
import { renderLibrary, renderLibraryDetail } from "./views/library";
import { renderBindings, renderProjectConfig, renderRuntimeDetail, renderRuntimes } from "./views/configuration";
import { renderInspector } from "./views/inspector";
import { renderDesignSystem } from "./views/designSystem";
import { loginOverlayHtml, renderLogin } from "./login";
import { parseRoute, type Route } from "./router";
import { esc } from "./ui";
import { startRealtimeConnection, type RealtimeConnection } from "./realtime";
import type { components } from "./openapi-schema";
import "./ds/tokens.css";
import "./ds/components.css";
import "./styles.css";

type EventEnvelope = components["schemas"]["EventEnvelope"];

const DISABLED_SECTIONS = ["Activity", "Worklogs"] as const;

function navHtml(route: Route): string {
  const item = (href: string, label: string, active: boolean): string =>
    `<a class="nav-item${active ? " active" : ""}" href="${href}">${esc(label)}</a>`;
  const disabled = DISABLED_SECTIONS.map(
    (name) => `<span class="nav-item disabled" title="Planned later">${esc(name)}<span class="badge">later</span></span>`,
  ).join("");
  return `<nav class="nav">${item("#/", "Dashboard", route.name === "dashboard")}${item(
    "#/projects",
    "Projects",
    route.name === "projects" || route.name === "project",
  )}${item("#/tasks", "Tasks", route.name === "tasks" || route.name === "task")}${item(
    "#/machines",
    "Machines",
    route.name === "machines",
  )}${item("#/decisions", "Decisions", route.name === "decisions")}${item(
    "#/transfers",
    "Transfers",
    route.name === "transfers",
  )}${item("#/library", "Library", route.name === "library" || route.name === "libraryDetail")}${item(
    "#/configuration/runtimes",
    "Configuration",
    route.name === "configRuntimes" || route.name === "configRuntime" || route.name === "configBindings" || route.name === "configProject",
  )}${item("#/inspector", "Inspector", route.name === "inspector")}${disabled}</nav>`;
}

function shellHtml(apiUrl: string, route: Route): string {
  const shownUrl = apiUrl === "" ? "same-origin" : apiUrl;
  return `
  <a class="ds-skip-link" href="#view">Aller au contenu</a>
  <header class="topbar">
    <div class="brand">Studi'OS <span class="v0">dashboard v0</span></div>
    ${navHtml(route)}
    <div class="api-url" title="API base URL (VITE_STUDIO_API_URL, empty = same-origin)">${esc(shownUrl)}</div>
  </header>
  <div class="tokenbar">
    <label>Machine token
      <input id="token-input" type="password" autocomplete="off" spellcheck="false" placeholder="Bearer token (memory only)" />
    </label>
    <button id="token-set" type="button">Set</button>
    <button id="token-clear" type="button">Clear</button>
    <span id="token-state" class="meta"></span>
    <span class="meta warn" title="The token stays in page memory. It is never stored, never logged, never rendered back. Clearing drops it from this session.">memory-only · never stored</span>
  </div>
  <div id="conflict-banner" class="conflict-banner" role="status" hidden></div>
  <main id="view" tabindex="-1"></main>
  <div id="ds-toast-region" class="ds-toasts" role="status" aria-live="polite"></div>`;
}

function refreshTokenState(): void {
  const state = document.getElementById("token-state");
  const input = document.getElementById("token-input") as HTMLInputElement | null;
  if (state !== null) state.textContent = hasToken() ? "token set (hidden)" : "no token";
  if (input !== null && hasToken()) input.value = "";
}

async function render(): Promise<void> {
  const view = document.getElementById("view");
  const topbar = document.querySelector(".topbar");
  if (view === null) return;
  const route = parseRoute(location.hash);
  if (topbar !== null) topbar.outerHTML = `<header class="topbar"><div class="brand">Studi'OS <span class="v0">dashboard v0</span></div>${navHtml(route)}<div class="api-url">${esc(apiUrlShown())}</div></header>`;
  const baseUrl = resolveApiUrl(apiBaseUrl());
  const client = createApiClient(baseUrl);
  const authed = hasToken();
  switch (route.name) {
    case "projects":
      await renderProjects(view, { client, authed });
      break;
    case "project":
      await renderProjectDetail(view, { client, authed }, route.id, route.tab);
      break;
    case "tasks":
      await renderTasksInto(view, {
        client,
        authed,
        projectId: uiState.selectedProjectId ?? undefined,
        scopeLabel: uiState.selectedProjectId ? "selected project (change in Overview/Projects)" : "all projects",
      });
      break;
    case "task":
      await renderTaskDetail(view, { client, authed }, route.id);
      break;
    case "machines":
      await renderMachines(view, { client, baseUrl, authed });
      break;
    case "decisions":
      await renderDecisions(view, { client, authed });
      break;
    case "transfers":
      await renderTransfers(view, { client, authed });
      break;
    case "library":
      await renderLibrary(view, { client, authed }, route.kind);
      break;
    case "libraryDetail":
      await renderLibraryDetail(view, { client, authed }, route.kind, route.id);
      break;
    case "configRuntimes":
      await renderRuntimes(view, { client, authed });
      break;
    case "configRuntime":
      await renderRuntimeDetail(view, { client, authed }, route.id);
      break;
    case "configBindings":
      await renderBindings(view, { client, authed });
      break;
    case "configProject":
      await renderProjectConfig(view, { client, authed }, route.tab);
      break;
    case "inspector":
      await renderInspector(view, { client, authed, stableKey: route.stableKey });
      break;
    case "designSystem":
      renderDesignSystem(view);
      break;
    case "dashboard":
    default:
      await renderOverview(view, { client, baseUrl, authed });
      break;
  }
}

function apiUrlShown(): string {
  const baseUrl = resolveApiUrl(apiBaseUrl());
  return baseUrl === "" ? "same-origin" : baseUrl;
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

function mountShell(): void {
  const app = document.getElementById("app");
  if (app === null) throw new Error("#app missing");
  app.innerHTML = shellHtml(resolveApiUrl(apiBaseUrl()), parseRoute(location.hash));

  const input = document.getElementById("token-input") as HTMLInputElement;
  document.getElementById("token-set")?.addEventListener("click", () => {
    setToken(input.value);
    input.value = "";
    refreshTokenState();
    syncRealtimeConnection();
    void render();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      setToken(input.value);
      input.value = "";
      refreshTokenState();
      syncRealtimeConnection();
      void render();
    }
  });
  document.getElementById("token-clear")?.addEventListener("click", () => {
    clearToken();
    refreshTokenState();
    syncRealtimeConnection();
    void render();
  });
  refreshTokenState();
  subscribe(() => {
    syncRealtimeConnection();
    void render();
  });
  window.addEventListener("hashchange", () => {
    void render();
  });
  void render();
}

function mountLogin(): void {
  const app = document.getElementById("app");
  if (app === null) throw new Error("#app missing");
  app.innerHTML = loginOverlayHtml();
  renderLogin(app, () => {
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
