/**
 * P3 — assistant de premier lancement de Studi'OS Desktop.
 *
 * Le premier lancement ne configure que le poste (connexion au serveur,
 * vérification locale), sans projet ni dossier. La mémoire, l'environnement
 * (Git, analyse du code) et l'assistant IA se configurent ensuite par
 * dossier depuis « Espaces de travail » (voir `views/workspaceFolderSetup`).
 * Vocabulaire utilisateur, aucun secret affiché ou stocké.
 */
import { apiBaseUrl, createApiClient, type StudioClient } from "../api";
import { getToken, hasToken } from "../auth";
import { joinUrl } from "../config";
import { isDashboardIdentity } from "../machinesApi";
import { getDesktopShell, refreshDaemon } from "../desktopShell";
import { daemonLabel } from "../shellStatus";
import { dsBadge, dsPageHeader, dsStateHtml, dsStatus, dsTechDetails } from "../ds/ds";
import { loginOverlayHtml, renderLogin } from "../login";
import { fetchIdentity } from "../identityApi";
import { renderPublicAccount, type PublicAccountDeps, type PublicScreen } from "../views/publicAccount";
import { getPlatform, type Platform } from "../platform";
import type {
  IdentityView,
  LocalError,
} from "../platform/generated/local-contracts.generated";
import { esc } from "../ui";
import { originRefusalMessage } from "../originRefusal";
import { daemonGrantsEnroll } from "./enrollGrant";
import { ONBOARDING_STEPS, nextStep, previousStep, stepById, type OnboardingStep } from "./steps";
import {
  loadOnboardingState,
  saveOnboardingState,
  type OnboardingState,
  type OnboardingStepId,
} from "./state";

export function onboardingWebHtml(): string {
  return (
    dsPageHeader("Assistant de configuration", "Premier lancement de Studi'OS Desktop.") +
    `<section class="settings-domain" data-testid="onboarding-web">` +
    dsStateHtml(
      "empty",
      {
        title: "Disponible dans Studi'OS Desktop",
        message: "La configuration du poste se fait sur le poste, depuis l'application Studi'OS Desktop. Ce tableau de bord web reste autonome.",
      },
    ) +
    `</section>`
  );
}

/**
 * Version figéeille un bouton pendant une action asynchrone : empêche le double clic
 * et annonce l'attente. Le rendu suivant (`again`) remplace le bouton, ce qui
 * lève le verrou. Faux = une action est déjà en cours.
 */
function lockButton(button: HTMLButtonElement | null | undefined, label: string): boolean {
  if (!button) return true;
  if (button.disabled) return false;
  button.disabled = true;
  button.textContent = label;
  button.setAttribute("aria-busy", "true");
  return true;
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
      const pill = step.required ? dsBadge("requis") : dsBadge("optionnel", "info");
      return `<li${aria}>${esc(step.title)} ${pill}<span class="ds-sr-only">${state}</span></li>`;
    })
    .join("");
  return `<nav aria-label="Progression de l'assistant"><ol class="onboarding-progress" data-testid="onboarding-progress">${items}</ol></nav>`;
}

/**
 * Contexte : état réel du poste, consignes de repli. Aucune information
 * technique par défaut.
 */
function contextAside(session: SessionData, extra = ""): string {
  const server =
    session.serverProbe === null
      ? dsStatus("idle", "Non vérifié")
      : session.serverProbe.ok
        ? dsStatus("success", "Serveur joint")
        : dsStatus("warning", "Serveur injoignable");
  const rows = (label: string, value: string): string => `<div><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
  return (
    `<aside class="ds-card tool-context" aria-label="Contexte">` +
    `<div><h2>Ce poste, à l'instant</h2><dl class="context-list">${rows("Serveur", server)}</dl></div>` +
    extra +
    `<div><h2>Sans serveur ?</h2><p>L'application démarre quand même. La suite attend un serveur joint.</p></div>` +
    `<div><h2>Sur le web</h2><p>La configuration du poste se fait dans Studi'OS Desktop, pas ici.</p></div>` +
    `</aside>`
  );
}

