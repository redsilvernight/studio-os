/**
 * P11 — assistant de configuration (first-run) de Studi'OS Desktop.
 *
 * Orchestration UX au-dessus des capacités P0→P10 : chaque étape réutilise la
 * surface existante (origine serveur, login, pont `workspace.*`, mémoire,
 * harnais) et revalide l'état réel au lieu de recopier un booléen du wizard.
 * Vocabulaire utilisateur, aucune saisie d'UUID, aucun secret affiché ou
 * stocké, aucun chemin complet conservé.
 */
import { apiBaseUrl, createApiClient } from "../api";
import { hasToken } from "../auth";
import { joinUrl } from "../config";
import { getDesktopShell } from "../desktopShell";
import { daemonLabel } from "../shellStatus";
import { dsBadge, dsEmptyState, dsPageHeader } from "../ds/ds";
import {
  applyHarness,
  CHANGE_LABELS,
  detectHarnesses,
  harnessErrorMessage,
  previewHarness,
  STATE_LABELS,
  STATE_TONES,
  type HarnessPlan,
  type HarnessStatus,
} from "../harnessApi";
import { loginOverlayHtml, renderLogin } from "../login";
import { getPlatform, type Platform } from "../platform";
import type {
  IdentityView,
  KnowledgeStatus,
  LocalError,
} from "../platform/generated/local-contracts.generated";
import { esc } from "../ui";
import { originRefusalMessage } from "../views/application";
import { toWorkspaceViewModel } from "../workspaces/workspaces";
import { pickWorkspaceFolder, type FolderPickOutcome } from "../views/workspacesPage";
import { createProject, type Project } from "../creationsApi";
import { newIdempotencyKey } from "../claimsApi";
import { ONBOARDING_STEPS, nextStep, previousStep, stepById, type OnboardingStep } from "./steps";
import {
  loadOnboardingState,
  saveOnboardingState,
  type OnboardingState,
  type OnboardingStepId,
} from "./state";
import {
  confirmRoots,
  gitStatusMessage,
  saveWorkspaceConfig,
  validateWorkspace,
  workspaceErrorMessage,
  workspaceGitStatus,
  workspaceHealthMessage,
} from "./workspaceApi";

export function onboardingWebHtml(): string {
  return (
    dsPageHeader("Assistant de configuration", "Premier lancement de Studi'OS Desktop.") +
    `<section class="settings-domain" data-testid="onboarding-web">` +
    dsEmptyState(
      "Disponible dans Studi'OS Desktop",
      "La configuration locale (dossier, mémoire, assistant IA) se fait sur le poste, depuis l'application Studi'OS Desktop. Ce tableau de bord web reste autonome.",
    ) +
    `</section>`
  );
}

/** UUID local frais pour un dossier jamais associé (identifiant, pas un secret). */
export function newWorkspaceId(): string {
  try {
    const random = globalThis.crypto?.randomUUID?.();
    if (typeof random === "string" && random.length > 0) return random;
  } catch {
    // Repli ci-dessous : l'identifiant reste unique par session.
  }
  const part = (): string => Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, "0");
  const raw = `${part()}${part()}`;
  return `${raw.slice(0, 8)}-${raw.slice(8, 12)}-4${raw.slice(13, 16)}-8${raw.slice(17, 20)}-${raw.slice(20, 32)}`;
}

function utcNow(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function progressHtml(current: OnboardingStepId): string {
  const items = ONBOARDING_STEPS.filter((step) => step.id !== "termine")
    .map((step) => {
      const at = ONBOARDING_STEPS.findIndex((s) => s.id === current);
      const mine = ONBOARDING_STEPS.findIndex((s) => s.id === step.id);
      const state = step.id === current ? " (étape en cours)" : mine < at ? " (terminée)" : "";
      const aria = step.id === current ? ' aria-current="step"' : "";
      return `<li${aria}>${esc(step.title)}<span class="ds-sr-only">${state}</span></li>`;
    })
    .join("");
  return `<nav aria-label="Progression de l'assistant"><ol class="onboarding-progress" data-testid="onboarding-progress">${items}</ol></nav>`;
}

function layout(step: OnboardingStep, current: OnboardingStepId, body: string): string {
  return (
    dsPageHeader("Assistant de configuration", "Premier lancement de Studi'OS Desktop.") +
    progressHtml(current) +
    `<section class="settings-domain" data-testid="onboarding-step" data-step="${esc(step.id)}">` +
    `<h2>${esc(step.heading)}</h2><p class="settings-intro">${esc(step.intro)}</p>${body}</section>`
  );
}

function navButtons(options: { prev?: OnboardingStepId | null; prevLabel?: string; extra?: string } = {}): string {
  const prev =
    options.prev === undefined || options.prev === null
      ? ""
      : `<button class="ds-btn" type="button" data-action="prev" data-step="${esc(options.prev)}">${esc(options.prevLabel ?? "Précédent")}</button>`;
  return `<div class="settings-actions">${prev}${options.extra ?? ""}</div>`;
}

function errorHtml(message: string | null): string {
  return message ? `<p class="ds-field-error" role="alert" data-testid="onboarding-error">${esc(message)}</p>` : "";
}

function noticeHtml(message: string | null): string {
  return message ? `<p class="settings-notice" role="status" data-testid="onboarding-notice">${esc(message)}</p>` : "";
}

export interface SessionData {
  state: OnboardingState;
  serverProbe: { ok: boolean; detail: string } | null;
  identity: IdentityView | null;
  identityError: string | null;
  projects: Project[] | null;
  projectsError: string | null;
  folder: FolderPickOutcome | null;
  statusText: string | null;
  gitText: string | null;
  knowledgeText: string | null;
  codeText: string | null;
  harnesses: HarnessStatus[] | null;
  harnessError: string | null;
  plan: HarnessPlan | null;
  error: string | null;
  notice: string | null;
  restartRequired: boolean;
}

async function probeServer(): Promise<{ ok: boolean; detail: string }> {
  const base = apiBaseUrl();
  if (!base) return { ok: false, detail: "Aucune adresse configurée." };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await globalThis.fetch(joinUrl(base, "/healthz"), {
      method: "GET",
      cache: "no-store",
      signal: controller.signal,
    });
    if (response.ok) return { ok: true, detail: "Serveur joint." };
    if (response.status === 401 || response.status === 403) return { ok: true, detail: "Serveur joint (connexion requise)." };
    return { ok: false, detail: `Le serveur répond ${response.status}.` };
  } catch {
    return { ok: false, detail: "Impossible de joindre le serveur." };
  } finally {
    clearTimeout(timer);
  }
}

