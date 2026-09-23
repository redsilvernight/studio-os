/**
 * Paramètres › Application — identité, serveur, assistant local, compatibilité.
 *
 * Deux niveaux : un résumé simple (état + action évidente) puis des détails
 * repliés. Rien n'est simulé : en mode web, les commandes natives (adresse du
 * serveur, redémarrage, sélecteurs) n'existent pas et ne sont ni affichées ni
 * actives. Cette page LIT l'état du daemon (contrat P1 `daemon.status`) ; son
 * cycle de vie (démarrer, arrêter, journaux) appartient à P4.
 */
import { apiBaseUrl } from "../api";
import { getDesktopShell, paintShellStatus, refreshDaemon, type DesktopShell } from "../desktopShell";
import {
  getPlatform,
  type DesktopDiagnostics,
  type DesktopInfo,
  type Platform,
  type ServerOriginRefusal,
  type ServerOriginState,
  type UpdateErrorCode,
  type UpdateStatus,
} from "../platform";
import {
  conditionLabel,
  daemonLabel,
  daemonNeedsAttention,
  serverStateLabel,
  summarizeShellStatus,
  type CompatibilityState,
  type DaemonSummary,
  type ShellStatus,
} from "../shellStatus";
import type { ConnectionSnapshot } from "../connection";
import { esc } from "../ui";
import { dsPageHeader } from "../ds/ds";
import { configTabsHtml } from "./configuration";
import { loadOnboardingState, saveOnboardingState } from "../onboarding/state";
import { stepById } from "../onboarding/steps";
import "./configuration.css";

const DESCRIPTION = "Identité, serveur et état de l'application qui exécute ce tableau de bord.";

/** P11 — revoir la configuration locale et relancer l'assistant si besoin. */
export function onboardingSectionHtml(): string {
  const state = loadOnboardingState();
  const status =
    state.status === "completed"
      ? `Terminé${state.completedAt ? ` le ${esc(state.completedAt.slice(0, 10))}` : ""}.`
      : state.status === "in_progress"
        ? `En cours — étape « ${esc(stepById(state.current).title)} ».`
        : "Jamais lancé.";
  return (
    `<section class="settings-domain" data-testid="onboarding-section"><h2>Assistant de configuration</h2>` +
    `<dl class="settings-refs">${row("État", esc(status))}</dl>` +
    `<p class="settings-intro">Revoyez la configuration locale (dossier, mémoire, assistant IA) ou corrigez une étape devenue invalide.</p>` +
    `<div class="settings-actions">` +
    (state.status === "in_progress"
      ? `<a class="ds-btn ds-btn--primary" href="#/bienvenue">Reprendre l'assistant</a> `
      : "") +
    `<button class="ds-btn${state.status === "in_progress" ? "" : " ds-btn--primary"}" type="button" data-action="relaunch-onboarding">Relancer l'assistant</button>` +
    `</div></section>`
  );
}

/** Words for the machine codes the shell answers when it refuses an address. */
export function originRefusalMessage(reason: ServerOriginRefusal): string {
  switch (reason) {
    case "origin_empty":
      return "Saisissez l'adresse du serveur, par exemple https://studio.exemple.com.";
    case "origin_too_long":
      return "Cette adresse est trop longue.";
    case "origin_invalid":
      return "Cette adresse n'est pas valide. Format attendu : https://studio.exemple.com.";
    case "origin_unsupported_scheme":
      return "Seules les adresses https:// sont acceptées (http:// uniquement pour localhost en développement).";
    case "origin_credentials_not_allowed":
      return "L'adresse ne doit contenir ni identifiant ni mot de passe.";
    case "origin_not_an_origin":
      return "Indiquez uniquement l'adresse du serveur, sans chemin, paramètre ni ancre.";
    case "origin_insecure_scheme":
      return "Une adresse http:// n'est acceptée que pour localhost ou 127.0.0.1. Utilisez https://.";
    case "origin_is_desktop_origin":
      return "Cette adresse est celle de l'application elle-même, pas celle du serveur Studio OS.";
    case "storage_unavailable":
    case "storage_failed":
      return "L'adresse n'a pas pu être enregistrée sur ce poste.";
    case "unavailable":
      return "Cette commande n'est disponible que dans l'application Desktop.";
    default:
      return "L'adresse n'a pas pu être enregistrée.";
  }
}

