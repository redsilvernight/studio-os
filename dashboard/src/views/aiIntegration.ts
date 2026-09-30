/**
 * Intégration IA du projet (AIB P6) — onglet du workspace.
 *
 * Lit GET /api/v1/projects/{id}/ai-integration : l'état *désiré* (plan de
 * bootstrap agrégé, calculé par le serveur) à côté de ce que chaque poste a
 * *rapporté* (rapport de capacités du heartbeat, R1). Tout état rapporté est
 * daté et étiqueté « rapporté par le poste » : le serveur — et donc cet
 * onglet — n'affirme jamais une écriture qu'un poste n'a pas confirmée.
 *
 * Action « resynchroniser » : le lancement à distance (demande tirée par le
 * daemon, R2) n'existe pas encore, l'onglet reste donc en *mode instruction* —
 * une commande locale à exécuter sur le poste, jamais une écriture supposée.
 */
import type { StudioClient } from "../api";
import {
  getAiIntegrationStatus,
  type AiIntegrationStatus,
  type DesiredIntegration,
  type HarnessReport,
  type ReportedMachineIntegration,
  type ReportFreshness,
} from "../aiIntegrationApi";
import { dsBadge, dsEmptyState, dsSectionHeader, dsSkeleton } from "../ds/ds";
import { activityLabelFr } from "../machinesApi";
import { describeError, esc, fmtTime, shortId } from "../ui";

export interface AiIntegrationContext {
  client: StudioClient;
  projectId: string;
}

/** Commande locale idempotente qui remet le bundle IA du dépôt au niveau attendu. */
export const RESYNC_COMMAND = "studio-client bootstrap sync --repo-root .";

const FRESHNESS_LABEL: Record<ReportFreshness, string> = {
  fresh: "Rapporté récemment",
  stale: "Rapport périmé",
  never_reported: "Jamais rapporté",
};

const FRESHNESS_TONE: Record<ReportFreshness, "success" | "warning" | "neutral"> = {
  fresh: "success",
  stale: "warning",
  never_reported: "neutral",
};

const ARTIFACT_LABEL: Record<string, string> = {
  agent_definition: "Agents",
  model_profile: "Profils de modèle",
  skill: "Compétences",
  rule: "Règles",
  workflow: "Flux de travail",
};

function artifactLabel(kind: string): string {
  return ARTIFACT_LABEL[kind] ?? kind;
}

const BOOTSTRAP_STATE_LABEL = {
  up_to_date: "À jour",
  obsolete: "Obsolètes",
  modified: "Modifiés",
  absent: "Absents",
  incompatible: "Incompatibles",
} as const;

const BOOTSTRAP_STATE_ORDER = ["up_to_date", "obsolete", "modified", "absent", "incompatible"] as const;