async function readIdentity(platform: Platform): Promise<{ view: IdentityView | null; error: string | null }> {
  const answer = await platform.request("identity.get_view", {});
  if (!answer.ok) return { view: null, error: workspaceErrorMessage(answer.error) };
  const view = answer.response.payload as unknown as IdentityView;
  const secret = view.secrets?.[0];
  if (!secret) return { view, error: "État du poste illisible." };
  if (secret.status === "present") return { view, error: null };
  if (secret.status === "absent") return { view, error: "Ce poste n'est pas encore enregistré." };
  return { view, error: "Le trousseau du système est indisponible." };
}

function persist(data: SessionData): void {
  saveOnboardingState(data.state);
}

function go(data: SessionData, step: OnboardingStepId): void {
  data.state = { ...data.state, status: "in_progress", current: step };
  data.error = null;
  persist(data);
}

/** Revalide l'état réel à la reprise : un booléen du wizard ne vaut jamais une preuve. */
export async function revalidate(data: SessionData, platform: Platform): Promise<void> {
  data.error = null;
  const id = data.state.workspaceId;
  if (!id) return;
  const checked = await validateWorkspace(platform, id);
  if (!checked.ok) {
    data.state = { ...data.state, workspaceId: undefined, folderName: undefined, current: "dossier" };
    data.error = "Le dossier associé n'est plus valide : choisissez-le à nouveau.";
    persist(data);
    return;
  }
  if (checked.value.health !== "valid") {
    data.state = { ...data.state, current: "dossier" };
    data.error = `Le dossier associé demande une action : ${workspaceHealthMessage(checked.value)}`;
    persist(data);
  }
}

function knowledgeMessage(status: KnowledgeStatus | null, error: LocalError | null): string {
  if (error) {
    if (error.code === "workspace_config_missing") return "Aucun dossier associé : la mémoire sera proposée après l'association.";
    return "Mémoire indisponible pour l'instant.";
  }
  if (!status) return "État de la mémoire inconnu.";
  const index = status.index?.state;
  switch (status.state) {
    case "ready":
      if (index === "ready") return "Mémoire prête.";
      if (index === "absent") return "Mémoire vide : aucun document indexé pour l'instant.";
      if (index === "indexing") return "Mémoire en cours d'indexation…";
      if (index === "corrupt") return "Index illisible : relancez l'indexation depuis les graphes.";
      return "Mémoire prête.";
    case "disabled":
      return "Mémoire désactivée pour ce dossier.";
    case "indexing":
      return "Mémoire en cours d'indexation…";
    case "unavailable":
      return "Mémoire indisponible : vérifiez le dossier de la mémoire.";
    default:
      return "Mémoire indisponible pour l'instant.";
  }
}

async function readKnowledge(platform: Platform, workspaceId: string): Promise<{ text: string; raw: KnowledgeStatus | null }> {
  const answer = await platform.request("knowledge.status", { workspace_id: workspaceId });
  if (!answer.ok) return { text: knowledgeMessage(null, answer.error), raw: null };
  const raw = answer.response.payload as unknown as KnowledgeStatus;
  return { text: knowledgeMessage(raw, null), raw };
}

async function readCodeGraph(platform: Platform, workspaceId: string): Promise<string> {
  const answer = await platform.request("code_graph.status", { workspace_id: workspaceId });
  if (!answer.ok) {
    if (answer.error.code === "not_supported" || answer.error.code === "capability_missing") {
      return "Analyse avancée du code indisponible.";
    }
    return "Analyse du code indisponible pour l'instant.";
  }
  const raw = answer.response.payload as { state?: string; provider?: { provider_id?: string } | null };
  if (raw.state === "ready") return "Analyse du code prête.";
  if (raw.state === "not_installed") return "Analyse avancée du code indisponible (composant non installé).";
  if (raw.state === "indexing") return "Analyse du code en cours d'indexation…";
  if (raw.state === "disabled") return "Analyse du code désactivée pour ce dossier.";
  return "Analyse du code indisponible pour l'instant.";
}