/** What the page shows about the running Desktop shell (`null` on the web). */
export interface DesktopSection {
  origin: ServerOriginState | null;
  /** The address API calls go to right now. */
  effectiveServer: string;
  connection: ConnectionSnapshot;
  daemon: DaemonSummary;
  compatibility: CompatibilityState;
  status: ShellStatus;
}

export interface ApplicationFormState {
  /** Text the user typed (kept after a refusal so it can be corrected). */
  value?: string;
  error?: string;
  notice?: string;
  update?: UpdateStatus;
  updateError?: string;
  exportedFile?: string;
  exportError?: string;
  diagnosticsOpen?: boolean;
}

function row(label: string, value: string): string {
  return `<div class="settings-ref"><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
}

function sidecarLabel(info: DesktopInfo): string {
  switch (info.sidecar.state) {
    case "running":
      return "Lancé";
    case "exited":
      return "Arrêté";
    case "recovering":
      return "Reprise en cours";
    case "abandoned":
      return "Abandonné après plusieurs arrêts";
    case "unavailable":
      return "Indisponible";
    default:
      return "Non démarré";
  }
}

function compatibilityLabel(state: CompatibilityState): string {
  if (state === "ok") return "Compatible";
  if (state === "incompatible") return "Incompatible — mettez à jour l'application";
  return "Non vérifiée";
}

function serverSectionHtml(section: DesktopSection, form: ApplicationFormState): string {
  const { origin, connection, status } = section;
  const configured = origin?.configured ?? "";
  const value = form.value ?? configured;
  const shown = section.effectiveServer || "Aucune adresse configurée — renseignez-la ci-dessous";
  const problem = connection.state === "unreachable" || connection.state === "auth_expired";
  const message = form.error
    ? `<p class="state error" id="server-origin-error" role="alert" data-testid="server-origin-error">${esc(form.error)}</p>`
    : form.notice
      ? `<p class="settings-intro" role="status" data-testid="server-origin-notice">${esc(form.notice)}</p>`
      : "";
  const restart = origin?.restart_required
    ? `<div class="settings-restart" data-testid="restart-required">` +
      `<p class="settings-intro">Le nouveau serveur ${origin.configured ? `<code class="mono">${esc(origin.configured)}</code> ` : "par défaut "}` +
      `sera utilisé après un redémarrage de l'application. L'ancienne adresse reste utilisée en attendant.</p>` +
      `<button class="ds-btn ds-btn--primary" type="button" data-action="restart">Redémarrer maintenant</button></div>`
    : "";
  const retry = problem
    ? `<button class="ds-btn" type="button" data-action="retry">Réessayer</button>`
    : "";
  return (
    `<section class="settings-domain" data-testid="server-section"><h2>Serveur</h2>` +
    `<p class="app-status-line app-status-line--${status.level}" data-testid="server-summary">${esc(status.label)}</p>` +
    `<dl class="settings-refs">` +
    row("Adresse utilisée", `<code class="mono" data-testid="server-effective">${esc(shown)}</code>`) +
    row("État", esc(serverStateLabel(connection))) +
    `</dl>${retry}` +
    `<form class="settings-server-form" data-testid="server-origin-form" novalidate>` +
    `<label class="settings-field">Adresse du serveur Studio OS` +
    `<input id="server-origin-input" name="server_origin" type="url" inputmode="url" autocomplete="off" spellcheck="false" ` +
    `placeholder="https://studio.exemple.com" value="${esc(value)}"${form.error ? ' aria-invalid="true" aria-describedby="server-origin-error"' : ""} /></label>` +
    `<div class="settings-actions">` +
    `<button class="ds-btn ds-btn--primary" type="submit">Enregistrer</button>` +
    `<button class="ds-btn ds-btn--ghost" type="button" data-action="reset-origin"${origin?.configured ? "" : " disabled"}>Rétablir la valeur par défaut</button>` +
    `</div></form>${message}${restart}</section>`
  );
}

function assistantSectionHtml(section: DesktopSection, info: DesktopInfo | null): string {
  const attention = daemonNeedsAttention(section.daemon);
  const health = section.daemon.kind === "state" ? section.daemon.health : null;
  const healthRows = health
    ? row("Synchronisation (heartbeat)", `<span data-testid="health-heartbeat">${esc(conditionLabel(health.heartbeat))}</span>`) +
      row("Rejeu de la file hors ligne", `<span data-testid="health-outbox">${esc(conditionLabel(health.outboxReplay))}</span>`) +
      row(
        "Surveillance Git",
        `<span data-testid="health-watchers">${health.gitWatchers.total === 0 ? "Aucun dépôt surveillé" : `${health.gitWatchers.healthy} / ${health.gitWatchers.total} en bonne santé`}</span>`,
      )
    : "";
  return (
    `<section class="settings-domain" data-testid="daemon-section"><h2>Assistant local</h2>` +
    `<dl class="settings-refs">` +
    row("État", `<span data-testid="daemon-state" data-attention="${attention}">${esc(daemonLabel(section.daemon))}</span>`) +
    row("Compatibilité", `<span data-testid="compatibility">${esc(compatibilityLabel(section.compatibility))}</span>`) +
    (info ? row("Processus", esc(sidecarLabel(info))) : "") +
    healthRows +
    `</dl>` +
    (attention
      ? `<p class="settings-intro">L'assistant local ne répond pas. Le tableau de bord reste utilisable ; les fonctions locales sont suspendues.</p>`
      : "") +
    `</section>`
  );
}

