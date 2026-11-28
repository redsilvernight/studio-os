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
 * Routes : voir src/router.ts. #/reglages/avance/design-system = démo interne (aucune
 * entrée nav). Activity/Worklogs sortis de la nav (Activité reviendra
 * comme onglet projet en UI-4). Token : mémoire seule, déconnexion =
 * retour à l'écran de connexion.
 */
import { apiBaseUrl, createApiClient } from "./api";
import { showClientUpdateAdvisory, showClientUpgradeRequired as showUpgradeRequired } from "./clientUpgradeUi";
import { checkUpdateAtStart, paintUpdateBanner } from "./updateAtStart";
import { checkWhatsNewAtStart } from "./releaseNotes";
import { loadActorNames } from "./actorNames";
import { resolveApiUrl } from "./config";
import { clearToken, getToken, hasToken, setToken } from "./auth";
import { subscribe, uiState } from "./store";
import { loadOnboardingState, onboardingRedirect } from "./onboarding/state";
import { loginOverlayHtml, renderLogin } from "./login";
import { PUBLIC_HASH, publicHashScreen, readAccountLink, scrubbedPath } from "./accountLink";
import { renderPublicAccount, type PublicScreen } from "./views/publicAccount";
import { probeProjectAccess, renderAwaitingAccess, type ProjectAccess } from "./views/awaitingAccess";
import { lazyView, renderViewLoadError, ViewLoadError } from "./lazyView";
import { forgetLocalIdentity } from "./localIdentity";
import { getPlatform } from "./platform";
import { getDesktopShell, paintShellStatus, prepareDesktop, setDesktopHooks } from "./desktopShell";
import { mountSkillsSync } from "./skillsSync";
import { parseRoute } from "./router";
import { canonicalHash } from "./routeAliases";
import { closePalette, isPaletteOpen, mountPalette, paletteEntries } from "./commandPalette";
import { applyUiMode, loadUiMode, switchUiMode, toggledUiMode, watchExpertMode } from "./uiMode";
import { applyThemeMode, isThemeMode, loadThemeMode, saveThemeMode } from "./theme";
import { breadcrumbHtml, mountAdminFlyout, paintConnection, shellHtml, syncAuthState, syncNav, syncStudioSelector } from "./shell";
import { listStudios, probeServer, type StudiosClient } from "./studiosApi";
import {
  STUDIO_CHANGE_EVENT,
  getActiveStudio,
  selectStudio,
  setStudios,
} from "./studioStore";
import { createRenderGuard } from "./renderGuard";
import { syncSuspendedBanner } from "./studioSuspendedBanner";
import { LIVE_CHANGE_EVENT, startRealtimeConnection, type RealtimeConnection } from "./realtime";
import type { LiveState } from "./views/mission";
import { setApiObserver } from "./apiEvents";
import { resetIdentityCache } from "./identityApi";
import { SESSION_ENDED_NOTICE, createSessionEndHandler } from "./session";
import { configurePersistentSession, endPersistentSession, refreshSession, resumeSession } from "./persistentSession";
import type { components } from "./openapi-schema";
import "./ds/fonts.css";
import "./ds/tokens.css";
import "./ds/components.css";
import "./ds/lot1.css";
import "./shell.css";
import "./views/overview.css";
import "./views/projects.css";
import "./views/library.css";
import "./views/vault.css";
import "./views/admin.css";
import "./views/workspace.css";
import "./views/roadmap.css";
import "./views/decisions.css";
import "./styles.css";

type EventEnvelope = components["schemas"]["EventEnvelope"];

let fixtureRoadmapDataSource: ReturnType<typeof import("./roadmapData").createFixtureRoadmapDataSource> | undefined;

const renderGuard = createRenderGuard();
let shellListenersMounted = false;

// Only a granted access is remembered (per token): « none » is re-asked on
// every landing render so a newly added membership shows up at once.
let grantedForToken: string | null = null;