export async function renderOnboarding(
  root: HTMLElement,
  platform: Platform = getPlatform(),
  data: SessionData | null = null,
): Promise<void> {
  if (platform.mode === "web") {
    root.innerHTML = onboardingWebHtml();
    return;
  }
  const session: SessionData = data ?? {
    state: loadOnboardingState(),
    serverProbe: null,
    identity: null,
    identityError: null,
    projects: null,
    projectsError: null,
    folder: null,
    statusText: null,
    gitText: null,
    knowledgeText: null,
    codeText: null,
    harnesses: null,
    harnessError: null,
    plan: null,
    error: null,
    notice: null,
    restartRequired: false,
  };
  if (data === null && session.state.status === "in_progress") await revalidate(session, platform);
  const again = (): Promise<void> => renderOnboarding(root, platform, session);
  const step = stepById(session.state.current);

  switch (session.state.current) {
    case "bienvenue":
      return paintBienvenue(root, platform, session, again);
    case "connexion":
      return paintConnexion(root, platform, session, again);
    case "verification":
      return paintVerification(root, platform, session, again);
    case "projet":
      return paintProjet(root, platform, session, again);
    case "dossier":
      return paintDossier(root, platform, session, again);
    case "memoire":
      return paintMemoire(root, platform, session, again);
    case "environnement":
      return paintEnvironnement(root, platform, session, again);
    case "assistant":
      return paintAssistant(root, platform, session, again);
    case "final":
      return paintFinal(root, platform, session, again);
    case "termine":
    default:
      return paintTermine(root, platform, session, again, step);
  }
}

/** Session vierge (les étapes rechargent l'état réel à l'affichage). */
export function emptySession(state: OnboardingState): SessionData {
  return {
    state,
    serverProbe: null,
    identity: null,
    identityError: null,
    projects: null,
    projectsError: null,
    folder: null,
    statusText: null,
    gitText: null,
    knowledgeText: null,
    codeText: null,
    harnesses: null,
    harnessError: null,
    plan: null,
    error: null,
    notice: null,
    restartRequired: false,
  };
}

async function paintBienvenue(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  const step = stepById("bienvenue");
  let detected = false;
  try {
    const origin = await platform.serverOrigin();
    const id = session.state.workspaceId;
    if (origin?.applied && id) {
      const checked = await validateWorkspace(platform, id);
      detected = checked.ok && checked.value.health === "valid";
    }
  } catch {
    detected = false;
  }
  const body =
    detected && session.state.status !== "not_started"
      ? `<p class="settings-notice" role="status">Votre configuration Studi'OS est déjà détectée.</p>` +
        navButtons({
          extra:
            `<button class="ds-btn ds-btn--primary" type="button" data-action="finish-detected">Ouvrir le tableau de bord</button>` +
            `<button class="ds-btn" type="button" data-action="review">Revoir la configuration</button>`,
        })
      : navButtons({
        extra: `<button class="ds-btn ds-btn--primary" type="button" data-action="start">Commencer</button>`,
      });
  root.innerHTML = layout(step, "bienvenue", errorHtml(session.error) + body);
  root.querySelector("[data-action=start]")?.addEventListener("click", () => {
    go(session, "connexion");
    void again();
  });
  root.querySelector("[data-action=finish-detected]")?.addEventListener("click", () => {
    session.state = { ...session.state, status: "completed", current: "termine", completedAt: utcNow() };
    persist(session);
    location.hash = "#/";
  });
  root.querySelector("[data-action=review]")?.addEventListener("click", () => {
    go(session, "connexion");
    void again();
  });
}

async function paintConnexion(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  const step = stepById("connexion");
  let origin = null;
  try {
    origin = await platform.serverOrigin();
  } catch {
    origin = null;
  }
  const probe = session.serverProbe ?? (await probeServer());
  session.serverProbe = probe;
  const authed = hasToken();
  const body =
    errorHtml(session.error) +
    noticeHtml(session.notice) +
    (session.restartRequired
      ? `<button class="ds-btn ds-btn--primary" type="button" data-action="restart-desktop">Redémarrer maintenant</button>`
      : "") +
    `<dl class="settings-rows">` +
    `<div class="settings-row"><dt>Adresse utilisée</dt><dd><code class="mono">${esc(origin?.applied ?? "Non configurée")}</code></dd></div>` +
    `<div class="settings-row"><dt>Serveur</dt><dd data-testid="server-probe">${esc(probe.detail)}</dd></div>` +
    `<div class="settings-row"><dt>Compte</dt><dd>${authed ? "Connecté" : "Non connecté"}</dd></div>` +
    `</dl>` +
    `<form class="settings-server-form" data-testid="server-origin-form" novalidate>` +
    `<label class="settings-field">Adresse du serveur Studi'OS` +
    `<input id="server-origin-input" name="server_origin" type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://studio.exemple.com" value="${esc(origin?.configured ?? "")}" /></label>` +
    `<div class="settings-actions"><button class="ds-btn ds-btn--primary" type="submit">Enregistrer</button>` +
    `<button class="ds-btn" type="button" data-action="retry">Réessayer</button></div></form>` +
    (authed
      ? ""
      : `<div data-testid="onboarding-login">${loginOverlayHtml()}</div>`) +
    navButtons({
      prev: previousStep("connexion"),
      extra:
        `<button class="ds-btn ds-btn--primary" type="button" data-action="next" ${probe.ok && authed ? "" : "disabled"}>Continuer</button>` +
        (probe.ok ? "" : `<span class="settings-intro">La suite nécessite un serveur joint et un compte connecté. L'application reste utilisable hors ligne.</span>`),
    });
  root.innerHTML = layout(step, "connexion", body);
  root.querySelector<HTMLFormElement>("[data-testid=server-origin-form]")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = root.querySelector<HTMLInputElement>("#server-origin-input")?.value ?? "";
    void platform.setServerOrigin(value).then((result) => {
      if (!result.ok) {
        session.error = originRefusalMessage(result.reason);
        return again();
      }
      session.serverProbe = null;
      session.restartRequired = result.state.restart_required;
      session.notice = result.state.restart_required
        ? "Adresse enregistrée. Redémarrez l'application pour l'utiliser."
        : "Adresse enregistrée.";
      session.error = null;
      return again();
    });
  });
  root.querySelector("[data-action=restart-desktop]")?.addEventListener("click", () => {
    void platform.restartDesktop().then((started) => {
      if (!started) {
        session.error = "Le redémarrage n'a pas pu être lancé. Fermez puis rouvrez l'application.";
        void again();
      }
    });
  });
  root.querySelector("[data-action=retry]")?.addEventListener("click", () => {
    session.serverProbe = null;
    session.error = null;
    void again();
  });
  const loginHost = root.querySelector("[data-testid=onboarding-login]");
  if (loginHost && !authed) {
    renderLogin(loginHost as HTMLElement, () => {
      session.notice = "Connecté.";
      session.error = null;
      void again();
    });
  }
  root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
    go(session, previousStep("connexion") ?? "bienvenue");
    void again();
  });
  root.querySelector("[data-action=next]")?.addEventListener("click", () => {
    go(session, nextStep("connexion") ?? "verification");
    void again();
  });
}

