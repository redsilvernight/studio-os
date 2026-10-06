/**
 * Intégration IA du projet — onglet du workspace (sous « Plus »).
 *
 * Lit GET /api/v1/projects/{id}/ai-integration et n'affiche, par poste, que ce
 * que le poste a lui-même rapporté (verdict, dernier rapport, outils détectés).
 * Le détail des agents vit dans la page Agents, pas ici. Le lancement à
 * distance n'existe pas : l'action reste une commande locale à copier.
 */
import type { StudioClient } from "../api";
import {
  getAiIntegrationStatus,
  type AiIntegrationStatus,
  type DesiredIntegration,
  type HarnessReport,
  type ReportedMachineIntegration,
} from "../aiIntegrationApi";
import { dsBadge, dsEmptyState, dsSkeleton } from "../ds/ds";
import { activityLabelFr } from "../machinesApi";
import { describeError, esc, fmtTime } from "../ui";

export interface AiIntegrationContext {
  client: StudioClient;
  projectId: string;
}

/** Commande locale idempotente qui remet le bundle IA du dépôt au niveau attendu. */
export const RESYNC_COMMAND = "studio-client bootstrap sync --repo-root .";

export interface MachineVerdict {
  label: string;
  tone: "success" | "warning" | "neutral";
  hint: string;
  needsAction: boolean;
}

/** Verdict en une phrase, uniquement à partir de ce que le poste a rapporté. */
export function machineVerdict(machine: ReportedMachineIntegration): MachineVerdict {
  const inSync = machine.bootstrap?.in_sync;
  if (machine.freshness === "never_reported") {
    return {
      label: "Pas encore configuré",
      tone: "neutral",
      hint: "Ce poste n'a encore rien rapporté pour ce projet.",
      needsAction: true,
    };
  }
  if (machine.project_registered === false) {
    return {
      label: "Projet non enregistré",
      tone: "warning",
      hint: "Le projet n'est pas encore enregistré sur ce poste.",
      needsAction: true,
    };
  }
  if (inSync === false) {
    return {
      label: "À mettre à jour",
      tone: "warning",
      hint: "La configuration IA de ce poste n'est plus à jour.",
      needsAction: true,
    };
  }
  if (machine.freshness === "stale") {
    return {
      label: "Rapport ancien",
      tone: "warning",
      hint: "Ce poste n'a pas donné de nouvelles récemment.",
      needsAction: true,
    };
  }
  if (inSync === true) {
    return { label: "À jour", tone: "success", hint: "La configuration IA de ce poste est à jour.", needsAction: false };
  }
  return {
    label: "Rapport reçu",
    tone: "neutral",
    hint: "Le poste a donné de ses nouvelles, sans détail sur sa configuration.",
    needsAction: false,
  };
}

/** Configuration attendue par le projet, en une ligne (le détail vit dans Agents). */
export function desiredHtml(
  desired: DesiredIntegration | null | undefined,
  desiredError: string | null | undefined,
): string {
  if (desired === null || desired === undefined) {
    if (desiredError !== null && desiredError !== undefined && desiredError !== "") {
      return (
        `<div class="ds-notice ds-notice--danger" role="alert"><strong>Configuration attendue indisponible.</strong> ` +
        `Elle n'a pas pu être calculée (${esc(desiredError)}).</div>`
      );
    }
    return "";
  }
  const agents = (desired.agent_keys ?? []).length;
  const items = Object.values(desired.artifact_counts ?? {}).reduce((sum, n) => sum + n, 0);
  return (
    `<p class="ds-list-sub">Ce projet attend ${agents} agent${agents > 1 ? "s" : ""} ` +
    `et ${items} élément${items > 1 ? "s" : ""} de configuration.</p>`
  );
}

function harnessChipHtml(harness: HarnessReport): string {
  if (!harness.detected) return "";
  return dsBadge(harness.harness_id, harness.configured ? "success" : "neutral");
}