async function projectAccess(client: ReturnType<typeof createApiClient>): Promise<ProjectAccess> {
  const token = getToken();
  if (token !== null && token === grantedForToken) return "granted";
  const access = await probeProjectAccess(client);
  if (access === "granted") grantedForToken = token;
  return access;
}

type Route = ReturnType<typeof parseRoute>;
type LoadView = <T>(importer: () => Promise<T>) => Promise<T>;

/** Thrown once a render is obsolete (newer navigation or session ended) while its chunk was loading. */
class StaleRender extends Error {}

/**
 * Une vue = un chunk chargé à la demande (`lazyView`) : le chunk d'entrée ne
 * contient que le shell, le routeur et la connexion. Les URL (`#/…`, deep
 * links) et les rendus sont inchangés ; seul le moment du chargement du code
 * diffère. Les sources de roadmap (API ou fixture) ne servent qu'à la route
 * projet et suivent donc le même chunk.
 */
async function renderRoute(
  staging: HTMLElement,
  route: Route,
  ctx: { client: ReturnType<typeof createApiClient>; baseUrl: string; authed: boolean; load: LoadView },
): Promise<void> {
  const { client, baseUrl, authed, load } = ctx;
  switch (route.name) {
    case "projects":
      await (await load(() => import("./views/projects"))).renderProjects(staging, { client, authed });
      break;
    case "project": {
      const [{ renderProjectDetail }, { createApiRoadmapDataSource }, { createFixtureRoadmapDataSource }] = await load(() =>
        Promise.all([import("./views/projectDetail"), import("./roadmapApi"), import("./roadmapData")]),
      );
      // Authenticated sessions read the canonical P3 API; anonymous or
      // development sessions keep the session-local fixture (tests, offline).
      fixtureRoadmapDataSource ??= createFixtureRoadmapDataSource();
      await renderProjectDetail(
        staging,
        {
          client,
          authed,
          roadmapDataSource: authed ? createApiRoadmapDataSource(client) : fixtureRoadmapDataSource,
          live: () => liveState,
        },
        route.id,
        route.tab,
        route.roadmapId,
      );
      break;
    }
    case "tasks": {
      const { renderTasksInto } = await load(() => import("./views/tasks"));
      await renderTasksInto(staging, {
        client,
        authed,
        projectId: uiState.selectedProjectId ?? undefined,
        scopeLabel: uiState.selectedProjectId ? "Projet sélectionné (à changer dans Vue d'ensemble ou Projets)" : "Tous les projets",
      });
      break;
    }
    case "task":
      await (await load(() => import("./views/taskDetail"))).renderTaskDetail(staging, { client, authed }, route.id);
      break;
    case "agents":
      await (await load(() => import("./views/agents"))).renderAgents(staging, { client, authed });
      break;
    case "agent":
      await (await load(() => import("./views/agents"))).renderAgentDetail(staging, { client, authed }, route.id);
      break;
    case "machines":
      await (await load(() => import("./views/machines"))).renderMachines(staging, { client, baseUrl, authed });
      break;
    case "accounts":
      await (await load(() => import("./views/accounts"))).renderAccounts(staging, { client, authed });
      break;
    case "admin":
      await (await load(() => import("./views/admin"))).renderAdmin(staging, { client, authed });
      break;
    case "adminMeasures":
      await (await load(() => import("./views/infraMeasures"))).renderInfraMeasures(staging, { client, authed });
      break;
    case "decisions":
      await (await load(() => import("./views/decisionsV2"))).renderDecisionsV2(staging, { client, authed });
      break;
    case "transfers":
      await (await load(() => import("./views/transfers"))).renderTransfers(staging, { client, authed });
      break;
    case "vault":
      await (await load(() => import("./views/vault"))).renderVault(staging, { client, authed });
      break;
    case "vaultDetail":
      await (await load(() => import("./views/vault"))).renderVaultDetail(staging, { client, authed }, route.id);
      break;
    case "vaultAtlas":
      await (await load(() => import("./views/vaultAtlas"))).renderVaultAtlas(staging, { client, authed });
      break;
    case "library":
      await (await load(() => import("./views/library"))).renderLibrary(staging, { client, authed }, route.kind);
      break;
    case "libraryDetail":
      await (await load(() => import("./views/library"))).renderLibraryDetail(staging, { client, authed }, route.kind, route.id);
      break;
    case "configRuntimes":
      await (await load(() => import("./views/configuration"))).renderRuntimes(staging, { client, authed });
      break;
    case "configRuntime":
      await (await load(() => import("./views/configuration"))).renderRuntimeDetail(staging, { client, authed }, route.id);
      break;
    case "configBindings":
      await (await load(() => import("./views/configuration"))).renderBindings(staging, { client, authed });
      break;
    case "configApplication":
      await (await load(() => import("./views/application"))).renderApplication(staging);
      break;
    case "configIntegrations":
      await (await load(() => import("./views/integrations"))).renderIntegrations(staging, route.workspaceId);
      break;
    case "workspaces":
      await (await load(() => import("./views/workspacesPage"))).renderWorkspaces(staging, getPlatform(), { client, authed });
      break;
    case "subscription":
      (await load(() => import("./views/subscription"))).renderSubscription(staging, getActiveStudio()?.role ?? "owner", { baseUrl });
      break;
    case "help":
      (await load(() => import("./views/help"))).renderHelp(staging);
      break;
    case "studios":
      await (await load(() => import("./views/studioPicker"))).renderStudioPicker(staging, { baseUrl, authed }, route.create === true);
      break;
    case "studioInvitations":
      await (await load(() => import("./views/studioInvitations"))).renderStudioInvitations(staging, { baseUrl, authed });
      break;
    case "invitationAccept":
      await (await load(() => import("./views/studioInvitations"))).renderInvitationAccept(staging, { baseUrl }, route);
      break;
    case "studioSuspended":
      await (await load(() => import("./views/studioSuspended"))).renderStudioSuspended(staging, { baseUrl, authed }, route.id);
      break;
    case "studioData":
      await (await load(() => import("./views/studioData"))).renderStudioData(staging, { baseUrl, authed }, route.id);
      break;
    case "onboarding":
      await (await load(() => import("./onboarding/view"))).renderOnboarding(staging, getPlatform());
      break;
    case "configProject":
      await (await load(() => import("./views/configuration"))).renderProjectConfig(staging, { client, authed }, route.tab);
      break;
    case "inspector":
      await (await load(() => import("./views/inspector"))).renderInspector(staging, { client, authed, stableKey: route.stableKey });
      break;
    case "designSystem":
      (await load(() => import("./views/designSystem"))).renderDesignSystem(staging);
      break;
    case "notFound":
      (await load(() => import("./views/notFound"))).renderNotFound(staging, route.hash);
      break;
    case "dashboard":
    default:
      await (await load(() => import("./views/overview"))).renderOverview(staging, { client, baseUrl, authed });
      break;
  }
}