async function paintVerification(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  const step = stepById("verification");
  const shell = getDesktopShell();
  const daemonText = shell ? `Assistant local : ${daemonLabel(shell.daemon)}` : "Assistant local : état inconnu.";
  const { view, error } = await readIdentity(platform);
  session.identity = view;
  session.identityError = error;
  const machineReady = error === null;
  const body =
    errorHtml(session.error) +
    `<dl class="settings-rows">` +
    `<div class="settings-row"><dt>Assistant local</dt><dd>${esc(daemonText)}</dd></div>` +
    `<div class="settings-row"><dt>Ce poste</dt><dd>${esc(error ?? "Reconnu — prêt à travailler.")}</dd></div>` +
    `</dl>` +
    (machineReady
      ? ""
      : `<p class="settings-intro">Si une action est nécessaire côté serveur, faites-la valider puis revenez ici avec « Revérifier ».</p>`) +
    navButtons({
      prev: previousStep("verification"),
      extra:
        `<button class="ds-btn" type="button" data-action="recheck">Revérifier</button>` +
        `<button class="ds-btn ds-btn--primary" type="button" data-action="next" ${machineReady ? "" : "disabled"}>Continuer</button>`,
    });
  root.innerHTML = layout(step, "verification", body);
  root.querySelector("[data-action=recheck]")?.addEventListener("click", () => {
    session.error = null;
    void again();
  });
  root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
    go(session, previousStep("verification") ?? "connexion");
    void again();
  });
  root.querySelector("[data-action=next]")?.addEventListener("click", () => {
    go(session, nextStep("verification") ?? "projet");
    void again();
  });
}

async function paintProjet(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  const step = stepById("projet");
  void platform;
  if (!hasToken()) {
    root.innerHTML = layout(
      step,
      "projet",
      `<p class="ds-field-error" role="alert">Connectez-vous d'abord (étape « Connexion »).</p>` +
        navButtons({ prev: previousStep("projet") }),
    );
    root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
      go(session, previousStep("projet") ?? "verification");
      void again();
    });
    return;
  }
  if (session.projects === null && session.projectsError === null) {
    try {
      const client = createApiClient(apiBaseUrl());
      const result = await client.GET("/api/v1/projects");
      if (result.response.ok && result.data !== undefined) {
        session.projects = result.data as Project[];
      } else {
        session.projectsError = "La liste des projets est indisponible.";
      }
    } catch {
      session.projectsError = "La liste des projets est indisponible. Vérifiez la connexion.";
    }
  }
  const list = session.projects ?? [];
  const cards = list
    .map(
      (project) =>
        `<li><label class="ds-radio"><input type="radio" name="project" value="${esc(project.id)}" ${session.state.projectId === project.id ? "checked" : ""} />` +
        `<span><strong>${esc(project.name ?? project.slug ?? "Projet")}</strong></span></label></li>`,
    )
    .join("");
  const body =
    errorHtml(session.error ?? session.projectsError) +
    noticeHtml(session.notice) +
    (list.length === 0
      ? `<p class="settings-intro">Aucun projet sur le serveur : créez-le ci-dessous.</p>`
      : `<ul class="ds-list" data-testid="project-list">${cards}</ul>`) +
    `<form class="settings-server-form" data-testid="project-create-form">` +
    `<label class="settings-field">Nom du nouveau projet<input id="project-name-input" name="project_name" type="text" autocomplete="off" maxlength="80" /></label>` +
    `<div class="settings-actions"><button class="ds-btn" type="submit">Créer</button></div></form>` +
    navButtons({
      prev: previousStep("projet"),
      extra: `<button class="ds-btn ds-btn--primary" type="button" data-action="next" ${session.state.projectId ? "" : "disabled"}>Continuer</button>`,
    });
  root.innerHTML = layout(step, "projet", body);
  session.notice = null;
  root.querySelectorAll<HTMLInputElement>('input[name=project]')?.forEach((input) => {
    input.addEventListener("change", () => {
      const chosen = list.find((project) => project.id === input.value);
      session.state = {
        ...session.state,
        projectId: input.value,
        projectName: chosen?.name ?? chosen?.slug ?? undefined,
        projectSlug: chosen?.slug ?? undefined,
      };
      persist(session);
      const next = root.querySelector<HTMLButtonElement>('[data-action=next]');
      if (next) next.disabled = false;
    });
  });
  root.querySelector<HTMLFormElement>("[data-testid=project-create-form]")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const name = (root.querySelector<HTMLInputElement>("#project-name-input")?.value ?? "").trim();
    if (!name) {
      session.error = "Indiquez un nom de projet.";
      void again();
      return;
    }
    try {
      const client = createApiClient(apiBaseUrl());
      void createProject(client, { name } as Parameters<typeof createProject>[1], newIdempotencyKey()).then(
        (created: Project) => {
          session.projects = [...(session.projects ?? []), created];
          session.state = {
            ...session.state,
            projectId: created.id,
            projectName: created.name ?? undefined,
            projectSlug: created.slug ?? undefined,
          };
          session.error = null;
          session.notice = "Projet créé.";
          persist(session);
          void again();
        },
        () => {
          session.error = "La création a échoué. Vérifiez vos droits puis réessayez.";
          void again();
        },
      );
    } catch {
      session.error = "La création a échoué. Vérifiez vos droits puis réessayez.";
      void again();
    }
  });
  root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
    go(session, previousStep("projet") ?? "verification");
    void again();
  });
  root.querySelector("[data-action=next]")?.addEventListener("click", () => {
    go(session, nextStep("projet") ?? "dossier");
    void again();
  });
}