/** Instruction locale de mise à jour pour un poste : rien n'est écrit depuis l'UI. */
export function resyncInstructionHtml(machine: ReportedMachineIntegration): string {
  return (
    `<div class="ai-resync" data-resync-panel="${esc(machine.machine_id)}" hidden>` +
    `<p class="ds-list-sub">À lancer <strong>sur le poste ${esc(machine.display_name)}</strong>, ` +
    `dans le dossier du projet. Ce tableau de bord n'écrit rien sur le poste.</p>` +
    `<pre class="code"><code>${esc(RESYNC_COMMAND)}</code></pre>` +
    `<button type="button" class="ds-btn ds-btn--sm" data-copy aria-label="Copier la commande de mise à jour">Copier la commande</button>` +
    `<span class="ds-list-sub" data-copy-msg role="status"></span>` +
    `</div>`
  );
}

/** Un poste : verdict, dernier rapport, outils détectés et, si besoin, la commande. */
export function machineItemHtml(machine: ReportedMachineIntegration): string {
  const verdict = machineVerdict(machine);
  const presence = activityLabelFr(machine.status, "canonical");
  const reported =
    machine.reported_at !== null && machine.reported_at !== undefined
      ? `Dernier rapport le ${fmtTime(machine.reported_at)}.`
      : "Aucun rapport.";
  const tools = (machine.harnesses ?? []).map(harnessChipHtml).join(" ");
  const action = verdict.needsAction
    ? `<div class="ai-machine-actions"><button type="button" class="ds-btn ds-btn--sm" data-resync="${esc(machine.machine_id)}">Mettre à jour…</button></div>` +
      resyncInstructionHtml(machine)
    : "";
  return (
    `<li class="ai-machine" data-machine="${esc(machine.machine_id)}">` +
    `<div class="ai-machine-head"><div class="grow">` +
    `<div class="ds-list-title">${esc(machine.display_name)}</div>` +
    `<div class="ds-list-sub">${esc(verdict.hint)} ${esc(reported)}</div></div>` +
    `${dsBadge(presence.label, presence.tone)} ${dsBadge(verdict.label, verdict.tone)}` +
    `</div>` +
    (tools === "" ? "" : `<div class="ai-machine-tools"><span class="ds-list-sub">Outils détectés</span> ${tools}</div>`) +
    action +
    `</li>`
  );
}

/** Corps de l'onglet : le résumé, puis un poste par ligne. */
export function aiIntegrationHtml(status: AiIntegrationStatus): string {
  const machines = status.machines ?? [];
  const upToDate = machines.filter((m) => machineVerdict(m).label === "À jour").length;
  const summary =
    machines.length === 0
      ? ""
      : `<p class="ai-summary"><strong>${upToDate} poste${upToDate > 1 ? "s" : ""} sur ${machines.length}</strong> à jour.</p>`;
  const body =
    machines.length === 0
      ? dsEmptyState(
          "Aucun poste n'a encore donné de nouvelles",
          "Quand un poste de l'équipe travaillera sur ce projet, son état apparaîtra ici.",
        )
      : `<ul class="ds-list">${machines.map(machineItemHtml).join("")}</ul>`;
  return (
    `<p class="ds-list-sub">Vérifiez que l'IA est bien installée sur chaque poste qui travaille sur ce projet.</p>` +
    summary +
    desiredHtml(status.desired, status.desired_error) +
    `<section class="workspace-section" aria-label="Postes">${body}</section>`
  );
}

function panelHtml(body: string): string {
  return (
    `<section class="ds-panel" aria-label="Intégration IA"><header><h2>Intégration IA</h2></header>` +
    `<div class="body">${body}</div></section>`
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
  root.innerHTML = panelHtml(dsSkeleton(3));
  try {
    const status = await getAiIntegrationStatus(ctx.client, ctx.projectId);
    root.innerHTML = panelHtml(
      aiIntegrationHtml(status) +
        `<div class="ai-refresh"><button type="button" class="ds-btn" data-refresh>Actualiser</button></div>`,
    );
    bind(root, ctx);
  } catch (error) {
    root.innerHTML = panelHtml(
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Intégration IA indisponible.</strong> ${esc(describeError(error))}</div>`,
    );
  }
}
