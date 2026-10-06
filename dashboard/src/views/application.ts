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
  type OutboxLegacyStatus,
  type Platform,
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
import { originRefusalMessage } from "../originRefusal";
import { loadOnboardingState, saveOnboardingState } from "../onboarding/state";
import { stepById } from "../onboarding/steps";
import { allNotes, openWhatsNew, whatsNewSectionHtml } from "../releaseNotes";
import "./configuration.css";

const DESCRIPTION = "Identité, serveur et état de l'application qui exécute ce tableau de bord.";

/** P11 — revoir la configuration locale et relancer l'assistant si besoin. */
export function onboardingSectionHtml(): string {
  const state = loadOnboardingState();
  const status =
    state.status === "completed"
      ? `Terminé${state.completedAt ? ` le ${esc(state.completedAt.slice(0, 10))}` : ""}`
      : state.status === "in_progress"
        ? `En cours — étape « ${esc(stepById(state.current).title)} »`
        : "Jamais lancé";
  return (
    `<section class="app-card app-card--row" data-testid="onboarding-section">` +
    `<div class="app-card-text"><h2>Assistant de configuration</h2>` +
    `<p class="settings-intro">${status}. Revoyez le dossier, la mémoire et l'assistant IA, ou corrigez une étape devenue invalide.</p></div>` +
    `<div class="settings-actions">` +
    (state.status === "in_progress"
      ? `<a class="ds-btn ds-btn--primary" href="#/bienvenue">Reprendre l'assistant</a> `
      : "") +
    `<button class="ds-btn" type="button" data-action="relaunch-onboarding">Relancer l'assistant</button>` +
    `</div></section>`
  );
}

export { originRefusalMessage };