async function paintDossier(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  const step = stepById("dossier");
  const outcome = session.folder;
  const picked = outcome?.kind === "selected" ? outcome : null;
  let statusLine = session.statusText ?? "";
  if (!statusLine && session.state.workspaceId) {
    const checked = await validateWorkspace(platform, session.state.workspaceId);
    statusLine = checked.ok ? workspaceHealthMessage(checked.value) : workspaceErrorMessage(checked.error);
    session.statusText = statusLine;
  }
  const body =
    errorHtml(session.error) +
    noticeHtml(session.notice) +
    (picked
      ? `<dl class="settings-rows"><div class="settings-row"><dt>Dossier choisi</dt><dd>${esc(picked.displayName)}</dd></div>` +
        `<div class="settings-row"><dt>État</dt><dd>${esc(statusLine || "Prêt à associer.")}</dd></div></dl>`
      : `<p class="settings-intro">Aucun dossier choisi pour l'instant.</p>`) +
    `<div class="settings-actions"><button class="ds-btn ds-btn--primary" type="button" data-action="pick">Choisir un dossier…</button></div>` +
    navButtons({
      prev: previousStep("dossier"),
      extra:
        `<button class="ds-btn" type="button" data-action="skip">Passer cette étape</button>` +
        `<button class="ds-btn ds-btn--primary" type="button" data-action="associate" ${picked ? "" : "disabled"}>Associer ce dossier</button>`,
    });
  root.innerHTML = layout(step, "dossier", body);
  session.notice = null;
  root.querySelector("[data-action=pick]")?.addEventListener("click", () => {
    void pickWorkspaceFolder(platform).then((next) => {
      session.folder = next;
      session.statusText = null;
      session.error = next.kind === "error" ? "Le dossier n'a pas pu être sélectionné." : null;
      void again();
    });
  });
  root.querySelector("[data-action=skip]")?.addEventListener("click", () => {
    go(session, nextStep("dossier") ?? "memoire");
    void again();
  });
  root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
    go(session, previousStep("dossier") ?? "projet");
    void again();
  });
  root.querySelector("[data-action=associate]")?.addEventListener("click", () => {
    if (!picked) return;
    associateFolder(root, platform, session, picked.path, picked.displayName, again).catch(() => {
      session.error = "L'opération a échoué. Aucune modification n'a été confirmée.";
      void again();
    });
  });
}

async function associateFolder(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  path: string,
  displayName: string,
  again: () => Promise<void>,
): Promise<void> {
  session.error = null;
  const projectId = session.state.projectId;
  if (!projectId) {
    session.error = "Choisissez d'abord un projet.";
    return again();
  }
  const identity = session.identity ?? (await readIdentity(platform)).view;
  const profile = identity?.profile;
  if (!profile) {
    session.error = "Ce poste n'est pas reconnu. Revenez à l'étape « Vérification ».";
    return again();
  }
  const roots = { workspace_root: path, repo_roots: [] as { name: string; path: string }[] };
  // Le pont exige une confirmation liée à ces racines exactes : l'identifiant
  // est émis par le démon après le choix natif, jamais inventé ici.
  const confirmed = await confirmRoots(platform, roots);
  if (!confirmed.ok) {
    session.error = workspaceErrorMessage(confirmed.error);
    return again();
  }
  const now = utcNow();
  const existingId = session.state.workspaceId;
  let currentRoots: Record<string, unknown> | null = null;
  let workspaceId = existingId ?? newWorkspaceId();
  let expectedUpdatedAt: string | undefined;
  if (existingId) {
    const answer = await platform.request("workspace.get_config", { workspace_id: existingId });
    if (answer.ok) {
      const stored = answer.response.payload as { roots?: Record<string, unknown>; updated_at?: string };
      currentRoots = (stored.roots as Record<string, unknown>) ?? null;
      expectedUpdatedAt = stored.updated_at;
    } else {
      currentRoots = null;
      workspaceId = newWorkspaceId();
    }
  }
  const saved = await saveWorkspaceConfig(platform, {
    config: {
      schema_version: 1,
      workspace_id: workspaceId,
      profile,
      project_id: projectId,
      ...(session.state.projectSlug ? { project_slug: session.state.projectSlug } : {}),
      roots,
      created_at: now,
      updated_at: now,
    },
    current_roots: currentRoots,
    root_confirmation_id: confirmed.value.root_confirmation_id,
    ...(expectedUpdatedAt ? { expected_updated_at: expectedUpdatedAt } : {}),
  });
  if (!saved.ok) {
    session.error = workspaceErrorMessage(saved.error);
    return again();
  }
  session.state = { ...session.state, workspaceId, folderName: displayName };
  session.folder = null;
  session.statusText = null;
  session.notice = "Dossier associé.";
  persist(session);
  go(session, nextStep("dossier") ?? "memoire");
  return again();
}

