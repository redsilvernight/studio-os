/**
 * AIB R4 — panneau « Lancer sur… » de la fiche tâche (HTML pur).
 *
 * Le rendu ne fabrique jamais d'état : la machine cible est la seule à
 * rapporter l'exécution, l'UI affiche le statut du serveur tel quel. Un poste
 * hors ligne ou inéligible reste visible mais non sélectionnable, avec sa
 * raison.
 */
import { dsBadge, dsEmptyState, dsField, dsSectionHeader, dsSkeleton } from "../ds/ds";
import { esc, fmtTime } from "../ui";
import type { ResolvedAgentDefinition } from "../resolutionApi";
import type {
  HarnessReport,
  IneligibilityReason,
  MachineEligibility,
  TaskLaunch,
  TaskLaunchStatus,
} from "../taskLaunchesApi";

export interface AgentOption {
  stable_key: string;
}

export interface LaunchPanelData {
  machines: MachineEligibility[];
  agents: AgentOption[];
  latest: TaskLaunch | null;
}

export interface LaunchPanelState {
  data: LaunchPanelData | null;
  authed: boolean;
  selectedMachineId: string;
  selectedHarnessId: string;
  agentStableKey: string;
  preview: ResolvedAgentDefinition | null;
  previewLoading: boolean;
  previewError: string;
  notice: string;
  error: string;
}

const LAUNCH_STATUS_FR: Record<TaskLaunchStatus, string> = {
  requested: "Demandé",
  accepted: "Accepté par le poste",
  preparing: "Préparation",
  running: "En cours",
  succeeded: "Terminé (succès)",
  failed: "Échec",
  cancelled: "Annulé",
  rejected: "Refusé par le poste",
  expired: "Expiré",
};

export function taskLaunchStatusLabel(status: TaskLaunchStatus): string {
  return LAUNCH_STATUS_FR[status] ?? status;
}

export function taskLaunchStatusTone(
  status: TaskLaunchStatus,
): "neutral" | "success" | "warning" | "danger" | "info" {
  switch (status) {
    case "succeeded":
      return "success";
    case "failed":
    case "rejected":
      return "danger";
    case "expired":
      return "warning";
    case "accepted":
    case "preparing":
    case "running":
      return "info";
    default:
      return "neutral";
  }
}

const REASON_FR: Record<IneligibilityReason, string> = {
  offline: "hors ligne",
  no_capabilities_report: "aucun rapport de capacités",
  capabilities_stale: "rapport de capacités périmé",
  owner_no_project_access: "propriétaire sans accès au projet",
  project_not_registered: "projet non enregistré sur le poste",
  launches_not_accepted: "lancements non acceptés sur le poste",
  harness_incompatible: "harnais incompatible",
  at_capacity: "capacité atteinte",
};

export function ineligibilityReasonLabel(reason: IneligibilityReason): string {
  return REASON_FR[reason] ?? reason;
}

export function machineOptionLabel(machine: MachineEligibility): string {
  const suffix = machine.eligible
    ? `${machine.free_slots} place(s) libre(s)`
    : (machine.reasons ?? []).map(ineligibilityReasonLabel).join(", ") || "non éligible";
  return `${machine.display_name} · ${machine.status} · ${suffix}`;
}

export function selectedMachine(state: LaunchPanelState): MachineEligibility | null {
  if (state.data === null || state.selectedMachineId === "") return null;
  return state.data.machines.find((machine) => machine.machine_id === state.selectedMachineId) ?? null;
}

function machineOptions(state: LaunchPanelState, data: LaunchPanelData): string {
  const rows = data.machines.map((machine) => {
    const selected = machine.machine_id === state.selectedMachineId ? " selected" : "";
    const disabled = machine.eligible ? "" : " disabled";
    return `<option value="${esc(machine.machine_id)}"${disabled}${selected}>${esc(machineOptionLabel(machine))}</option>`;
  });
  return `<option value="">— Choisir un poste —</option>${rows.join("")}`;
}

