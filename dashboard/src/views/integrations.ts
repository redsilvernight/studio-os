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
  CHANGE_LABELS,
  STATE_LABELS,
  STATE_TONES,
  VERIFY_MESSAGES,
  VERIFY_TONES,
  applyHarness,
  changeDetail,
  changeTarget,
  detectHarnesses,
  harnessErrorMessage,
  latestRollbackId,
  previewHarness,
  rollbackHarness,
  verifyHarness,
  type HarnessPlan,
  type HarnessStatus,
  type HarnessVerifyResult,
} from "../harnessApi";
import {
  SKILL_STATE_LABELS,
  SKILL_STATE_TONES,
  SKILL_TARGET_LABELS,
  checkSkills,
  type SkillsCheckResult,
} from "../skillsApi";
import {
  MAX_CONCURRENT,
  MIN_CONCURRENT,
  clampConcurrent,
  getLaunchSettings,
  launchSettingsErrorMessage,
  offeredHarnesses,
  saveLaunchSettings,
  type LaunchSettings,
  type LaunchSettingsView,
} from "../launchSettingsApi";
import { esc } from "../ui";
import { configTabsHtml } from "./configuration";
import { loadOnboardingState } from "../onboarding/state";
import "./configuration.css";

const DESCRIPTION = "Connecter Claude Code, OpenCode et les autres harnais IA de ce poste au MCP Studi'OS.";