async function render(): Promise<void> {
  const my = renderGuard.next();
  // Ancienne adresse (lien partagé, favori) : réécrite sans entrée d'historique.
  const canonical = canonicalHash(location.hash);
  if (canonical !== location.hash && parseRoute(location.hash).name !== "notFound") history.replaceState(null, "", canonical);
  const route = parseRoute(location.hash);
  // Le flux temps réel (et l'état « direct perdu » de Mission Control) suit le
  // projet affiché, sans toucher à la sélection globale.
  displayedProjectId = route.name === "project" ? route.id : null;
  syncRealtimeConnection();
  // Premier lancement (Desktop seul) : l'assistant de configuration est
  // prioritaire tant qu'il n'est pas terminé ; la reprise revalide l'état
  // réel au lieu de supposer l'étape mémorisée encore valide.
  if (getDesktopShell() !== null) {
    const redirect = onboardingRedirect(
      loadOnboardingState().status,
      route.name === "onboarding",
    );
    if (redirect !== null) {
      location.hash = redirect;
      return;
    }
  }
  const baseUrl = resolveApiUrl(apiBaseUrl());
  const client = createApiClient(baseUrl);
  const authed = hasToken();
  if (authed) await loadActorNames(client);
  const staging = document.createElement("main");
  // A5 : un compte actif sans aucun projet voit « En attente d'accès » à
  // l'Accueil plutôt qu'un tableau de bord vide (#/projets garde l'état
  // vide explicite A0).
  const awaiting = authed && route.name === "dashboard" && (await projectAccess(client)) === "none";
  if (awaiting) {
    renderAwaitingAccess(staging, () => void render());
  } else {
    try {
      // Le chunk arrive après un délai : une navigation plus récente ou une
      // session terminée entre-temps (401 → écran de connexion) ne doit plus
      // déclencher les appels API de la vue.
      const load: LoadView = async (importer) => {
        const module = await lazyView(importer);
        if (!renderGuard.isCurrent(my) || (authed && !hasToken())) throw new StaleRender();
        return module;
      };
      await renderRoute(staging, route, { client, baseUrl, authed, load });
    } catch (error) {
      if (error instanceof StaleRender) return;
      if (!(error instanceof ViewLoadError)) throw error;
      renderViewLoadError(staging, () => location.reload());
    }
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
  paintNavAndConnection(route, authed);
  paintShellStatus(document);
  void syncSuspendedBanner(baseUrl, authed, route.name === "studioSuspended");
}

let conflictBannerTimer: ReturnType<typeof setTimeout> | null = null;

function showConflictBanner(event: EventEnvelope): void {
  const banner = document.getElementById("conflict-banner");
  if (banner === null) return;
  const resourcePath = typeof event.payload?.["resource_path"] === "string" ? event.payload["resource_path"] : "ressource inconnue";
  banner.textContent = `Conflit de ressource : ${resourcePath}`;
  banner.hidden = false;
  if (conflictBannerTimer !== null) clearTimeout(conflictBannerTimer);
  conflictBannerTimer = setTimeout(() => {
    banner.hidden = true;
    conflictBannerTimer = null;
  }, 8000);
}

/** 403 on the live stream: no access to the selected project. Stays visible
 * (no timer) — the stream will not retry until the project or token changes. */
function showStreamDeniedBanner(): void {
  const banner = document.getElementById("conflict-banner");
  if (banner === null) return;
  if (conflictBannerTimer !== null) {
    clearTimeout(conflictBannerTimer);
    conflictBannerTimer = null;
  }
  banner.textContent = "Accès à ce projet refusé : les mises à jour en direct sont arrêtées. Demandez l'accès à un administrateur.";
  banner.hidden = false;
  streamDeniedShown = true;
}

let streamDeniedShown = false;

function clearStreamDeniedBanner(): void {
  if (!streamDeniedShown) return;
  streamDeniedShown = false;
  const banner = document.getElementById("conflict-banner");
  if (banner !== null) banner.hidden = true;
}

let realtimeConnection: RealtimeConnection | null = null;
let realtimeKey: string | null = null;
let liveState: LiveState = "off";
let displayedProjectId: string | null = null;

/** One live connection per tab, opened/closed as the selected project or
 * token changes — never per-view (the backend has exactly one stream per
 * project, `project` required, DEC-0018). Every live message triggers the
 * same `render()` a manual navigation would (debounced in realtime.ts). */
function syncRealtimeConnection(): void {
  const token = getToken();
  const projectId = displayedProjectId ?? uiState.selectedProjectId;
  const key = token !== null && projectId !== null ? `${projectId}::${token}` : null;
  if (key === realtimeKey) return;
  clearStreamDeniedBanner();
  realtimeConnection?.close();
  realtimeConnection = null;
  realtimeKey = key;
  liveState = "off";
  window.dispatchEvent(new CustomEvent(LIVE_CHANGE_EVENT));
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
      onDenied: (status) => {
        // 401 is already handled by the shell (session expired, apiEvents).
        if (status === 403) showStreamDeniedBanner();
      },
      onLiveChange: (live) => {
        // Pas de re-rendu complet (focus, modales) : la vue concernée écoute.
        liveState = live ? "live" : "lost";
        window.dispatchEvent(new CustomEvent(LIVE_CHANGE_EVENT));
      },
    },
  );
}