async function paintMemoire(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  const step = stepById("memoire");
  const workspaceId = session.state.workspaceId;
  if (!workspaceId) {
    root.innerHTML = layout(
      step,
      "memoire",
      `<p class="settings-intro">Associez d'abord un dossier : la mémoire vit dans le dossier du projet.</p>` +
        navButtons({ prev: previousStep("memoire"), extra: `<button class="ds-btn ds-btn--primary" type="button" data-action="skip">Passer</button>` }),
    );
    root.querySelector("[data-action=skip]")?.addEventListener("click", () => {
      go(session, nextStep("memoire") ?? "environnement");
      void again();
    });
    root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
      go(session, previousStep("memoire") ?? "dossier");
      void again();
    });
    return;
  }
  const { text } = await readKnowledge(platform, workspaceId);
  session.knowledgeText = text;
  const body =
    errorHtml(session.error) +
    noticeHtml(session.notice) +
    `<dl class="settings-rows"><div class="settings-row"><dt>Mémoire du projet</dt><dd>${esc(text)}</dd></div></dl>` +
    `<p class="settings-intro">Vous pourrez ouvrir ce dossier dans Obsidian ou tout autre éditeur Markdown : Obsidian n'est jamais requis.</p>` +
    `<form class="settings-server-form" data-testid="memory-folder-form">` +
    `<label class="settings-field">Dossier de la mémoire (dans le projet)<input id="memory-folder-input" name="memory_folder" type="text" autocomplete="off" spellcheck="false" maxlength="64" value="vault" /></label>` +
    `<div class="settings-actions"><button class="ds-btn ds-btn--primary" type="submit">Activer la mémoire</button></div></form>` +
    navButtons({
      prev: previousStep("memoire"),
      extra:
        `<button class="ds-btn" type="button" data-action="skip">Passer cette étape</button>` +
        `<button class="ds-btn ds-btn--primary" type="button" data-action="next">Continuer</button>`,
    });
  root.innerHTML = layout(step, "memoire", body);
  session.notice = null;
  root.querySelector<HTMLFormElement>("[data-testid=memory-folder-form]")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const contentRoot = (root.querySelector<HTMLInputElement>("#memory-folder-input")?.value ?? "vault").trim() || "vault";
    void enableKnowledge(root, platform, session, contentRoot, again);
  });
  root.querySelector("[data-action=skip]")?.addEventListener("click", () => {
    go(session, nextStep("memoire") ?? "environnement");
    void again();
  });
  root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
    go(session, previousStep("memoire") ?? "dossier");
    void again();
  });
  root.querySelector("[data-action=next]")?.addEventListener("click", () => {
    go(session, nextStep("memoire") ?? "environnement");
    void again();
  });
}

async function enableKnowledge(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  contentRoot: string,
  again: () => Promise<void>,
): Promise<void> {
  const workspaceId = session.state.workspaceId;
  if (!workspaceId) {
    session.error = "Associez d'abord un dossier.";
    return again();
  }
  const answer = await platform.request("workspace.get_config", { workspace_id: workspaceId });
  if (!answer.ok) {
    session.error = workspaceErrorMessage(answer.error);
    return again();
  }
  const stored = answer.response.payload as Record<string, unknown>;
  const storedRoots = stored.roots as Record<string, unknown>;
  const config = {
    ...(stored as object),
    features: { ...((stored.features as Record<string, unknown>) ?? {}), knowledge: true },
    knowledge: {
      provider_id: "markdown-files",
      content_root: contentRoot,
      index: { scope: "workspace_cache", directory_name: "knowledge-index" },
    },
    updated_at: utcNow(),
  };
  // Pas de transition de racines : aucune confirmation à consommer.
  const saved = await saveWorkspaceConfig(platform, {
    config,
    current_roots: storedRoots,
    ...(typeof stored.updated_at === "string" ? { expected_updated_at: stored.updated_at } : {}),
  });
  if (!saved.ok) {
    session.error = workspaceErrorMessage(saved.error);
    return again();
  }
  const initialized = await platform.request("knowledge.init_vault", {
    workspace_id: workspaceId,
    confirmed: true,
  });
  if (!initialized.ok) {
    session.error = workspaceErrorMessage(initialized.error);
    return again();
  }
  const indexed = await platform.request("knowledge.reindex", {
    workspace_id: workspaceId,
    mode: "full_rebuild",
  });
  if (!indexed.ok) {
    session.error = workspaceErrorMessage(indexed.error);
    return again();
  }
  const { text } = await readKnowledge(platform, workspaceId);
  session.knowledgeText = text;
  session.notice = "Mémoire activée et préparée dans le dossier du projet.";
  session.error = null;
  void root;
  return again();
}