/** What the page shows about the running Desktop shell (`null` on the web). */
export interface DesktopSection {
  origin: ServerOriginState | null;
  /** The address API calls go to right now. */
  effectiveServer: string;
  connection: ConnectionSnapshot;
  daemon: DaemonSummary;
  compatibility: CompatibilityState;
  /** The daemon misses optional capabilities that only an update brings. */
  daemonUpdateAdvised?: boolean;
  status: ShellStatus;
  /** Legacy outbox status (Phase 1 read-only). */
  legacyOutbox: OutboxLegacyStatus | null;
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

function compatibilityLabel(state: CompatibilityState, daemonUpdateAdvised = false): string {
  if (state === "ok" && daemonUpdateAdvised) {
    return "Compatible — mettez à jour l'assistant local pour disposer de toutes les fonctions";
  }
  if (state === "ok") return "Compatible";
  if (state === "incompatible") return "Incompatible — mettez à jour l'application";
  return "Non vérifiée";
}

type Tone = "ok" | "warn" | "error";

function tile(testid: string, label: string, tone: Tone, value: string, extra = "", attrs = ""): string {
  return (
    `<div class="app-tile app-tile--${tone}" data-testid="${testid}">` +
    `<p class="app-tile-label">${esc(label)}</p>` +
    `<p class="app-tile-value"><span class="app-dot" aria-hidden="true"></span><span ${attrs}>${value}</span></p>${extra}</div>`
  );
}

function compatibilityTone(state: CompatibilityState, advised: boolean): Tone {
  if (state === "incompatible") return "error";
  return state === "ok" && !advised ? "ok" : "warn";
}

function statusTilesHtml(section: DesktopSection): string {
  const { connection, status } = section;
  const problem = connection.state === "unreachable" || connection.state === "auth_expired";
  const shown = section.effectiveServer || "Aucune adresse configurée";
  const attention = daemonNeedsAttention(section.daemon);
  const retry = problem ? `<button class="ds-btn" type="button" data-action="retry">Réessayer</button>` : "";
  const server = tile(
    "server-section",
    "Serveur",
    status.level as Tone,
    esc(status.label),
    `<p class="app-tile-hint"><code class="mono" data-testid="server-effective">${esc(shown)}</code></p>${retry}`,
    'data-testid="server-summary"',
  );
  const daemon = tile(
    "daemon-section",
    "Assistant local",
    attention ? "error" : "ok",
    esc(daemonLabel(section.daemon)),
    attention ? `<p class="app-tile-hint">Les fonctions locales sont suspendues ; le tableau de bord reste utilisable.</p>` : "",
    `data-testid="daemon-state" data-attention="${attention}"`,
  );
  const compat = tile(
    "compat-section",
    "Compatibilité",
    compatibilityTone(section.compatibility, section.daemonUpdateAdvised ?? false),
    esc(compatibilityLabel(section.compatibility, section.daemonUpdateAdvised)),
    "",
    'data-testid="compatibility"',
  );
  return `<section class="app-tiles" aria-label="État de l'application">${server}${daemon}${compat}</section>`;
}

function serverFormHtml(section: DesktopSection, form: ApplicationFormState): string {
  const { origin } = section;
  const value = form.value ?? origin?.configured ?? "";
  const message = form.error
    ? `<p class="state error" id="server-origin-error" role="alert" data-testid="server-origin-error">${esc(form.error)}</p>`
    : form.notice
      ? `<p class="settings-intro" role="status" data-testid="server-origin-notice">${esc(form.notice)}</p>`
      : "";
  const restart = origin?.restart_required
    ? `<div class="app-callout" data-testid="restart-required">` +
      `<p class="settings-intro">Le nouveau serveur ${origin.configured ? `<code class="mono">${esc(origin.configured)}</code> ` : "par défaut "}` +
      `sera utilisé après un redémarrage de l'application. L'ancienne adresse reste utilisée en attendant.</p>` +
      `<button class="ds-btn ds-btn--primary" type="button" data-action="restart">Redémarrer maintenant</button></div>`
    : "";
  const open = form.error || form.notice || form.value !== undefined;
  return (
    restart +
    `<details class="settings-technical" data-testid="server-settings"${open ? " open" : ""}><summary>Changer l'adresse du serveur</summary>` +
    `<form class="settings-server-form" data-testid="server-origin-form" novalidate>` +
    `<label class="settings-field">Adresse du serveur Studio OS` +
    `<input id="server-origin-input" name="server_origin" type="url" inputmode="url" autocomplete="off" spellcheck="false" ` +
    `placeholder="https://studio.exemple.com" value="${esc(value)}"${form.error ? ' aria-invalid="true" aria-describedby="server-origin-error"' : ""} /></label>` +
    `<div class="settings-actions">` +
    `<button class="ds-btn ds-btn--primary" type="submit">Enregistrer</button>` +
    `<button class="ds-btn ds-btn--ghost" type="button" data-action="reset-origin"${origin?.configured ? "" : " disabled"}>Rétablir la valeur par défaut</button>` +
    `</div></form>${message}</details>`
  );
}

function healthRowsHtml(section: DesktopSection, info: DesktopInfo | null): string {
  const health = section.daemon.kind === "state" ? section.daemon.health : null;
  return (
    (info ? row("Processus de l'assistant", esc(sidecarLabel(info))) : "") +
    (health
      ? row("Synchronisation (heartbeat)", `<span data-testid="health-heartbeat">${esc(conditionLabel(health.heartbeat))}</span>`) +
        row("Rejeu de la file hors ligne", `<span data-testid="health-outbox">${esc(conditionLabel(health.outboxReplay))}</span>`) +
        row(
          "Surveillance Git",
          `<span data-testid="health-watchers">${health.gitWatchers.total === 0 ? "Aucun dépôt surveillé" : `${health.gitWatchers.healthy} / ${health.gitWatchers.total} en bonne santé`}</span>`,
        )
      : "")
  );
}

function legacyOutboxHtml(section: DesktopSection): string {
  const outbox = section.legacyOutbox;
  if (!outbox) return "";
  const counts = Object.entries(outbox.counts ?? {})
    .map(([table, count]) => `${table}: ${count}`)
    .join(", ") || "aucun";
  return (
    `<div data-testid="legacy-outbox-section"><h4>File d'attente héritée</h4><dl class="settings-refs">` +
    row("État", esc(outbox.exists ? "Présente" : "Absente")) +
    row("Contenu", esc(outbox.has_queued_work ? "Travail en attente" : "Vide")) +
    row("Détail par table", esc(counts)) +
    `</dl><p class="settings-intro">Cette file date d'avant l'identité de ce poste. Elle est en lecture seule.</p></div>`
  );
}

/** Version courante + mise à jour : l'action principale de la page. */
function heroHtml(info: DesktopInfo | null, failure: string | undefined, form: ApplicationFormState, canCheck: boolean): string {
  if (!info) {
    return (
      `<div class="state error" role="alert" data-testid="application-error">` +
      `Impossible de lire l'identité Desktop${failure ? ` : ${esc(failure)}` : ""}.</div>`
    );
  }
  const status = form.update;
  const available = status?.state === "available";
  const error = form.updateError ? `<p class="state error" role="alert" data-testid="update-error">${esc(form.updateError)}</p>` : "";
  const check = (primary: boolean, label: string): string =>
    canCheck
      ? `<button class="ds-btn${primary ? " ds-btn--primary" : ""}" type="button" data-action="check-update" data-testid="check-update">${label}</button>`
      : "";
  let text: string;
  let button: string;
  if (status?.state === "available") {
    text =
      `La version ${esc(status.version)} est disponible. Vos données sont conservées ; ` +
      `l'assistant local est arrêté puis l'application redémarre.`;
    button =
      `<button class="ds-btn ds-btn--primary ds-btn--lg" type="button" data-action="install-update">` +
      `${form.updateError ? "Réessayer l'installation de la version" : "Installer la version"} ${esc(status.version)}</button>` +
      (form.updateError ? check(false, "Vérifier à nouveau") : "");
  } else if (status?.state === "up_to_date") {
    text = "Vous utilisez la dernière version.";
    button = check(false, "Vérifier à nouveau");
  } else if (status?.state === "not_configured") {
    text = "Les mises à jour automatiques ne sont pas activées dans cette version de l'application.";
    button = check(false, "Vérifier à nouveau");
  } else {
    text = "Vérifiez si une nouvelle version est disponible.";
    button = check(true, "Rechercher une mise à jour");
  }
  const message = `${error}${form.updateError ? "" : `<p class="app-hero-text" data-testid="update-status">${text}</p>`}`;
  return (
    `<section class="app-hero${available ? " app-hero--update" : ""}" data-testid="application-identity">` +
    `<div class="app-hero-main"><p class="app-hero-eyebrow">${esc(info.product)}</p>` +
    `<h2 class="app-hero-version">Version <code class="mono">${esc(info.desktop_version)}</code></h2>${message}</div>` +
    `<div class="app-hero-actions">${button}</div></section>`
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
  return (
    `<details class="settings-technical" data-testid="diagnostics"${form.diagnosticsOpen ? " open" : ""}><summary>Détails techniques</summary>` +
    `<dl class="settings-refs">` +
    row("Mode", "Desktop") +
    (info ? row("Version studio.local", `<code class="mono">${esc(info.protocol)}</code>`) : "") +
    row("Origine de l'application", `<code class="mono">http://tauri.localhost</code>`) +
    row("Détail réseau", esc(section.connection.detail ?? "aucun")) +
    healthRowsHtml(section, info) +
    componentsHtml(diag) +
    row(
      "Journaux et diagnostic",
      diag
        ? `<button class="ds-btn ds-btn--ghost" type="button" data-action="open-logs" data-testid="open-logs">Ouvrir les journaux</button> ` +
            `<button class="ds-btn ds-btn--ghost" type="button" data-action="export-diagnostics" data-testid="export-diagnostics">Exporter un diagnostic</button>`
        : `<span class="meta">Non disponible : le diagnostic n'a pas pu être lu.</span>`,
    ) +
    `</dl>${exported}${exportError}${legacyOutboxHtml(section)}` +
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
  const head = `<p class="ds-hero-eyebrow">Administration / Configuration</p>${dsPageHeader("Configuration", DESCRIPTION)}${configTabsHtml("application")}`;
  let body: string;
  if (mode === "desktop") {
    body =
      heroHtml(info, failure, form, diag !== null) +
      (section
        ? statusTilesHtml(section) +
          serverFormHtml(section, form) +
          onboardingSectionHtml() +
          `<details class="settings-technical" data-testid="whats-new-details"><summary>Historique des versions</summary>${whatsNewSectionHtml()}</details>` +
          diagnosticsHtml(section, info, diag, form)
        : "");
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

async function sectionOf(
  shell: DesktopShell,
  origin: ServerOriginState | null,
  platform: Platform,
): Promise<DesktopSection> {
  const connection = shell.monitor.snapshot();
  const legacyOutbox = await platform.outboxLegacyStatus().catch(() => null);
  return {
    origin,
    effectiveServer: apiBaseUrl(),
    connection,
    daemon: shell.daemon,
    compatibility: shell.compatibility,
    daemonUpdateAdvised: shell.daemonAdvice === "update_daemon",
    status: summarizeShellStatus({
      connection,
      daemon: shell.daemon,
      compatibility: shell.compatibility,
      restartRequired: origin?.restart_required ?? false,
    }),
    legacyOutbox,
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
  const sectionData = shell ? await sectionOf(shell, origin, platform) : null;
  root.innerHTML = applicationPageHtml("desktop", info, failure, sectionData, form, diag);
  if (shell) bindActions(root, platform, shell, form);
}

function bindActions(root: HTMLElement, platform: Platform, shell: DesktopShell, form: ApplicationFormState): void {
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
  root.querySelector("[data-action=open-whats-new]")?.addEventListener("click", () => {
    openWhatsNew(document, allNotes());
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
      again(result.ok ? { update: result.status } : { updateError: updateErrorMessage(result.code) }),
    );
  });
  const install = root.querySelector<HTMLButtonElement>("[data-action=install-update]");
  install?.addEventListener("click", () => {
    // Download and verification take a while; a second click would find no
    // pending release. On success the application exits and the installer
    // restarts it, so only a failure comes back here.
    install.disabled = true;
    install.textContent = "Téléchargement et vérification…";
    root.querySelector(".app-hero-actions")?.insertAdjacentHTML(
      "beforeend",
      `<p class="settings-intro" role="status" data-testid="update-progress">La mise à jour est vérifiée avant d'être installée ; l'application redémarrera d'elle-même.</p>`,
    );
    void platform.installUpdate().then((result) => {
      if (!result.ok) {
        // Only an interrupted download leaves the release pending for a retry.
        const update = result.code === "network" ? form.update : undefined;
        return again({ update, updateError: updateErrorMessage(result.code) });
      }
      return undefined;
    });
  });
  root.querySelector("[data-action=retry]")?.addEventListener("click", () => {
    void shell.monitor.check().then(() => again());
  });
}
