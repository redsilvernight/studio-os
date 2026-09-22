/**
 * Paramètres › Intégrations IA — configurer les harnais IA installés sur ce
 * poste (Claude Code, OpenCode…) pour qu'ils utilisent le MCP Studi'OS.
 *
 * Fonction de Studi'OS Desktop : la détection, les fichiers et les
 * sauvegardes appartiennent à l'assistant local. Cette page n'envoie que des
 * commandes `harness.*` du pont et n'affiche un changement comme appliqué
 * qu'après la réussite de l'assistant. Studi'OS ne gère ni modèle, ni
 * abonnement, ni clé de fournisseur : aucun champ de ce type n'existe ici.
 */
import { getPlatform, type Platform } from "../platform";
import { dsBadge, dsEmptyState, dsPageHeader } from "../ds/ds";
import {
  CHANGE_DETAILS,
  CHANGE_LABELS,
  STATE_LABELS,
  STATE_TONES,
  applyHarness,
  detectHarnesses,
  harnessErrorMessage,
  latestRollbackId,
  previewHarness,
  rollbackHarness,
  type HarnessPlan,
  type HarnessStatus,
} from "../harnessApi";
import { esc } from "../ui";
import { configTabsHtml } from "./configuration";
import "./configuration.css";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DESCRIPTION = "Connecter Claude Code, OpenCode et les autres harnais IA de ce poste au MCP Studi'OS.";

export interface IntegrationsView {
  notice?: string;
  error?: string;
  /** The preview shown for one harness; nothing is written until it is applied. */
  plan?: HarnessPlan;
  /** The harness for which a restore awaits confirmation. */
  confirmRestore?: string;
  workspaceInput?: string;
  workspaceError?: string;
}

function header(): string {
  return dsPageHeader("Intégrations IA", DESCRIPTION) + configTabsHtml("integrations");
}

export function integrationsWebHtml(): string {
  return (
    header() +
    `<section class="settings-domain" data-testid="integrations-web">` +
    dsEmptyState(
      "Fonction de Studi'OS Desktop",
      "La détection et la configuration des harnais IA se font sur le poste, depuis l'application Studi'OS Desktop. Ce tableau de bord web ne lit ni ne modifie aucun fichier local.",
    ) +
    `</section>`
  );
}

export function integrationsWorkspaceHtml(view: IntegrationsView): string {
  const error = view.workspaceError ? `<p class="ds-field-error" role="alert">${esc(view.workspaceError)}</p>` : "";
  return (
    header() +
    `<section class="settings-domain" data-testid="integrations-workspace">` +
    `<h2>Dossier local</h2>` +
    `<p class="settings-intro">Indiquez l'identifiant du dossier de travail Studi'OS à configurer. Il est affiché par Studi'OS Desktop.</p>` +
    `<form data-testid="workspace-form" class="settings-form">` +
    `<label class="ds-field" for="workspace-id-input"><span>Identifiant du dossier</span>` +
    `<input id="workspace-id-input" name="workspace" type="text" autocomplete="off" spellcheck="false" maxlength="36" value="${esc(view.workspaceInput ?? "")}"></label>` +
    error +
    `<button class="ds-btn ds-btn--primary" type="submit">Continuer</button>` +
    `</form></section>`
  );
}

function planHtml(status: HarnessStatus, plan: HarnessPlan): string {
  const changes = plan.changes ?? [];
  if (changes.length === 0) {
    return `<div class="integration-plan" data-testid="plan" role="status"><p>Déjà à jour : aucune modification à appliquer.</p>` +
      `<button class="ds-btn" type="button" data-action="cancel-plan">Fermer</button></div>`;
  }
  const rows = changes
    .map(
      (change) =>
        `<li data-change="${esc(change.kind)}"><strong>${esc(CHANGE_LABELS[change.kind] ?? change.kind)}</strong> · <code class="mono">${esc(change.target)}</code><br><span>${esc(CHANGE_DETAILS[change.kind] ?? "")}</span></li>`,
    )
    .join("");
  return (
    `<div class="integration-plan" data-testid="plan" role="region" aria-label="Aperçu des modifications de ${esc(status.display_name)}">` +
    `<h4>Aperçu — rien n'est écrit tant que vous n'appliquez pas</h4><ul>${rows}</ul>` +
    `<p class="settings-intro">Une sauvegarde locale est créée avant toute écriture. Vos autres serveurs MCP et réglages sont conservés.</p>` +
    `<button class="ds-btn ds-btn--primary" type="button" data-action="apply-plan">Appliquer</button> ` +
    `<button class="ds-btn" type="button" data-action="cancel-plan">Annuler</button></div>`
  );
}