async function paintEnvironnement(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  const step = stepById("environnement");
  const workspaceId = session.state.workspaceId;
  let git = "Aucun dossier associé pour l'instant.";
  let code = "Aucun dossier associé pour l'instant.";
  if (workspaceId) {
    const probed = await workspaceGitStatus(platform, workspaceId);
    git = probed.ok ? gitStatusMessage(probed.value) : workspaceErrorMessage(probed.error);
    session.gitText = git;
    code = await readCodeGraph(platform, workspaceId);
    session.codeText = code;
  }
  const detected = await detectHarnessesSafe(platform, workspaceId);
  const harnessRows = detected
    .map((harness) => `<div class="settings-row"><dt>${esc(harness.display_name)}</dt><dd>${esc(harness.detected_version ? `Détecté (${harness.detected_version})` : STATE_LABELS[harness.state])}</dd></div>`)
    .join("");
  const body =
    errorHtml(session.error) +
    `<dl class="settings-rows">` +
    `<div class="settings-row"><dt>Git</dt><dd>${esc(git)}</dd></div>` +
    `<div class="settings-row"><dt>Mémoire projet</dt><dd>${esc(session.knowledgeText ?? "Non configurée.")}</dd></div>` +
    `<div class="settings-row"><dt>Analyse du code</dt><dd>${esc(code)}</dd></div>` +
    (harnessRows || `<div class="settings-row"><dt>Assistants IA</dt><dd>Aucun détecté.</dd></div>`) +
    `</dl>` +
    navButtons({
      prev: previousStep("environnement"),
      extra: `<button class="ds-btn ds-btn--primary" type="button" data-action="next">Continuer</button>`,
    });
  root.innerHTML = layout(step, "environnement", body);
  root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
    go(session, previousStep("environnement") ?? "memoire");
    void again();
  });
  root.querySelector("[data-action=next]")?.addEventListener("click", () => {
    go(session, nextStep("environnement") ?? "assistant");
    void again();
  });
}

async function detectHarnessesSafe(platform: Platform, workspaceId: string | undefined): Promise<HarnessStatus[]> {
  if (!workspaceId) return [];
  const detected = await detectHarnesses(platform, workspaceId);
  return detected.ok ? (detected.value.harnesses ?? []) : [];
}

async function paintAssistant(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  const step = stepById("assistant");
  const workspaceId = session.state.workspaceId;
  if (!workspaceId) {
    root.innerHTML = layout(
      step,
      "assistant",
      `<p class="settings-intro">Associez d'abord un dossier : la connexion se fait par projet.</p>` +
        navButtons({ prev: previousStep("assistant"), extra: `<button class="ds-btn ds-btn--primary" type="button" data-action="skip">Passer</button>` }),
    );
    root.querySelector("[data-action=skip]")?.addEventListener("click", () => {
      go(session, nextStep("assistant") ?? "final");
      void again();
    });
    root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
      go(session, previousStep("assistant") ?? "environnement");
      void again();
    });
    return;
  }
  const detected = await detectHarnesses(platform, workspaceId);
  const harnesses = detected.ok ? (detected.value.harnesses ?? []) : [];
  session.harnesses = harnesses;
  session.harnessError = detected.ok ? null : harnessErrorMessage(detected.error);
  const cards =
    harnesses.length === 0
      ? dsEmptyState("Aucun assistant détecté", "Studi'OS fonctionne sans assistant IA. Vous pourrez terminer et connecter un assistant plus tard.")
      : harnesses.map((harness) => harnessCard(harness, session.plan)).join("");
  const body =
    errorHtml(session.error ?? session.harnessError) +
    noticeHtml(session.notice) +
    `<p class="settings-intro">Le jeton Studi'OS n'est jamais écrit dans les fichiers, seulement référencé. Lancez ensuite votre assistant depuis Studi'OS pour activer la connexion.</p>` +
    `<div class="integrations-list">${cards}</div>` +
    navButtons({
      prev: previousStep("assistant"),
      extra:
        `<button class="ds-btn" type="button" data-action="skip">Passer cette étape</button>` +
        `<button class="ds-btn ds-btn--primary" type="button" data-action="next">Continuer</button>`,
    });
  root.innerHTML = layout(step, "assistant", body);
  session.notice = null;
  bindHarnessCards(root, platform, session, workspaceId, again);
  root.querySelector("[data-action=skip]")?.addEventListener("click", () => {
    go(session, nextStep("assistant") ?? "final");
    void again();
  });
  root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
    go(session, previousStep("assistant") ?? "environnement");
    void again();
  });
  root.querySelector("[data-action=next]")?.addEventListener("click", () => {
    go(session, nextStep("assistant") ?? "final");
    void again();
  });
}

function harnessCard(harness: HarnessStatus, plan: HarnessPlan | null): string {
  const configured = harness.state === "configured";
  const installed = configured || harness.state === "detected";
  const shown = plan && plan.adapter_id === harness.adapter_id ? planHtml(plan) : "";
  const actions = installed
    ? `<div class="integration-actions">` +
      `<button class="ds-btn ds-btn--primary" type="button" data-action="preview" data-harness="${esc(harness.adapter_id)}">${configured ? "Reconfigurer" : "Connecter à Studi'OS"}</button></div>`
    : "";
  return (
    `<article class="ds-card integration" data-harness="${esc(harness.adapter_id)}" data-state="${esc(harness.state)}">` +
    `<header class="integration-head"><h3>${esc(harness.display_name)}</h3>${dsBadge(STATE_LABELS[harness.state], STATE_TONES[harness.state])}</header>` +
    `<dl class="settings-rows"><div class="settings-row"><dt>Version</dt><dd>${esc(harness.detected_version ?? "—")}</dd></div>` +
    `<div class="settings-row"><dt>MCP Studi'OS</dt><dd>${configured ? "Configuré" : installed ? "Non configuré" : "—"}</dd></div></dl>` +
    actions +
    shown +
    `</article>`
  );
}