function updateMessage(form: ApplicationFormState): string {
  if (form.updateError) return `<p class="state error" role="alert" data-testid="update-error">${esc(form.updateError)}</p>`;
  const status = form.update;
  if (!status) return "";
  if (status.state === "not_configured") {
    return `<p class="settings-intro" data-testid="update-status">Les mises à jour automatiques ne sont pas activées dans cette version de l'application.</p>`;
  }
  if (status.state === "up_to_date") {
    return `<p class="settings-intro" data-testid="update-status">Vous utilisez la dernière version (${esc(status.current)}).</p>`;
  }
  return (
    `<p class="settings-intro" data-testid="update-status">La version ${esc(status.version)} est disponible (actuelle : ${esc(status.current)}). ` +
    `Vos données sont conservées ; l'assistant local est arrêté puis l'application redémarre.</p>` +
    `<button class="ds-btn ds-btn--primary" type="button" data-action="install-update">Installer la version ${esc(status.version)}</button>`
  );
}

const UPDATE_ERRORS: Record<UpdateErrorCode, string> = {
  not_configured: "Les mises à jour ne sont pas activées dans cette version de l'application.",
  network: "Le serveur de mises à jour est injoignable. Vérifiez votre connexion puis réessayez.",
  invalid_metadata: "La réponse du serveur de mises à jour n'est pas exploitable. Rien n'a été modifié.",
  invalid_signature: "La signature de la mise à jour est invalide : elle a été refusée. Rien n'a été modifié.",
  install_failed: "L'installation de la mise à jour a échoué. La version actuelle reste en place.",
  failed: "La mise à jour a échoué. La version actuelle reste en place.",
};

export function updateErrorMessage(code: UpdateErrorCode): string {
  return UPDATE_ERRORS[code];
}

function componentsHtml(diag: DesktopDiagnostics | null): string {
  if (!diag) return "";
  const compat = {
    compatible: "Compatible",
    version_drift: "Compatible (versions différentes)",
    protocol_mismatch: "Incompatible — réinstallez l'application",
    unknown: "Non vérifiée",
  }[diag.sidecar.compat];
  const data = diag.locations.data_format;
  const format =
    data.state === "supported"
      ? `Version ${data.format}`
      : data.state === "unstamped"
        ? "Pas encore initialisées"
        : data.state === "too_new"
          ? `Écrites par une version plus récente (${data.format}) : non modifiées`
          : "Illisible : non modifiées";
  return (
    row("Version de l'assistant local", `<code class="mono">${esc(diag.sidecar.manifest?.daemon_version ?? "inconnue")}</code>`) +
    row("Assistant local fourni", esc(diag.sidecar.present ? "Oui" : "Non (introuvable)")) +
    row("Compatibilité de l'assistant", esc(compat)) +
    row("Composants optionnels", "Aucun n'est fourni avec l'application (Graphify : installation séparée)") +
    row("Système", esc(`${diag.os} ${diag.arch}`)) +
    row("Données utilisateur", `<code class="mono">${esc(diag.locations.daemon_data_dir ?? "indisponible")}</code>`) +
    row("Format des données", esc(format)) +
    row("Application installée dans", `<code class="mono">${esc(diag.locations.install_dir ?? "indisponible")}</code>`)
  );
}