/**
 * Après un changement de vue, le nœud #view est remplacé : sans reprise de
 * focus, il retombe sur <body> et l'utilisateur clavier/lecteur d'écran perd
 * le point de reprise. On focalise le repère principal (même cible que le
 * skip-link) — jamais un titre de contenu, pour ne pas déplacer le curseur
 * de lecture dans la page. Réservé aux navigations explicites (hashchange) :
 * le rendu initial et les re-rendus temps réel ne volent jamais le focus,
 * pour préserver le premier Tab vers le skip-link (invariant UI-2/UI-13).
 * Une nouvelle page démarre en haut : sans remise à zéro, le défilement de la
 * vue précédente subsiste et le titre reste masqué (sous la barre collante).
 */
function focusView(): void {
  window.scrollTo(0, 0);
  document.getElementById("view")?.focus({ preventScroll: true });
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

/**
 * Coque Atelier (R2, fiche E1) : navigation selon le rôle du studio actif,
 * connexion web prouvée par sonde /healthz (jamais un défaut).
 *
 * `webReachable` : null = sonde en cours (« Connexion… »), true = « Connecté »,
 * false = « Serveur injoignable » + Réessayer. Le Desktop garde son propre
 * moniteur (paintShellStatus repeint après nous).
 */
let webReachable: boolean | null = null;

function studioRole(): "owner" | "admin" | "member" | "viewer" {
  return getActiveStudio()?.role ?? "owner";
}

function studioPlan(): string {
  return getActiveStudio()?.plan ?? "Gratuit";
}

/** État de connexion côté navigateur : jeton + sonde serveur réelle. */
export function webConnectionView(authed: boolean): Parameters<typeof paintConnection>[0] {
  if (!authed) return { level: "info", label: "Non connecté" };
  if (webReachable === false) {
    return {
      level: "error",
      label: "Serveur injoignable",
      title: "Serveur injoignable — vos modifications sont gardées sur cet appareil et partiront au retour de la connexion.",
      action: { kind: "retry", label: "Réessayer" },
    };
  }
  if (webReachable === null) return { level: "info", label: "Connexion…" };
  return { level: "ok", label: "Connecté" };
}

function paintNavAndConnection(route: Route, authed: boolean): void {
  syncNav(route, document, getDesktopShell() !== null, loadUiMode(), studioRole(), studioPlan());
  const crumbSlot = document.getElementById("breadcrumb-slot");
  if (crumbSlot !== null) crumbSlot.innerHTML = breadcrumbHtml(route);
  if (getDesktopShell() === null) paintConnection(webConnectionView(authed), document);
  else syncAuthState(authed, document);
}

/** Sonde /healthz puis repeint l'unique indicateur (web uniquement). */
async function probeWebServer(baseUrl: string, authed: boolean): Promise<void> {
  if (getDesktopShell() !== null || !authed) return;
  webReachable = null;
  paintConnection(webConnectionView(true), document);
  webReachable = await probeServer(baseUrl);
  paintConnection(webConnectionView(true), document);
}

/** Menu du sélecteur : Entrée/flèches/Échap (E1), choix sans rechargement. */
function setStudioMenu(open: boolean, focusFirst = false): void {
  const button = document.getElementById("studio-button");
  const menu = document.getElementById("studio-menu");
  if (button === null || menu === null) return;
  button.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) {
    menu.hidden = false;
    if (focusFirst) menu.querySelector<HTMLButtonElement>("[role='menuitemradio']")?.focus();
  } else {
    menu.hidden = true;
  }
}