function planHtml(plan: HarnessPlan): string {
  const rows = (plan.changes ?? [])
    .map(
      (change) =>
        `<li><strong>${esc(CHANGE_LABELS[change.kind] ?? change.kind)}</strong> · <code class="mono">${esc(change.target)}</code></li>`,
    )
    .join("");
  if ((plan.changes ?? []).length === 0) {
    return `<div class="integration-plan" role="status"><p>Déjà à jour : aucune modification à appliquer.</p>` +
      `<button class="ds-btn" type="button" data-action="cancel-plan">Fermer</button></div>`;
  }
  return (
    `<div class="integration-plan" role="region" aria-label="Aperçu des modifications">` +
    `<h4>Aperçu — rien n'est écrit tant que vous n'appliquez pas</h4><ul>${rows}</ul>` +
    `<p class="settings-intro">Une sauvegarde locale est créée avant toute écriture.</p>` +
    `<button class="ds-btn ds-btn--primary" type="button" data-action="apply-plan">Appliquer</button> ` +
    `<button class="ds-btn" type="button" data-action="cancel-plan">Annuler</button></div>`
  );
}

function bindHarnessCards(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  workspaceId: string,
  again: () => Promise<void>,
): void {
  for (const card of root.querySelectorAll<HTMLElement>("[data-harness]")) {
    const adapterId = card.dataset["harness"] ?? "";
    card.querySelector("[data-action=preview]")?.addEventListener("click", () => {
      void previewHarness(platform, workspaceId, adapterId).then((outcome) => {
        if (!outcome.ok) {
          session.error = harnessErrorMessage(outcome.error);
          return again();
        }
        session.plan = outcome.value;
        session.error = null;
        return again();
      });
    });
    card.querySelector("[data-action=cancel-plan]")?.addEventListener("click", () => {
      session.plan = null;
      void again();
    });
    card.querySelector("[data-action=apply-plan]")?.addEventListener("click", () => {
      const plan = session.plan;
      if (!plan || plan.adapter_id !== adapterId) return;
      void applyHarness(platform, plan).then((outcome) => {
        if (!outcome.ok) {
          session.error = harnessErrorMessage(outcome.error);
          return again();
        }
        if (outcome.value.error || outcome.value.state !== "configured") {
          session.error = harnessErrorMessage(outcome.value.error);
          return again();
        }
        session.plan = null;
        session.notice = "Configuration appliquée. Une sauvegarde locale permet de la restaurer.";
        session.error = null;
        return again();
      });
    });
  }
}

async function paintFinal(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  const step = stepById("final");
  const workspaceId = session.state.workspaceId;
  const shell = getDesktopShell();
  const serverOk = (await probeServer()).ok;
  let folder = "Non associé";
  let memory = "Non configurée";
  let git = "—";
  let code = "—";
  if (workspaceId) {
    const checked = await validateWorkspace(platform, workspaceId);
    if (checked.ok) {
      const view = toWorkspaceViewModel(checked.value);
      folder = view ? `${session.state.folderName ?? "Dossier"} — ${workspaceHealthMessage(checked.value)}` : workspaceHealthMessage(checked.value);
    } else {
      folder = workspaceErrorMessage(checked.error);
    }
    const known = await readKnowledge(platform, workspaceId);
    memory = known.text;
    const probed = await workspaceGitStatus(platform, workspaceId);
    git = probed.ok ? gitStatusMessage(probed.value) : workspaceErrorMessage(probed.error);
    code = await readCodeGraph(platform, workspaceId);
  }
  const harnesses = await detectHarnessesSafe(platform, workspaceId);
  const harnessLine =
    harnesses.length === 0
      ? "Non configuré"
      : harnesses.map((harness) => `${harness.display_name} : ${harness.state === "configured" ? "connecté" : STATE_LABELS[harness.state]}`).join(" · ");
  const machine = (await readIdentity(platform)).error === null ? "Reconnu" : "À vérifier";
  const rows: Array<[string, string]> = [
    ["Projet", session.state.projectName ?? "Non choisi"],
    ["Dossier", folder],
    ["Mémoire", memory],
    ["Git", git],
    ["Analyse du code", code],
    ["Assistants IA", harnessLine],
    ["Ce poste", machine],
    ["Serveur Studi'OS", serverOk ? "Connecté" : "Injoignable (réessayez ou modifiez l'adresse)"],
  ];
  const body =
    errorHtml(session.error) +
    `<dl class="settings-rows">` +
    rows.map(([label, value]) => `<div class="settings-row"><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("") +
    `</dl>` +
    navButtons({
      prev: previousStep("final"),
      extra: `<button class="ds-btn ds-btn--primary" type="button" data-action="finish">Terminer</button>`,
    });
  root.innerHTML = layout(step, "final", body);
  void shell;
  root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
    go(session, previousStep("final") ?? "assistant");
    void again();
  });
  root.querySelector("[data-action=finish]")?.addEventListener("click", () => {
    if (!workspaceId) {
      session.error = "Associez un dossier avant de terminer (étape « Dossier »).";
      void again();
      return;
    }
    session.state = { ...session.state, status: "completed", current: "termine", completedAt: utcNow() };
    persist(session);
    location.hash = "#/";
  });
}

async function paintTermine(
  root: HTMLElement,
  _platform: Platform,
  session: SessionData,
  _again: () => Promise<void>,
  step: OnboardingStep,
): Promise<void> {
  void _platform;
  void _again;
  root.innerHTML = layout(
    step,
    "termine",
    `<p class="settings-notice" role="status">Votre projet « ${esc(session.state.projectName ?? "Studi'OS")} » est prêt.</p>` +
      `<div class="settings-actions"><a class="ds-btn ds-btn--primary" href="#/">Ouvrir le tableau de bord</a></div>`,
  );
}