function diagnosticsHtml(
  section: DesktopSection,
  info: DesktopInfo | null,
  diag: DesktopDiagnostics | null,
  form: ApplicationFormState,
): string {
  const exported = form.exportedFile
    ? `<p class="settings-intro" role="status" data-testid="export-result">Diagnostic enregistré : <code class="mono">${esc(form.exportedFile)}</code>. ` +
      `Les secrets en sont exclus ; vérifiez-le avant de le partager.</p>`
    : "";
  const exportError = form.exportError
    ? `<p class="state error" role="alert" data-testid="export-error">${esc(form.exportError)}</p>`
    : "";
  const checkUpdate = diag
    ? `<button class="ds-btn ds-btn--ghost" type="button" data-action="check-update" data-testid="check-update">Rechercher une mise à jour</button>`
    : "";
  return (
    `<details class="settings-technical" data-testid="diagnostics"${form.diagnosticsOpen ? " open" : ""}><summary>Détails techniques</summary>` +
    `<dl class="settings-refs">` +
    row("Origine de l'application", `<code class="mono">http://tauri.localhost</code>`) +
    row("Détail réseau", esc(section.connection.detail ?? "aucun")) +
    (info ? row("Processus local", esc(sidecarLabel(info))) : "") +
    componentsHtml(diag) +
    row(
      "Journaux et diagnostic",
      diag
        ? `<button class="ds-btn ds-btn--ghost" type="button" data-action="open-logs" data-testid="open-logs">Ouvrir les journaux</button> ` +
            `<button class="ds-btn ds-btn--ghost" type="button" data-action="export-diagnostics" data-testid="export-diagnostics">Exporter un diagnostic</button>`
        : `<span class="meta">Non disponible : le diagnostic n'a pas pu être lu.</span>`,
    ) +
    `</dl>${exported}${exportError}` +
    `<div class="settings-actions">${checkUpdate}</div>${updateMessage(form)}` +
    `</details>`
  );
}

export function applicationPageHtml(
  mode: "web" | "desktop",
  info: DesktopInfo | null,
  failure?: string,
  section: DesktopSection | null = null,
  form: ApplicationFormState = {},
  diag: DesktopDiagnostics | null = null,
): string {
  const head = `${dsPageHeader("Paramètres", DESCRIPTION)}${configTabsHtml("application")}`;
  let body: string;
  if (mode === "desktop") {
    const identity = info
      ? `<dl class="settings-refs" data-testid="application-identity">` +
        row("Application", esc(info.product)) +
        row("Mode", "Desktop") +
        row("Version Desktop", `<code class="mono">${esc(info.desktop_version)}</code>`) +
        row("Version studio.local", `<code class="mono">${esc(info.protocol)}</code>`) +
        `</dl>`
      : `<div class="state error" role="alert" data-testid="application-error">` +
        `Impossible de lire l'identité Desktop${failure ? ` : ${esc(failure)}` : ""}.</div>`;
    body =
      `<section class="settings-domain"><h2>Application</h2>${identity}</section>` +
      (section ? serverSectionHtml(section, form) + assistantSectionHtml(section, info) + onboardingSectionHtml() + diagnosticsHtml(section, info, diag, form) : "");
  } else {
    body =
      `<section class="settings-domain"><h2>Application</h2>` +
      `<dl class="settings-refs" data-testid="application-identity">` +
      row("Application", "Studi'OS Dashboard") +
      row("Mode", "Web") +
      `</dl>` +
      `<p class="settings-intro">Application Desktop non utilisée : ce tableau de bord s'exécute dans un navigateur. ` +
      `Le serveur est fixé à la construction du tableau de bord.</p></section>`;
  }
  return `<div class="settings">${head}${body}</div>`;
}