function layout(session: SessionData, step: OnboardingStep, current: OnboardingStepId, body: string, context = ""): string {
  return (
    `<p class="ds-eyebrow">Premier lancement · Desktop uniquement</p>` +
    dsPageHeader("Assistant de configuration", "4 étapes guidées, poste seul.") +
    progressHtml(current) +
    `<div class="tool-columns"><div class="tool-main"><section class="settings-domain" data-testid="onboarding-step" data-step="${esc(step.id)}">` +
    `<h2>${esc(step.heading)}</h2><p class="settings-intro">${esc(step.intro)}</p>${body}</section></div>` +
    contextAside(session, context) +
    `</div>`
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
  if (!answer.ok) return { view: null, error: "État du poste illisible." };
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

/**
 * P3 : le parcours ne retient que le poste ; un état hérité (dossier déjà
 * associé) n'a rien à revalider ici. Conservé pour la reprise après
 * redémarrage : ne détourne plus jamais l'utilisateur.
 */
export async function revalidate(_data: SessionData, _platform: Platform): Promise<void> {
  return undefined;
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
    error: null,
    notice: null,
    restartRequired: false,
  };
}

async function paintBienvenue(
  root: HTMLElement,
  _platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  void _platform;
  const step = stepById("bienvenue");
  const body =
    errorHtml(session.error) +
    `<section class="ds-hero" aria-label="Bienvenue">` +
    `<p class="ds-hero-eyebrow">Bienvenue dans Studi'OS</p>` +
    `<h2>Configurez ce poste en quelques étapes</h2>` +
    `<p class="ds-hero-body">Sans projet ni dossier : ils se configureront ensuite depuis « Dossiers du projet », sans obligation.</p>` +
    `<div class="ds-hero-actions">` +
    `<button class="ds-btn ds-btn--primary" type="button" data-action="start">Commencer la configuration</button>` +
    (session.state.status === "in_progress"
      ? `<button class="ds-btn ds-btn--ghost" type="button" data-action="resume">Reprendre où j'en étais</button>`
      : "") +
    `</div></section>`;
  root.innerHTML = layout(session, step, "bienvenue", body);
  root.querySelector("[data-action=start]")?.addEventListener("click", () => {
    go(session, "connexion");
    void again();
  });
  root.querySelector("[data-action=resume]")?.addEventListener("click", () => {
    go(session, session.state.current);
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
    `<div class="settings-row"><dt>Serveur</dt><dd data-testid="server-probe">${esc(probe.detail)}</dd></div>` +
    `<div class="settings-row"><dt>Compte</dt><dd>${authed ? "Connecté" : "Non connecté"}</dd></div>` +
    `</dl>` +
    `<form class="settings-server-form" data-testid="server-origin-form" novalidate>` +
    `<label class="settings-field">Adresse du serveur Studi'OS` +
    `<input id="server-origin-input" name="server_origin" type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://studio.exemple.com" value="${esc(origin?.configured ?? "")}" /></label>` +
    `<div class="settings-actions"><button class="ds-btn ds-btn--primary" type="submit">Enregistrer</button>` +
    `<button class="ds-btn" type="button" data-action="retry">Réessayer</button></div></form>` +
    dsTechDetails(
      [
        { label: "Adresse appliquée", value: origin?.applied ?? "Non configurée", mono: true },
        { label: "Adresse configurée", value: origin?.configured ?? "Valeur du poste", mono: true },
        { label: "Redémarrage requis", value: origin?.restart_required === true ? "oui" : "non" },
      ],
      "Détails techniques — adresses et origine",
    ) +
    (authed
      ? ""
      : `<div data-testid="onboarding-login">${loginOverlayHtml()}</div>`) +
    navButtons({
      prev: previousStep("connexion"),
      extra:
        `<button class="ds-btn ds-btn--primary" type="button" data-action="next" ${probe.ok && authed ? "" : "disabled"}>Continuer</button>` +
        (probe.ok ? "" : `<span class="settings-intro">La suite nécessite un serveur joint et un compte connecté. L'application reste utilisable hors ligne.</span>`),
    });
  root.innerHTML = layout(session, step, "connexion", body);
  root.querySelector<HTMLFormElement>("[data-testid=server-origin-form]")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!lockButton(form.querySelector<HTMLButtonElement>("button[type=submit]"), "Enregistrement…")) return;
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
  root.querySelector<HTMLButtonElement>("[data-action=restart-desktop]")?.addEventListener("click", (event) => {
    if (!lockButton(event.currentTarget as HTMLButtonElement, "Redémarrage…")) return;
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
    const host = loginHost as HTMLElement;
    // A5 : création de compte et récupération dans l'assistant, sur l'adresse
    // serveur déjà configurée ci-dessus (apiBaseUrl, aucune seconde saisie).
    const showLogin = (): void =>
      renderLogin(
        host,
        () => {
          session.notice = "Connecté.";
          session.error = null;
          void again();
        },
        { onAccountAction: (action) => showAccount({ name: action }) },
      );
    const deps: PublicAccountDeps = {
      client: createApiClient(apiBaseUrl()),
      go: (screen) => showAccount(screen),
      toLogin: showLogin,
    };
    const showAccount = (screen: PublicScreen): void => {
      renderPublicAccount(host, screen, deps);
      if (screen.name === "sent" && screen.flow !== "forgot") {
        host.querySelector(".login-box .state")?.insertAdjacentHTML(
          "afterend",
          `<p class="meta" data-testid="onboarding-verify-hint">Ouvrez le lien dans votre navigateur, puis revenez ici pour vous connecter.</p>`,
        );
      }
    };
    showLogin();
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

/** A5 (DEC-0130) : message fixe pour chaque refus de `identity.enroll`. */
export function enrollErrorMessage(error: LocalError): string {
  const reason = (error.details as Record<string, unknown> | undefined)?.["reason"];
  if (reason === "session_expired") return "Votre session a expiré : reconnectez-vous à l'étape « Connexion », puis réessayez.";
  if (reason === "forbidden") return "Ce compte ne peut pas enregistrer de poste. Contactez l'administrateur de votre studio.";
  if (reason === "server_unreachable") return "Serveur injoignable. Vérifiez votre connexion, puis réessayez.";
  if (reason === "credential_not_stored") {
    return "Le poste a été créé sur le serveur mais son identifiant n'a pas pu être rangé dans le trousseau : révoquez-le depuis « Postes », puis réessayez.";
  }
  if (error.code === "wrong_profile") {
    return "L'assistant local vise un autre serveur que votre session. Vérifiez l'adresse du serveur, redémarrez l'application puis réessayez.";
  }
  if (error.code === "keyring_unavailable") return "Le trousseau du système est indisponible : le poste ne peut pas être enregistré.";
  if (error.code === "capability_missing" || error.code === "not_supported") {
    return ENROLL_UPDATE_MESSAGE;
  }
  return "L'enregistrement du poste a échoué. Réessayez dans quelques instants.";
}

const ENROLL_UPDATE_MESSAGE =
  "L'assistant local de cette version ne sait pas enregistrer le poste. Mettez l'application à jour ou demandez à un administrateur.";

export { daemonGrantsEnroll };

const MAX_MACHINE_NAME = 100;

/**
 * Nom proposé à l'enrôlement : le nom d'hôte du poste exposé par le démon
 * (même source que les noms de harnais, DEC-0117). Un démon antérieur ne le
 * fournit pas : repli sur l'ancien libellé.
 */
function defaultMachineName(view: IdentityView | null): string {
  const workstation = view?.workstation_name?.trim();
  if (workstation) return workstation.slice(0, MAX_MACHINE_NAME);
  return `Studi'OS Desktop · ${new Date().toISOString().slice(0, 10)}`;
}

/** `null` = nom acceptable ; sinon le message de refus, borné comme le serveur. */
function machineNameRefusal(name: string): string | null {
  if (!name) return "Indiquez un nom pour ce poste.";
  if (name.length > MAX_MACHINE_NAME) {
    return `Le nom du poste est limité à ${MAX_MACHINE_NAME} caractères.`;
  }
  return null;
}

interface AdoptableMachine {
  id: string;
  name: string;
}

/**
 * Machines non révoquées de l'utilisateur (`GET /api/v1/machines`, déjà filtré
 * côté serveur) proposées à la reprise. Toute panne (endpoint absent, réseau,
 * réponse inattendue) retombe sur une liste vide : l'enrôlement reste possible
 * en créant une nouvelle machine, jamais bloqué par cette lecture d'agrément.
 */
async function readAdoptableMachines(client: StudioClient): Promise<AdoptableMachine[]> {
  try {
    const result = await client.GET("/api/v1/machines");
    if (result?.response?.ok !== true || !Array.isArray(result.data)) return [];
    return result.data
      .filter((machine) => typeof machine.id === "string" && machine.id !== "" && !isDashboardIdentity(machine.display_name))
      .map((machine) => ({
        id: machine.id,
        name: machine.display_name.trim() === "" ? "Machine sans nom" : machine.display_name,
      }));
  } catch {
    return [];
  }
}

/**
 * Choix « reprendre une machine » / « nouvelle machine ». Absent quand aucune
 * machine connue : le formulaire d'enrôlement garde alors son geste unique.
 */
function machineChoiceHtml(machines: AdoptableMachine[]): string {
  if (machines.length === 0) return "";
  const options = machines
    .map(
      (machine) =>
        `<label class="ds-radio"><input type="radio" name="enroll-mode" value="${esc(machine.id)}" />` +
        `<span>Reprendre la machine « ${esc(machine.name)} »</span></label>`,
    )
    .join("");
  return (
    `<fieldset class="ds-fieldset" data-testid="enroll-machine-choice">` +
    `<legend>Ce poste est-il déjà enregistré ?</legend>` +
    `<p class="settings-intro">Une machine non révoquée de votre compte existe déjà : reprenez-la pour conserver son identifiant, ou créez une nouvelle machine.</p>` +
    `<label class="ds-radio"><input type="radio" name="enroll-mode" value="new" checked />` +
    `<span>Créer une nouvelle machine</span></label>` +
    options +
    `</fieldset>`
  );
}

async function paintVerification(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  const step = stepById("verification");
  const shell = getDesktopShell();
  if (shell) await refreshDaemon(shell).catch(() => undefined);
  const daemonText = shell ? `Assistant local : ${daemonLabel(shell.daemon)}` : "Assistant local : état inconnu.";
  const { view, error } = await readIdentity(platform);
  session.identity = view;
  session.identityError = error;
  const machineReady = error === null;
  const secretStatus = view?.secrets?.[0]?.status;
  // A5 : sans credential (ou révoqué), le poste s'enregistre lui-même avec la
  // session de l'étape « Connexion » ; aucun admin, aucun jeton affiché.
  const canEnroll =
    view !== null && (secretStatus === "absent" || secretStatus === "revoked") && (await daemonGrantsEnroll(platform));
  const authed = hasToken();
  const machines = canEnroll && authed ? await readAdoptableMachines(createApiClient(apiBaseUrl())) : [];
  const enrollHtml = !canEnroll
    ? view !== null && (secretStatus === "absent" || secretStatus === "revoked")
      ? `<p class="settings-intro" data-testid="enroll-unavailable">${esc(ENROLL_UPDATE_MESSAGE)}</p>`
      : ""
    : authed
      ? `<label class="settings-field">Nom de ce poste` +
        `<input id="enroll-machine-name" name="machine_name" type="text" autocomplete="off" maxlength="${MAX_MACHINE_NAME}" value="${esc(defaultMachineName(view))}" /></label>` +
        machineChoiceHtml(machines) +
        `<div class="settings-actions" data-testid="enroll-machine"><button class="ds-btn ds-btn--primary" type="button" data-action="enroll">Enregistrer ce poste</button></div>`
      : `<p class="settings-intro" data-testid="enroll-needs-login">Connectez-vous à l'étape « Connexion » pour enregistrer ce poste.</p>`;
  const body =
    errorHtml(session.error) +
    noticeHtml(session.notice) +
    `<dl class="settings-rows">` +
    `<div class="settings-row"><dt>Assistant local</dt><dd>${esc(daemonText)}</dd></div>` +
    `<div class="settings-row"><dt>Ce poste</dt><dd>${esc(error ?? "Reconnu — prêt à travailler.")}</dd></div>` +
    `</dl>` +
    enrollHtml +
    (machineReady || canEnroll
      ? ""
      : `<p class="settings-intro">Si une action est nécessaire côté serveur, faites-la valider puis revenez ici avec « Revérifier ».</p>`) +
    navButtons({
      prev: previousStep("verification"),
      extra:
        `<button class="ds-btn" type="button" data-action="recheck">Revérifier</button>` +
        `<button class="ds-btn ds-btn--primary" type="button" data-action="next" ${machineReady ? "" : "disabled"}>Continuer</button>`,
    });
  root.innerHTML = layout(session, step, "verification", body);
  session.notice = null;
  root.querySelector<HTMLButtonElement>("[data-action=enroll]")?.addEventListener("click", (event) => {
    const token = getToken();
    if (view === null || token === null) return;
    const machineName = (root.querySelector<HTMLInputElement>("#enroll-machine-name")?.value ?? "").trim();
    const refusal = machineNameRefusal(machineName);
    if (refusal) {
      session.error = refusal;
      void again();
      return;
    }
    const chosen = root.querySelector<HTMLInputElement>("input[name=enroll-mode]:checked")?.value ?? "new";
    const adoptMachineId = chosen !== "new" ? chosen : undefined;
    if (!lockButton(event.currentTarget as HTMLButtonElement, "Enregistrement…")) return;
    void daemonGrantsEnroll(platform)
      .then((granted) => {
        if (!granted) return null;
        return platform.request("identity.enroll", {
          profile: view.profile,
          human_session: token,
          machine_name: machineName,
          replace_existing: secretStatus === "revoked",
          ...(adoptMachineId !== undefined ? { adopt_machine_id: adoptMachineId } : {}),
        });
      })
      .then((answer) => {
        if (answer === null) {
          session.error = ENROLL_UPDATE_MESSAGE;
        } else if (answer.ok) {
          const outcome = (answer.response.payload as { outcome?: string }).outcome;
          session.error = null;
          session.notice = outcome === "already_enrolled" ? "Ce poste était déjà enregistré." : "Poste enregistré.";
        } else {
          session.error = enrollErrorMessage(answer.error);
        }
        return again();
      });
  });
  root.querySelector("[data-action=recheck]")?.addEventListener("click", () => {
    session.error = null;
    void again();
  });
  root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
    go(session, previousStep("verification") ?? "connexion");
    void again();
  });
  root.querySelector("[data-action=next]")?.addEventListener("click", () => {
    go(session, nextStep("verification") ?? "final");
    void again();
  });
}

async function paintFinal(
  root: HTMLElement,
  platform: Platform,
  session: SessionData,
  again: () => Promise<void>,
): Promise<void> {
  const step = stepById("final");
  const serverOk = (await probeServer()).ok;
  const machine = (await readIdentity(platform)).error === null ? "Reconnu" : "À vérifier";
  const rows: Array<[string, string]> = [
    ["Ce poste", machine],
    ["Serveur Studi'OS", serverOk ? "Connecté" : "Injoignable (réessayez ou modifiez l'adresse)"],
  ];
  const body =
    errorHtml(session.error) +
    `<dl class="settings-rows">` +
    rows.map(([label, value]) => `<div class="settings-row"><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("") +
    `</dl>` +
    `<p class="settings-intro">Vos dossiers se configureront ensuite depuis « Dossiers du projet » : mémoire, environnement et assistant IA, par dossier, sans obligation.</p>` +
    `<p class="settings-actions"><a class="ds-btn" href="#/reglages/dossiers" data-testid="onboarding-to-workspaces">Configurer un dossier</a></p>` +
    navButtons({
      prev: previousStep("final"),
      extra: `<button class="ds-btn ds-btn--primary" type="button" data-action="finish">Terminer</button>`,
    });
  root.innerHTML = layout(session, step, "final", body);
  root.querySelector("[data-action=prev]")?.addEventListener("click", () => {
    go(session, previousStep("final") ?? "verification");
    void again();
  });
  root.querySelector("[data-action=finish]")?.addEventListener("click", () => {
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
    session,
    step,
    "termine",
    `<p class="settings-notice" role="status">Votre poste est prêt. Les dossiers se configurent depuis « Dossiers du projet », sans obligation.</p>` +
      `<div class="settings-actions"><a class="ds-btn ds-btn--primary" href="#/">Ouvrir le tableau de bord</a> ` +
      `<a class="ds-btn" href="#/reglages/dossiers">Aller aux espaces de travail</a></div>`,
  );
}