function studioOptions(): HTMLButtonElement[] {
  return [...document.querySelectorAll<HTMLButtonElement>("#studio-menu [role='menuitemradio']")];
}

function focusStudioOption(current: Element | null, delta: number): void {
  const options = studioOptions();
  if (options.length === 0) return;
  const index = options.findIndex((option) => option === current);
  const next = options[(index + delta + options.length) % options.length];
  next?.focus();
}

/** Charge les studios, peint le sélecteur, câble menu + réessais. */
function mountStudioSelector(client: ReturnType<typeof createApiClient>): void {
  syncStudioSelector(document, { status: "loading" });
  void listStudios(client as unknown as StudiosClient).then(
    (result) => {
      setStudios(result.studios);
      const active = getActiveStudio();
      if (active === null) {
        syncStudioSelector(document, { status: "error" });
        return;
      }
      syncStudioSelector(document, { status: "ready", studios: result.studios, activeId: active.id });
      // La barre dépend du rôle (Abonnement) et du plan (pastille) : repeint.
      paintNavAndConnection(parseRoute(location.hash), hasToken());
      mountPalette(() => paletteEntries(parseRoute(location.hash), getDesktopShell() !== null, studioRole(), studioPlan(), loadUiMode(), () => switchUiMode(toggledUiMode(loadUiMode()))));
    },
    () => {
      syncStudioSelector(document, { status: "error" });
    },
  );

  const slot = document.getElementById("studio-slot");
  if (slot === null || slot.hasAttribute("data-studio-wired")) return;
  slot.setAttribute("data-studio-wired", "true");
  slot.addEventListener("click", (event) => {
    const target = event.target as Element | null;
    const button = target?.closest("#studio-button");
    if (button !== null) {
      const menu = document.getElementById("studio-menu");
      setStudioMenu(menu?.hidden ?? false, true);
      return;
    }
    if (target?.closest("#studio-retry") !== null) {
      mountStudioSelector(client);
      return;
    }
    const option = target?.closest<HTMLButtonElement>("[data-studio-id]");
    if (option !== null) {
      const chosen = selectStudio(option.dataset["studioId"] ?? "");
      if (chosen !== null) {
        // Changement sans rechargement : la barre (rôle/plan) puis la vue.
        mountShell();
        document.getElementById("studio-button")?.focus();
      }
    }
  });
  slot.addEventListener("keydown", (event) => {
    if (!(event instanceof KeyboardEvent)) return;
    const target = event.target as Element | null;
    if (target?.closest("#studio-button") !== null && (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      setStudioMenu(true, true);
      return;
    }
    if (target?.closest("#studio-menu") === null) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setStudioMenu(false);
      document.getElementById("studio-button")?.focus();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      focusStudioOption(target, 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusStudioOption(target, -1);
    } else if (event.key === "Home") {
      event.preventDefault();
      studioOptions()[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      studioOptions().at(-1)?.focus();
    }
  });
  // Clic ailleurs : referme le menu sans voler le focus.
  document.addEventListener("click", (event) => {
    const menu = document.getElementById("studio-menu");
    if (menu === null || menu.hidden) return;
    if ((event.target as Element | null)?.closest("#studio-slot") === null) setStudioMenu(false);
  });
}

function mountShell(): void {
  const app = document.getElementById("app");
  if (app === null) throw new Error("#app missing");
  applyUiMode(loadUiMode());
  app.innerHTML = shellHtml(
    parseRoute(location.hash),
    hasToken(),
    getDesktopShell() !== null,
    loadUiMode(),
    loadThemeMode(),
  );
  paintShellStatus(document);
  mountSkillsSync(getPlatform());
  paintUpdateBanner(document);
  mountPalette(() => paletteEntries(parseRoute(location.hash), getDesktopShell() !== null, studioRole(), studioPlan(), loadUiMode(), () => switchUiMode(toggledUiMode(loadUiMode()))));
  mountAdminFlyout();
  const shellClient = createApiClient(resolveApiUrl(apiBaseUrl()));
  mountStudioSelector(shellClient);
  if (getDesktopShell() === null && hasToken()) void probeWebServer(resolveApiUrl(apiBaseUrl()), true);

  // Thème : le choix est appliqué aussitôt (aucun re-rendu nécessaire) et
  // mémorisé sur le poste ; « système » retire l'attribut, le CSS décide.
  const themeSelect = document.getElementById("theme-select");
  if (themeSelect instanceof HTMLSelectElement) {
    themeSelect.addEventListener("change", () => {
      const value = themeSelect.value;
      const mode = isThemeMode(value) ? value : "system";
      saveThemeMode(mode);
      applyThemeMode(mode);
    });
  }
  document.getElementById("nav-open")?.addEventListener("click", () => openDrawer());
  document.getElementById("nav-close")?.addEventListener("click", () => closeDrawer());
  document.getElementById("app-scrim")?.addEventListener("click", () => closeDrawer());
  app.querySelector(".ds-skip-link")?.addEventListener("click", (event) => {
    event.preventDefault();
    document.getElementById("view")?.focus();
  });
  if (!shellListenersMounted) {
    shellListenersMounted = true;
    watchExpertMode(app, loadUiMode);
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !isDrawerOpen()) return;
      if ((event.target as HTMLElement | null)?.closest(".ds-overlay") !== null) return;
      closeDrawer();
    });
    subscribe(() => {
      syncRealtimeConnection();
      void render();
    });
    // « Réessayer » de l'indicateur web : re-sonde le serveur, sans recharger.
    document.addEventListener("click", (event) => {
      const retry = (event.target as Element | null)?.closest('[data-action="retry-status"]');
      if (retry === null || retry === undefined) return;
      if (getDesktopShell() !== null) return;
      void probeWebServer(resolveApiUrl(apiBaseUrl()), hasToken());
    });
    // Changement de studio (sélecteur) : repeint la vue courante, sans recharger.
    window.addEventListener(STUDIO_CHANGE_EVENT, () => {
      void render();
    });
    window.addEventListener("hashchange", () => {
      if (isDrawerOpen()) closeDrawer(false);
      if (isPaletteOpen()) closePalette(false);
      // Le rendu est asynchrone (chunk de vue + API) : si l'utilisateur a rouvert
      // la palette entre-temps, on ne lui reprend pas le focus.
      void render().then(() => {
        if (!isPaletteOpen()) focusView();
      });
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
    void endPersistentSession();
    void forgetLocalIdentity(getPlatform());
    clearToken();
    syncRealtimeConnection();
    getDesktopShell()?.monitor.clearAuthExpired();
    mountLogin();
  });

  syncRealtimeConnection();
  // Rendu initial : focus laissé au navigateur (le premier Tab atteint le
  // skip-link, invariant UI-2/UI-13). Seules les navigations explicites
  // (hashchange) reprennent le focus sur #view, jamais les re-rendus.
  void render();
}