export interface IntegrationsView {
  notice?: string;
  error?: string;
  /** The preview shown for one harness; nothing is written until it is applied. */
  plan?: HarnessPlan;
  /** The harness for which a restore awaits confirmation. */
  confirmRestore?: string;
  /** The last connection check, for one harness. */
  verify?: HarnessVerifyResult;
  /** Library skills on this machine (read-only); absent when the check is unavailable. */
  skills?: SkillsCheckResult;
  /** Remote-launch settings of this machine; absent when unavailable. */
  launch?: LaunchSettingsView;
  /** Edits awaiting the owner's explicit confirmation; nothing is saved before it. */
  launchDraft?: LaunchSettings;
  launchNotice?: string;
  launchError?: string;
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

/**
 * Choix du dossier sans saisie manuelle d'identifiant : l'assistant de
 * configuration transporte déjà le dossier associé. Aucun copier/coller
 * d'UUID dans le parcours normal.
 */
export function integrationsWorkspaceHtml(): string {
  const remembered = loadOnboardingState();
  if (remembered.workspaceId) {
    return (
      header() +
      `<section class="settings-domain" data-testid="integrations-workspace">` +
      `<h2>Dossier local</h2>` +
      `<p class="settings-intro">Configurer les assistants IA pour « ${esc(remembered.folderName ?? remembered.projectName ?? "le dossier associé")} ».</p>` +
      `<div class="settings-actions">` +
      `<a class="ds-btn ds-btn--primary" data-testid="workspace-continue" href="#/configuration/integrations/${esc(remembered.workspaceId)}">Continuer</a> ` +
      `<a class="ds-btn" href="#/bienvenue">Choisir un autre dossier</a></div>` +
      `</section>`
    );
  }
  return (
    header() +
    `<section class="settings-domain" data-testid="integrations-workspace">` +
    `<h2>Dossier local</h2>` +
    dsEmptyState(
      "Aucun dossier associé",
      "Lancez l'assistant de configuration pour associer un dossier : les assistants IA se configurent par projet, sans identifiant à saisir.",
    ) +
    `<div class="settings-actions"><a class="ds-btn ds-btn--primary" href="#/bienvenue">Lancer l'assistant</a></div>` +
    `</section>`
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
        `<li data-change="${esc(change.kind)}"><strong>${esc(CHANGE_LABELS[change.kind] ?? change.kind)}</strong> · <code class="mono">${esc(changeTarget(change))}</code><br><span>${esc(changeDetail(change))}</span></li>`,
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
      `<p>Restaurer la configuration précédente de ${esc(status.display_name)} ? L'identifiant Studi'OS créé pour cet outil sera révoqué. Si un fichier a été modifié depuis, la restauration sera refusée.</p>` +
      `<button class="ds-btn ds-btn--danger" type="button" data-action="confirm-restore">Restaurer</button> ` +
      `<button class="ds-btn" type="button" data-action="cancel-restore">Annuler</button></div>`
    : "";
  const check = view.verify && view.verify.adapter_id === status.adapter_id
    ? `<p class="integration-verify" data-testid="verify" data-verify="${esc(view.verify.state)}" role="status">` +
      `${dsBadge(view.verify.state === "verified" ? "Connexion vérifiée" : view.verify.state === "token_missing" ? "Jeton manquant" : "Non vérifié", VERIFY_TONES[view.verify.state])} ` +
      `${esc(VERIFY_MESSAGES[view.verify.state])}</p>`
    : "";
  const actions = installed
    ? `<div class="integration-actions">` +
      `<button class="ds-btn ds-btn--primary" type="button" data-action="preview">${configured ? "Reconfigurer" : "Configurer"}</button>` +
      (configured
        ? ` <button class="ds-btn" type="button" data-action="verify">Vérifier la connexion</button>` +
          ` <button class="ds-btn" type="button" data-action="renew">Renouveler l'identifiant</button>` +
          ` <button class="ds-btn" type="button" data-action="restore">Restaurer</button>`
        : "") +
      `</div>`
    : "";
  return (
    `<article class="ds-card integration" data-harness="${esc(status.adapter_id)}" data-state="${esc(status.state)}">` +
    `<header class="integration-head"><h3>${esc(status.display_name)}</h3>${dsBadge(STATE_LABELS[status.state], STATE_TONES[status.state])}</header>` +
    `<dl class="settings-rows"><div class="settings-row"><dt>Version</dt><dd>${version}</dd></div>` +
    `<div class="settings-row"><dt>MCP Studi'OS</dt><dd>${configured ? "Configuré" : installed ? "Non configuré" : "—"}</dd></div>${files}</dl>` +
    reason +
    check +
    actions +
    plan +
    confirm +
    `</article>`
  );
}

export function skillsHtml(result: SkillsCheckResult): string {
  const skills = result.skills ?? [];
  const summary = result.in_sync
    ? dsBadge("Synchronisés", "success")
    : dsBadge("À resynchroniser", "warning");
  const rows = skills
    .map(
      (skill) =>
        `<li data-skill="${esc(skill.stable_key)}"><code class="mono">${esc(skill.stable_key)}</code> · v${skill.version} ` +
        skill.targets
          .map(
            (target) =>
              `<span data-target="${esc(target.harness)}">${esc(SKILL_TARGET_LABELS[target.harness])} : ${dsBadge(SKILL_STATE_LABELS[target.state], SKILL_STATE_TONES[target.state])}</span>`,
          )
          .join(" ") +
        `</li>`,
    )
    .join("");
  return (
    `<section class="settings-domain" data-testid="skills" data-in-sync="${result.in_sync}">` +
    `<h2>Skills de la bibliothèque sur ce poste</h2>` +
    `<p class="settings-intro">${summary} ${result.current} à jour · ${result.missing} absents · ${result.outdated} obsolètes · ${result.locally_modified} modifiés localement. Lecture seule : aucune skill n'est écrite depuis cette page.</p>` +
    (skills.length === 0 ? "" : `<ul class="skills-list">${rows}</ul>`) +
    `</section>`
  );
}

export function launchSettingsHtml(view: LaunchSettingsView, draft?: LaunchSettings, notice?: string, error?: string): string {
  const shown = draft ?? view;
  const allowed = new Set(shown.allowed_harnesses ?? []);
  const offered = offeredHarnesses(view);
  const detected = new Set(view.detected_harnesses ?? []);
  const boxes = offered.length === 0
    ? `<p class="settings-intro" data-testid="launch-no-harness">Aucun harnais détecté sur ce poste : aucun lancement ne pourra être accepté.</p>`
    : offered
        .map(
          (id) =>
            `<label class="settings-check"><input type="checkbox" data-launch-harness="${esc(id)}"${allowed.has(id) ? " checked" : ""}${draft ? " disabled" : ""}> <code class="mono">${esc(id)}</code>${detected.has(id) ? "" : " (non détecté)"}</label>`,
        )
        .join("");
  const form =
    `<label class="settings-check"><input type="checkbox" data-launch-field="opt_in"${shown.opt_in ? " checked" : ""}${draft ? " disabled" : ""}> Accepter les lancements demandés à distance sur ce poste</label>` +
    `<label class="settings-field">Lancements simultanés maximum (${MIN_CONCURRENT} à ${MAX_CONCURRENT}) <input type="number" min="${MIN_CONCURRENT}" max="${MAX_CONCURRENT}" step="1" data-launch-field="max_concurrent" value="${shown.max_concurrent}"${draft ? " disabled" : ""}></label>` +
    `<fieldset class="settings-field"><legend>Harnais autorisés</legend>${boxes}</fieldset>`;
  const actions = draft
    ? `<div class="settings-confirm" role="alert" data-testid="launch-confirm"><p>Enregistrer ces réglages ? Vous seul autorisez les lancements sur ce poste : ${draft.opt_in ? `ils seront acceptés (${draft.max_concurrent} simultané(s) au plus, ${(draft.allowed_harnesses ?? []).length} harnais autorisé(s))` : "aucun lancement ne sera accepté"}.</p>` +
      `<button class="ds-btn ds-btn--primary" type="button" data-action="confirm-launch">Confirmer l'enregistrement</button> ` +
      `<button class="ds-btn" type="button" data-action="cancel-launch">Annuler</button></div>`
    : `<button class="ds-btn ds-btn--primary" type="button" data-action="save-launch">Enregistrer…</button>`;
  return (
    `<section class="settings-domain" data-testid="launch-settings" data-opt-in="${view.opt_in}">` +
    `<h2>Lancements à distance sur ce poste</h2>` +
    `<p class="settings-intro">${dsBadge(view.opt_in ? "Activés" : "Désactivés", view.opt_in ? "success" : "neutral")} Par défaut rien n'est accepté : seul le propriétaire du poste autorise les lancements et choisit les harnais permis.</p>` +
    (notice ? `<p class="settings-notice" role="status" data-testid="launch-notice">${esc(notice)}</p>` : "") +
    (error ? `<p class="ds-field-error" role="alert" data-testid="launch-error">${esc(error)}</p>` : "") +
    form +
    actions +
    `</section>`
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
    `<p class="settings-intro">Studi'OS ne gère ni modèle, ni abonnement, ni clé de fournisseur : seule la connexion du harnais au MCP Studi'OS est configurée. Chaque outil reçoit son propre identifiant Studi'OS, rangé dans sa seule configuration utilisateur et jamais affiché ; les fichiers du projet n'en contiennent aucun.</p>` +
    notice +
    error +
    `<div class="integrations-list">${list}</div></section>` +
    (view.skills ? skillsHtml(view.skills) : "") +
    (view.launch ? launchSettingsHtml(view.launch, view.launchDraft, view.launchNotice, view.launchError) : "")
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
    root.innerHTML = integrationsWorkspaceHtml();
    return;
  }
  const detected = await detectHarnesses(platform, workspaceId);
  if (!detected.ok) {
    root.innerHTML = integrationsHtml([], { ...view, error: harnessErrorMessage(detected.error) });
    return;
  }
  // Best effort: an unavailable check never hides the harness list.
  const skills = await checkSkills(platform).catch(() => null);
  const launch = await getLaunchSettings(platform).catch(() => null);
  const withSkills = {
    ...view,
    ...(skills?.ok ? { skills: skills.value } : {}),
    ...(launch?.ok ? { launch: launch.value } : {}),
  };
  root.innerHTML = integrationsHtml(detected.value.harnesses ?? [], withSkills);
  bind(root, workspaceId, platform, view.plan, view.launchDraft);
}

function readLaunchDraft(root: HTMLElement): LaunchSettings {
  const field = (name: string): HTMLInputElement | null => root.querySelector<HTMLInputElement>(`[data-launch-field="${name}"]`);
  return {
    opt_in: field("opt_in")?.checked === true,
    max_concurrent: clampConcurrent(Number(field("max_concurrent")?.value)),
    allowed_harnesses: [...root.querySelectorAll<HTMLInputElement>("[data-launch-harness]")]
      .filter((box) => box.checked)
      .map((box) => box.dataset["launchHarness"] ?? ""),
  };
}

function bindLaunch(root: HTMLElement, platform: Platform, draft: LaunchSettings | undefined, again: (view?: IntegrationsView) => Promise<void>): void {
  root.querySelector("[data-action=save-launch]")?.addEventListener("click", () => void again({ launchDraft: readLaunchDraft(root) }));
  root.querySelector("[data-action=cancel-launch]")?.addEventListener("click", () => void again());
  root.querySelector("[data-action=confirm-launch]")?.addEventListener("click", () => {
    if (draft === undefined) return;
    void saveLaunchSettings(platform, draft).then((outcome) =>
      outcome.ok
        ? again({ launchNotice: "Réglages de lancement enregistrés ; ils s'appliquent sans redémarrage." })
        : again({ launchDraft: draft, launchError: launchSettingsErrorMessage(outcome.error) }),
    );
  });
}

function bind(root: HTMLElement, workspaceId: string, platform: Platform, shown: HarnessPlan | undefined, draft?: LaunchSettings): void {
  const again = (view: IntegrationsView = {}): Promise<void> => renderIntegrations(root, workspaceId, platform, view);
  bindLaunch(root, platform, draft, again);
  for (const card of root.querySelectorAll<HTMLElement>("[data-harness]")) {
    const adapterId = card.dataset["harness"] ?? "";
    card.querySelector("[data-action=preview]")?.addEventListener("click", () => {
      void previewHarness(platform, workspaceId, adapterId).then((outcome) =>
        outcome.ok ? again({ plan: outcome.value }) : again({ error: harnessErrorMessage(outcome.error) }),
      );
    });
    card.querySelector("[data-action=renew]")?.addEventListener("click", () => {
      void previewHarness(platform, workspaceId, adapterId, true).then((outcome) =>
        outcome.ok ? again({ plan: outcome.value }) : again({ error: harnessErrorMessage(outcome.error) }),
      );
    });
    card.querySelector("[data-action=verify]")?.addEventListener("click", () => {
      void verifyHarness(platform, workspaceId, adapterId).then((outcome) =>
        outcome.ok ? again({ verify: outcome.value }) : again({ error: harnessErrorMessage(outcome.error) }),
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