function harnessOptions(state: LaunchPanelState, machine: MachineEligibility | null): string {
  const harnesses: HarnessReport[] = machine?.harnesses ?? [];
  if (machine === null || harnesses.length === 0) {
    return `<option value="">— Choisir un poste d'abord —</option>`;
  }
  const rows = harnesses.map((harness) => {
    const selected = harness.harness_id === state.selectedHarnessId ? " selected" : "";
    const disabled = harness.detected ? "" : " disabled";
    const mark = harness.detected ? (harness.configured ? "" : " (non configuré)") : " (non détecté)";
    return `<option value="${esc(harness.harness_id)}"${disabled}${selected}>${esc(harness.harness_id)}${mark}</option>`;
  });
  return `<option value="">— Choisir un harnais —</option>${rows.join("")}`;
}

function agentOptions(state: LaunchPanelState, data: LaunchPanelData): string {
  const rows = data.agents.map(
    (agent) =>
      `<option value="${esc(agent.stable_key)}"${agent.stable_key === state.agentStableKey ? " selected" : ""}>${esc(agent.stable_key)}</option>`,
  );
  return `<option value="">— Aucun agent (facultatif) —</option>${rows.join("")}`;
}

export function previewLines(resolved: ResolvedAgentDefinition): string[] {
  const lines: string[] = [];
  lines.push(`Agent ${resolved.agent.stable_key} v${resolved.agent.version}${resolved.agent.deprecated ? " (obsolète)" : ""}`);
  if (resolved.rules.length > 0) {
    lines.push(`Règles : ${resolved.rules.map((rule) => rule.stable_key).join(", ")}`);
  }
  if (resolved.skills.length > 0) {
    lines.push(`Skills : ${resolved.skills.map((skill) => skill.stable_key).join(", ")}`);
  }
  if (resolved.model_profile) {
    lines.push(`Profil de modèle : ${resolved.model_profile.stable_key} v${resolved.model_profile.version}`);
  }
  if (resolved.runtime) {
    const target = resolved.runtime.target;
    const refs = [target.harness_ref, target.provider_ref, target.model_ref].filter(
      (ref): ref is string => typeof ref === "string" && ref !== "",
    );
    lines.push(
      `Runtime (${resolved.runtime.level})${refs.length === 0 ? "" : ` : ${refs.join(" · ")}`}`,
    );
  }
  if (resolved.requirements.coding) lines.push("Exige un runtime capable de coder");
  return lines;
}

function previewHtml(state: LaunchPanelState): string {
  if (state.previewLoading) return dsSkeleton(3);
  if (state.previewError !== "") {
    return `<div class="ds-notice ds-notice--danger" role="alert">Aperçu indisponible : ${esc(state.previewError)}</div>`;
  }
  if (state.preview === null) {
    return `<p class="ds-list-sub">Choisissez un agent puis affichez l'aperçu de résolution avant de lancer.</p>`;
  }
  const lines = previewLines(state.preview);
  return `<ul class="ds-list" data-testid="launch-preview-list">${lines
    .map((line) => `<li class="ds-list-item"><div class="grow">${esc(line)}</div></li>`)
    .join("")}</ul>`;
}

function latestHtml(latest: TaskLaunch | null): string {
  if (latest === null) {
    return dsEmptyState("Aucun lancement", "Aucun lancement n'est enregistré pour cette tâche.");
  }
  const details = [
    `Poste ${esc(latest.machine_id)}`,
    `Harnais ${esc(latest.harness_id)}`,
    latest.agent_stable_key ? `Agent ${esc(latest.agent_stable_key)}` : "Sans agent",
  ];
  if (latest.session_id) details.push(`Session ${esc(latest.session_id)}`);
  if (latest.reason_code !== "none") details.push(`Motif ${esc(latest.reason_code)}`);
  return `<div class="ds-list-item" data-testid="launch-latest"><div class="grow">` +
    `<div class="ds-list-title">${esc(details.join(" · "))}</div>` +
    `<div class="ds-list-sub">Demandé ${esc(fmtTime(latest.created_at))} · expire ${esc(fmtTime(latest.expires_at))}` +
    (latest.finished_at ? ` · terminé ${esc(fmtTime(latest.finished_at))}` : "") +
    `</div>` +
    (latest.output_excerpt ? `<pre class="mono">${esc(latest.output_excerpt)}</pre>` : "") +
    `</div>${dsBadge(taskLaunchStatusLabel(latest.status), taskLaunchStatusTone(latest.status))}</div>`;
}