function mountLogin(notice?: string): void {
  const app = document.getElementById("app");
  if (app === null) throw new Error("#app missing");
  app.innerHTML = loginOverlayHtml();
  renderLogin(
    app,
    () => {
      const desktop = getDesktopShell();
      if (desktop !== null) {
        desktop.monitor.clearAuthExpired();
        void desktop.monitor.check();
      }
      syncRealtimeConnection();
      mountShell();
    },
    {
      notice,
      desktop: getDesktopShell() !== null,
      onServerChange: () => void mountLogin(),
      onAccountAction: (action) => {
        history.replaceState(null, "", PUBLIC_HASH[action]);
        mountPublic({ name: action });
      },
    },
  );
}

/** A5 : écrans publics (inscription, vérification, récupération), sans token. */
function mountPublic(screen: PublicScreen): void {
  const app = document.getElementById("app");
  if (app === null) throw new Error("#app missing");
  renderPublicAccount(app, screen, {
    client: createApiClient(resolveApiUrl(apiBaseUrl())),
    go: mountPublic,
    toLogin: () => {
      if (publicHashScreen(location.hash) !== null) history.replaceState(null, "", location.pathname);
      mountLogin();
    },
  });
}

/** Emailed link or shareable pre-login address: mounted instead of the login. */
function publicEntry(): PublicScreen | null {
  const link = readAccountLink(location.pathname, location.hash);
  if (link !== null) {
    // The secret leaves the address bar and history before anything else.
    history.replaceState(null, "", scrubbedPath(location.pathname));
    if (link.token === null) return { name: "failure", kind: "invalid_or_expired_token", flow: link.kind };
    return link.kind === "verify" ? { name: "verify", token: link.token } : { name: "reset", token: link.token };
  }
  const screen = publicHashScreen(location.hash);
  return screen !== null && !hasToken() ? { name: screen } : null;
}