function harnessHtml(status: HarnessStatus, view: IntegrationsView): string {
  const configured = status.state === "configured";
  const installed = configured || status.state === "detected";
  const version = status.detected_version ? esc(status.detected_version) : "—";
  const managed = status.managed_files ?? [];
  const files = configured && managed.length > 0
    ? `<div class="settings-row"><dt>Fichier</dt><dd><code class="mono">${managed.map(esc).join(", ")}</code></dd></div>`
    : "";
  const reason = status.state === "error" || status.state === "incompatible" || status.state === "not_detected"
    ? `<p class="integration-reason" data-testid="reason">${esc(harnessErrorMessage(status.error))}</p>`
    : "";
  const plan = view.plan && view.plan.adapter_id === status.adapter_id ? planHtml(status, view.plan) : "";
  const confirm = view.confirmRestore === status.adapter_id
    ? `<div class="integration-plan" data-testid="restore-confirm" role="alertdialog" aria-label="Confirmer la restauration">` +
      `<p>Restaurer la configuration précédente de ${esc(status.display_name)} ? Si le fichier a été modifié depuis, la restauration sera refusée.</p>` +
      `<button class="ds-btn ds-btn--danger" type="button" data-action="confirm-restore">Restaurer</button> ` +
      `<button class="ds-btn" type="button" data-action="cancel-restore">Annuler</button></div>`
    : "";
  const actions = installed
    ? `<div class="integration-actions">` +
      `<button class="ds-btn ds-btn--primary" type="button" data-action="preview">${configured ? "Reconfigurer" : "Configurer"}</button>` +
      (configured ? ` <button class="ds-btn" type="button" data-action="restore">Restaurer</button>` : "") +
      `</div>`
    : "";
  return (
    `<article class="ds-card integration" data-harness="${esc(status.adapter_id)}" data-state="${esc(status.state)}">` +
    `<header class="integration-head"><h3>${esc(status.display_name)}</h3>${dsBadge(STATE_LABELS[status.state], STATE_TONES[status.state])}</header>` +
    `<dl class="settings-rows"><div class="settings-row"><dt>Version</dt><dd>${version}</dd></div>` +
    `<div class="settings-row"><dt>MCP Studi'OS</dt><dd>${configured ? "Configuré" : installed ? "Non configuré" : "—"}</dd></div>${files}</dl>` +
    reason +
    actions +
    plan +
    confirm +
    `</article>`
  );
}

export function integrationsHtml(harnesses: HarnessStatus[], view: IntegrationsView = {}): string {
  const notice = view.notice ? `<p class="settings-notice" role="status" data-testid="notice">${esc(view.notice)}</p>` : "";
  const error = view.error ? `<p class="ds-field-error" role="alert" data-testid="error">${esc(view.error)}</p>` : "";
  const list = harnesses.length === 0
    ? dsEmptyState("Aucun harnais connu", "Studi'OS Desktop ne connaît aucun harnais IA à configurer.")
    : harnesses.map((status) => harnessHtml(status, view)).join("");
  return (
    header() +
    `<section class="settings-domain" data-testid="integrations">` +
    `<p class="settings-intro">Studi'OS ne gère ni modèle, ni abonnement, ni clé de fournisseur : seule la connexion du harnais au MCP Studi'OS est configurée. Le jeton Studi'OS n'est jamais écrit dans les fichiers, seulement référencé.</p>` +
    notice +
    error +
    `<div class="integrations-list">${list}</div></section>`
  );
}

export async function renderIntegrations(
  root: HTMLElement,
  workspaceId: string | undefined,
  platform: Platform = getPlatform(),
  view: IntegrationsView = {},
): Promise<void> {
  if (platform.mode === "web") {
    root.innerHTML = integrationsWebHtml();
    return;
  }
  if (workspaceId === undefined) {
    root.innerHTML = integrationsWorkspaceHtml(view);
    root.querySelector<HTMLFormElement>("[data-testid=workspace-form]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = (root.querySelector<HTMLInputElement>("#workspace-id-input")?.value ?? "").trim();
      if (!UUID.test(value)) {
        void renderIntegrations(root, undefined, platform, { workspaceInput: value, workspaceError: "Identifiant invalide (format UUID attendu)." });
        return;
      }
      location.hash = `#/configuration/integrations/${value}`;
    });
    return;
  }
  const detected = await detectHarnesses(platform, workspaceId);
  if (!detected.ok) {
    root.innerHTML = integrationsHtml([], { ...view, error: harnessErrorMessage(detected.error) });
    return;
  }
  root.innerHTML = integrationsHtml(detected.value.harnesses ?? [], view);
  bind(root, workspaceId, platform, view.plan);
}

function bind(root: HTMLElement, workspaceId: string, platform: Platform, shown: HarnessPlan | undefined): void {
  const again = (view: IntegrationsView = {}): Promise<void> => renderIntegrations(root, workspaceId, platform, view);
  for (const card of root.querySelectorAll<HTMLElement>("[data-harness]")) {
    const adapterId = card.dataset["harness"] ?? "";
    card.querySelector("[data-action=preview]")?.addEventListener("click", () => {
      void previewHarness(platform, workspaceId, adapterId).then((outcome) =>
        outcome.ok ? again({ plan: outcome.value }) : again({ error: harnessErrorMessage(outcome.error) }),
      );
    });
    card.querySelector("[data-action=cancel-plan]")?.addEventListener("click", () => void again());
    card.querySelector("[data-action=apply-plan]")?.addEventListener("click", () => {
      if (shown === undefined || shown.adapter_id !== adapterId) return;
      void applyHarness(platform, shown).then((outcome) => {
        if (!outcome.ok) return again({ error: harnessErrorMessage(outcome.error) });
        if (outcome.value.error || outcome.value.state !== "configured") {
          return again({ error: harnessErrorMessage(outcome.value.error) });
        }
        return again({ notice: "Configuration appliquée. Une sauvegarde locale permet de la restaurer." });
      });
    });
    card.querySelector("[data-action=restore]")?.addEventListener("click", () => void again({ confirmRestore: adapterId }));
    card.querySelector("[data-action=cancel-restore]")?.addEventListener("click", () => void again());
    card.querySelector("[data-action=confirm-restore]")?.addEventListener("click", () => {
      void rollbackHarness(platform, latestRollbackId(workspaceId, adapterId)).then((outcome) => {
        if (!outcome.ok) return again({ error: harnessErrorMessage(outcome.error) });
        if (outcome.value.error) return again({ error: harnessErrorMessage(outcome.value.error) });
        return again({ notice: "Configuration précédente restaurée." });
      });
    });
  }
}