function sectionOf(shell: DesktopShell, origin: ServerOriginState | null): DesktopSection {
  const connection = shell.monitor.snapshot();
  return {
    origin,
    effectiveServer: apiBaseUrl(),
    connection,
    daemon: shell.daemon,
    compatibility: shell.compatibility,
    status: summarizeShellStatus({
      connection,
      daemon: shell.daemon,
      compatibility: shell.compatibility,
      restartRequired: origin?.restart_required ?? false,
    }),
  };
}

export async function renderApplication(
  root: HTMLElement,
  platform: Platform = getPlatform(),
  form: ApplicationFormState = {},
): Promise<void> {
  if (platform.mode === "web") {
    root.innerHTML = applicationPageHtml("web", null);
    return;
  }
  const shell = getDesktopShell();
  let info: DesktopInfo | null = null;
  let failure: string | undefined;
  try {
    info = await platform.desktopInfo();
  } catch (error) {
    failure = error instanceof Error ? error.message : undefined;
  }
  let diag: DesktopDiagnostics | null = null;
  try {
    diag = await platform.diagnostics();
  } catch {
    diag = null;
  }
  let origin: ServerOriginState | null = null;
  try {
    origin = await platform.serverOrigin();
  } catch {
    origin = null;
  }
  if (shell) {
    shell.origin = origin;
    // Refresh the daemon read when the page opens; a failure is a state, not a crash.
    await refreshDaemon(shell).catch(() => undefined);
  }
  root.innerHTML = applicationPageHtml("desktop", info, failure, shell ? sectionOf(shell, origin) : null, form, diag);
  if (shell) bindActions(root, platform, shell);
}

function bindActions(root: HTMLElement, platform: Platform, shell: DesktopShell): void {
  const again = (form: ApplicationFormState = {}): Promise<void> => renderApplication(root, platform, form);
  root.querySelector<HTMLFormElement>("[data-testid=server-origin-form]")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = root.querySelector<HTMLInputElement>("#server-origin-input");
    const value = input?.value ?? "";
    void platform.setServerOrigin(value).then((result) => {
      if (result.ok) {
        shell.origin = result.state;
        paintShellStatus();
        return again({ notice: "Adresse enregistrée." });
      }
      return again({ value, error: originRefusalMessage(result.reason) });
    });
  });
  root.querySelector("[data-action=reset-origin]")?.addEventListener("click", () => {
    void platform.setServerOrigin(null).then((result) => {
      if (result.ok) {
        shell.origin = result.state;
        paintShellStatus();
        return again({ notice: "Adresse par défaut rétablie." });
      }
      return again({ error: originRefusalMessage(result.reason) });
    });
  });
  root.querySelector("[data-action=restart]")?.addEventListener("click", () => {
    void platform.restartDesktop().then((started) => {
      if (!started) return again({ error: "Le redémarrage n'a pas pu être lancé. Fermez puis rouvrez l'application." });
      return undefined;
    });
  });
  root.querySelector("[data-action=relaunch-onboarding]")?.addEventListener("click", () => {
    saveOnboardingState({ schema: 1, status: "in_progress", current: "bienvenue" });
    location.hash = "#/bienvenue";
  });
  const keepOpen = (form: ApplicationFormState): Promise<void> => again({ ...form, diagnosticsOpen: true });
  root.querySelector("[data-action=open-logs]")?.addEventListener("click", () => {
    void platform.openDataFolder("logs").then((opened) => {
      if (!opened) return keepOpen({ exportError: "Le dossier des journaux n'a pas pu être ouvert." });
      return undefined;
    });
  });
  root.querySelector("[data-action=export-diagnostics]")?.addEventListener("click", () => {
    void platform.exportDiagnostics().then((result) =>
      keepOpen(result.ok ? { exportedFile: result.file } : { exportError: "Le diagnostic n'a pas pu être enregistré." }),
    );
  });
  root.querySelector("[data-action=check-update]")?.addEventListener("click", () => {
    void platform.checkForUpdate().then((result) =>
      keepOpen(result.ok ? { update: result.status } : { updateError: updateErrorMessage(result.code) }),
    );
  });
  root.querySelector("[data-action=install-update]")?.addEventListener("click", () => {
    void platform.installUpdate().then((result) => {
      if (!result.ok) return keepOpen({ updateError: updateErrorMessage(result.code) });
      return undefined;
    });
  });
  root.querySelector("[data-action=retry]")?.addEventListener("click", () => {
    void shell.monitor.check().then(() => again());
  });
}