function start(): void {
  const entry = publicEntry();
  if (entry !== null) {
    mountPublic(entry);
    return;
  }
  // Sans compte, l'écran de connexion couvre tout — sauf au premier lancement
  // Desktop, où l'assistant embarque sa propre connexion (étape « Connexion »).
  const desktop = getDesktopShell() !== null;
  const onboardingStatus = loadOnboardingState().status;
  if (desktop) {
    const redirect = onboardingRedirect(
      onboardingStatus,
      parseRoute(location.hash).name === "onboarding",
    );
    if (redirect !== null) location.hash = redirect;
  }
  const firstRun = desktop && onboardingStatus !== "completed" && onboardingStatus !== "skipped";
  if (hasToken() || firstRun) {
    mountShell();
  } else {
    mountLogin();
  }
}

export function boot(): void {
  // Thème appliqué avant le premier rendu (le choix stocké prime sur la
  // préférence système, qui reste le défaut).
  applyThemeMode(loadThemeMode());
  const platform = getPlatform();
  if (platform.mode !== "desktop") {
    setApiObserver({
      unauthorized: createSessionEndHandler((notice) => {
        syncRealtimeConnection();
        mountLogin(notice);
      }),
      // Web Dashboard: no connection monitor, but the C1 compatibility surfaces
      // must still work (advisory banner, blocking screen on 426).
      clientUpdate: (latest) => showClientUpdateAdvisory(latest),
      upgradeRequired: (info) => showUpgradeRequired(info),
    });
    start();
    return;
  }
  // Desktop only: learn the server origin before the first API call.
  void prepareDesktop(platform).then(async () => {
    setDesktopHooks({
      rerender: () => void render(),
      authExpired: () => {
        // A persistent session (DEC-0142) renews silently; only a refused or
        // unreachable renewal falls back to the sign-in screen.
        void refreshSession().then((outcome) => {
          const desktop = getDesktopShell();
          if (outcome === "refreshed" && desktop !== null) {
            desktop.monitor.clearAuthExpired();
            void desktop.monitor.check();
            syncRealtimeConnection();
            void render();
            return;
          }
          clearToken();
          resetIdentityCache();
          syncRealtimeConnection();
          mountLogin(SESSION_ENDED_NOTICE);
        });
      },
    });
    configurePersistentSession(platform.sessionVault);
    await resumeSession();
    start();
    void checkUpdateAtStart(platform);
    void checkWhatsNewAtStart(platform);
  });
}

boot();