/** État désiré (serveur) : le plan de bootstrap, ou l'erreur publique qui l'a empêché. */
export function desiredHtml(
  desired: DesiredIntegration | null | undefined,
  desiredError: string | null | undefined,
): string {
  if (desired === null || desired === undefined) {
    if (desiredError !== null && desiredError !== undefined && desiredError !== "") {
      return (
        `<div class="ds-notice ds-notice--danger" role="alert"><strong>État désiré indisponible.</strong> ` +
        `Le plan de bootstrap du projet n'a pas pu être calculé (${esc(desiredError)}).</div>`
      );
    }
    return `<p class="ds-list-sub">Aucun état désiré n'est disponible pour ce projet.</p>`;
  }
  const keys = desired.agent_keys ?? [];
  const counts = Object.entries(desired.artifact_counts ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const keysHtml =
    keys.length === 0
      ? `<p class="ds-list-sub">Aucun agent attendu.</p>`
      : `<ul class="ds-list">${keys
          .map(
            (key) =>
              `<li class="ds-list-item"><div class="grow"><code class="mono">${esc(key)}</code></div></li>`,
          )
          .join("")}</ul>`;
  const countsHtml =
    counts.length === 0
      ? `<p class="ds-list-sub">Aucun artefact attendu.</p>`
      : `<ul class="ds-list">${counts
          .map(
            ([kind, count]) =>
              `<li class="ds-list-item"><div class="grow">${esc(artifactLabel(kind))}</div>${dsBadge(String(count), "neutral")}</li>`,
          )
          .join("")}</ul>`;
  return (
    `<p class="ds-list-sub">Calculé par le serveur à partir du plan de bootstrap du projet — empreinte ` +
    `<code class="mono" title="${esc(desired.plan_hash)}">${esc(shortId(desired.plan_hash))}</code>.</p>` +
    `<div class="ai-desired">` +
    `<div><h3>Agents attendus (${keys.length})</h3>${keysHtml}</div>` +
    `<div><h3>Artefacts attendus</h3>${countsHtml}</div>` +
    `</div>`
  );
}

function harnessItemHtml(harness: HarnessReport): string {
  const detected = harness.detected ? dsBadge("Détecté", "success") : dsBadge("Non détecté", "neutral");
  const configured = harness.configured
    ? dsBadge("Configuré pour Studi'OS", "success")
    : dsBadge("Non configuré", "neutral");
  const version =
    harness.version !== null && harness.version !== undefined && harness.version !== ""
      ? `<span class="ds-list-sub">v${esc(harness.version)}</span>`
      : "";
  return (
    `<li class="ds-list-item"><div class="grow"><div class="ds-list-title">` +
    `<code class="mono">${esc(harness.harness_id)}</code> ${version}</div></div>${detected} ${configured}</li>`
  );
}

/** Instruction locale de resynchronisation pour un poste : rien n'est écrit depuis l'UI. */
export function resyncInstructionHtml(machine: ReportedMachineIntegration): string {
  return (
    `<div class="ai-resync" data-resync-panel="${esc(machine.machine_id)}" hidden>` +
    `<p class="ds-list-sub">Commande à exécuter <strong>sur le poste ${esc(machine.display_name)}</strong>, ` +
    `dans le dépôt du projet. Le lancement à distance (demande tirée par le daemon) n'est pas encore ` +
    `disponible : ce tableau de bord n'écrit rien sur le poste.</p>` +
    `<pre class="code"><code>${esc(RESYNC_COMMAND)}</code></pre>` +
    `<button type="button" class="ds-btn ds-btn--sm" data-copy aria-label="Copier la commande de resynchronisation">Copier la commande</button>` +
    `<span class="ds-list-sub" data-copy-msg role="status"></span>` +
    `</div>`
  );
}

/** Dernier contrôle local du bundle IA rapporté par le poste, ou son absence. */
function bootstrapBlockHtml(machine: ReportedMachineIntegration): string {
  const bootstrap = machine.bootstrap;
  if (bootstrap === null || bootstrap === undefined) {
    if (machine.freshness === "never_reported") return "";
    return `<p class="ds-list-sub">Aucun état de bootstrap local rapporté par le poste.</p>`;
  }
  const sync = bootstrap.in_sync
    ? dsBadge("Bundle à jour", "success")
    : dsBadge("Bundle à mettre à jour", "warning");
  const counts = BOOTSTRAP_STATE_ORDER.map(
    (key) =>
      `<li class="ds-list-item"><div class="grow">${esc(BOOTSTRAP_STATE_LABEL[key])}</div>${dsBadge(String(bootstrap.summary[key]), "neutral")}</li>`,
  ).join("");
  return (
    `<div class="ai-bootstrap"><p class="ds-list-sub">État du bundle IA observé par le poste, ` +
    `vérifié le ${fmtTime(bootstrap.checked_at)} — ${sync}</p><ul class="ds-list">${counts}</ul></div>`
  );
}

/** Un poste et ce qu'il a rapporté, plus l'action de resynchronisation (instruction). */
export function machineItemHtml(machine: ReportedMachineIntegration): string {
  const presence = activityLabelFr(machine.status, "canonical");
  const freshness = FRESHNESS_LABEL[machine.freshness];
  const reported =
    machine.reported_at !== null && machine.reported_at !== undefined
      ? `Rapporté le ${fmtTime(machine.reported_at)}`
      : "Aucun rapport daté";
  const registered =
    machine.project_registered === true
      ? dsBadge("Projet enregistré sur le poste", "success")
      : machine.project_registered === false
        ? dsBadge("Projet non enregistré", "warning")
        : dsBadge("Enregistrement inconnu", "neutral");
  const harnesses = machine.harnesses ?? [];
  const harnessBlock =
    machine.freshness === "never_reported"
      ? `<p class="ds-list-sub">Ce poste n'a jamais rapporté son état : rien n'est affiché au lieu d'être supposé.</p>`
      : harnesses.length === 0
        ? `<p class="ds-list-sub">Aucun harnais rapporté.</p>`
        : `<ul class="ds-list">${harnesses.map(harnessItemHtml).join("")}</ul>`;
  return (
    `<li class="ai-machine" data-machine="${esc(machine.machine_id)}">` +
    `<div class="ai-machine-head"><div class="grow">` +
    `<div class="ds-list-title">${esc(machine.display_name)}</div>` +
    `<div class="ds-list-sub">${esc(reported)} · ${esc(freshness)}</div></div>` +
    `${dsBadge(presence.label, presence.tone)} ${dsBadge(freshness, FRESHNESS_TONE[machine.freshness])}` +
    `</div>` +
    `<div class="ai-machine-body"><p class="ds-list-sub">${registered}</p>${harnessBlock}${bootstrapBlockHtml(machine)}</div>` +
    `<div class="ai-machine-actions"><button type="button" class="ds-btn ds-btn--sm" data-resync="${esc(machine.machine_id)}">Resynchroniser…</button></div>` +
    resyncInstructionHtml(machine) +
    `</li>`
  );
}

/** Corps complet de l'onglet : état désiré puis état rapporté, jamais confondus. */
export function aiIntegrationHtml(status: AiIntegrationStatus): string {
  const machines = status.machines ?? [];
  const machinesBody =
    machines.length === 0
      ? dsEmptyState(
          "Aucun poste n'a rapporté d'état",
          "Aucun de vos postes n'a encore rapporté de capacités pour ce projet. L'état apparaîtra à son prochain rapport.",
        )
      : `<ul class="ds-list">${machines.map(machineItemHtml).join("")}</ul>`;
  return (
    `<p class="ds-list-sub">Deux colonnes à ne pas confondre : l'<strong>état désiré</strong> est calculé par le ` +
    `serveur, l'<strong>état rapporté</strong> est une déclaration de chaque poste, datée. Aucune écriture n'est ` +
    `affirmée tant qu'un poste ne l'a pas rapportée.</p>` +
    `<section class="workspace-section" aria-label="État désiré">` +
    `${dsSectionHeader("État désiré (serveur)")}${desiredHtml(status.desired, status.desired_error)}</section>` +
    `<section class="workspace-section" aria-label="État rapporté par les postes">` +
    `${dsSectionHeader(`Rapporté par les postes (${machines.length})`)}${machinesBody}</section>`
  );
}

function panelHtml(subtitle: string, body: string): string {
  return (
    `<section class="ds-panel" aria-label="Intégration IA"><header><h2>Intégration IA</h2>` +
    `<span class="ds-list-sub">${esc(subtitle)}</span></header><div class="body">${body}</div></section>`
  );
}

function copyText(text: string, msg: HTMLElement | null): void {
  const done = (ok: boolean): void => {
    if (msg !== null) {
      msg.textContent = ok
        ? "Commande copiée."
        : "Copie automatique impossible — sélectionnez la commande et copiez-la manuellement.";
    }
  };
  const clipboard = navigator.clipboard;
  if (clipboard === undefined) {
    done(false);
    return;
  }
  clipboard.writeText(text).then(() => done(true)).catch(() => done(false));
}

function bind(root: HTMLElement, ctx: AiIntegrationContext): void {
  root.querySelector<HTMLButtonElement>("[data-refresh]")?.addEventListener("click", (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    button.disabled = true;
    void renderAiIntegrationInto(root, ctx);
  });
  root.querySelectorAll<HTMLButtonElement>("[data-resync]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset["resync"] ?? "";
      const panel = root.querySelector<HTMLElement>(`[data-resync-panel="${CSS.escape(id)}"]`);
      if (panel !== null) panel.hidden = !panel.hidden;
    });
  });
  root.querySelectorAll<HTMLButtonElement>("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => {
      const panel = button.closest("[data-resync-panel]");
      const code = panel?.querySelector("code");
      const msg = panel?.querySelector("[data-copy-msg]");
      copyText(code?.textContent ?? RESYNC_COMMAND, msg instanceof HTMLElement ? msg : null);
    });
  });
}

export async function renderAiIntegrationInto(root: HTMLElement, ctx: AiIntegrationContext): Promise<void> {
  root.innerHTML = panelHtml("", dsSkeleton(3));
  try {
    const status = await getAiIntegrationStatus(ctx.client, ctx.projectId);
    const machines = status.machines ?? [];
    root.innerHTML = panelHtml(
      `${machines.length} poste(s) · état rapporté daté, jamais une écriture supposée`,
      aiIntegrationHtml(status) +
        `<div class="ai-refresh"><button type="button" class="ds-btn" data-refresh>Vérifier l'état</button>` +
        `<span class="ds-list-sub" data-msg role="status"></span></div>`,
    );
    bind(root, ctx);
  } catch (error) {
    root.innerHTML = panelHtml(
      "",
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Intégration IA indisponible.</strong> ${esc(describeError(error))}</div>`,
    );
  }
}