export function launchConfirmText(
  machine: MachineEligibility | null,
  harnessId: string,
  agentStableKey: string,
): string {
  const agent = agentStableKey === "" ? "sans agent résolu" : `avec l'agent « ${agentStableKey} »`;
  return (
    `Lancer cette tâche sur « ${machine?.display_name ?? "?"} » (harnais ${harnessId || "?"}, ${agent}) ? ` +
    `Le poste cible décide localement (opt-in, projet enregistré) et rapporte l'exécution ; le statut affiché ne vient que de lui.`
  );
}

export function launchPanelHtml(state: LaunchPanelState): string {
  const header = dsSectionHeader("Lancer sur…");
  const intro =
    `<p class="ds-list-sub">Lancement en modèle « pull » : le serveur enregistre une demande typée, le poste cible la tire, ` +
    `décide localement puis rapporte. Aucun état n'est inventé ici : seul le statut rapporté par le poste fait foi.</p>`;

  if (!state.authed) {
    return `<section class="task-detail-section" aria-label="Lancer sur une machine">${header}${intro}` +
      `<p class="ds-list-sub">Connectez-vous pour lancer cette tâche sur une machine.</p></section>`;
  }

  if (state.data === null) {
    return `<section class="task-detail-section" aria-label="Lancer sur une machine">${header}${intro}` +
      `<div class="ds-notice ds-notice--warning" role="status">Machines éligibles indisponibles pour le moment.</div></section>`;
  }

  const data = state.data;
  const machine = selectedMachine(state);
  const canPreview = state.agentStableKey !== "" && !state.previewLoading;
  const canLaunch = machine !== null && machine.eligible && state.selectedHarnessId !== "";
  const notice = state.notice === "" ? "" : `<p class="ds-notice ds-notice--info" role="status">${esc(state.notice)}</p>`;
  const error = state.error === "" ? "" : `<p class="ds-notice ds-notice--danger" role="alert">${esc(state.error)}</p>`;

  const form =
    `<div class="task-launch-form">` +
    dsField("launch-machine", "Poste cible", `<select class="ds-select" id="FIELD">${machineOptions(state, data)}</select>`) +
    dsField("launch-harness", "Harnais", `<select class="ds-select" id="FIELD">${harnessOptions(state, machine)}</select>`) +
    dsField("launch-agent", "Agent à résoudre (facultatif)", `<select class="ds-select" id="FIELD">${agentOptions(state, data)}</select>`) +
    `<div class="tasks-footer">` +
    `<button class="ds-btn" type="button" data-action="launch-preview"${canPreview ? "" : " disabled"}>Afficher l'aperçu de résolution</button>` +
    `<button class="ds-btn ds-btn--primary" type="button" data-action="launch-submit"${canLaunch ? "" : " disabled"}>Lancer sur cette machine</button>` +
    `</div>` +
    `</div>`;

  return `<section class="task-detail-section" aria-label="Lancer sur une machine" data-testid="launch-panel">` +
    `${header}${intro}${notice}${error}${form}` +
    `<div data-testid="launch-preview">${previewHtml(state)}</div>` +
    `<p class="ds-list-sub"><strong>Dernier lancement</strong></p>` +
    latestHtml(data.latest) +
    `</section>`;
}
