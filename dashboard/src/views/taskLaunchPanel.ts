/**
 * AIB R4 — panneau « Lancer sur… » de la fiche tâche (HTML pur).
 *
 * Le rendu ne fabrique jamais d'état : la machine cible est la seule à
 * rapporter l'exécution, l'UI affiche le statut du serveur tel quel. Un poste
 * hors ligne ou inéligible reste visible mais non sélectionnable, avec sa
 * raison. Le suivi relit la même vérité serveur ; l'annulation n'est offerte
 * qu'au demandeur (ou à un administrateur), sur un lancement non terminal.
 *
 * Le statut du processus et la preuve de protocole sont deux faits distincts :
 * un code de sortie 0 décrit le processus, jamais le travail rendu. Un handoff
 * reçu est un résultat transmis, jamais une validation.
 */
import { dsBadge, dsEmptyState, dsField, dsSectionHeader, dsSkeleton, type DsTone } from "../ds/ds";
import { machineLabel } from "../actorNames";
import { esc, fmtTime } from "../ui";
import type { AuthIdentity } from "../identityApi";
import type { ResolvedAgentDefinition } from "../resolutionApi";
import { taskStatusLabel } from "../taskStatus";
import type {
  HarnessReport,
  IneligibilityReason,
  MachineEligibility,
  TaskLaunch,
  TaskLaunchProtocol,
  TaskLaunchProtocolStatus,
  TaskLaunchStatus,
  TaskLaunchWithProtocol,
} from "../taskLaunchesApi";

export interface AgentOption {
  stable_key: string;
}

/** Session liée à un lancement, réduite à ce que l'UI affiche (état, handoff). */
export interface LaunchSession {
  id: string;
  ended_at?: string | null;
}

export interface LaunchPanelData {
  machines: MachineEligibility[];
  agents: AgentOption[];
  /** Dernier lancement du projet pour cette tâche : porte la preuve de protocole. */
  latest: TaskLaunchWithProtocol | null;
  /** Sessions de la tâche, pour résoudre l'état de la session liée (best-effort). */
  sessions?: LaunchSession[] | null;
}

export interface LaunchPanelState {
  data: LaunchPanelData | null;
  authed: boolean;
  /** Droit d'annuler le dernier lancement affiché, recalculé à chaque relecture. */
  canCancel: boolean;
  selectedMachineId: string;
  selectedHarnessId: string;
  agentStableKey: string;
  preview: ResolvedAgentDefinition | null;
  previewLoading: boolean;
  previewError: string;
  latestLoading: boolean;
  notice: string;
  error: string;
}

const LAUNCH_STATUS_FR: Record<TaskLaunchStatus, string> = {
  requested: "Demandé",
  accepted: "Accepté par le poste",
  preparing: "Préparation",
  running: "En cours",
  succeeded: "Processus terminé (code 0)",
  failed: "Échec",
  cancelled: "Annulé",
  rejected: "Refusé par le poste",
  expired: "Expiré",
};

const TERMINAL_LAUNCH_STATUSES: readonly TaskLaunchStatus[] = [
  "succeeded",
  "failed",
  "cancelled",
  "rejected",
  "expired",
];

/** Un lancement terminal n'évolue plus : plus de suivi actif ni d'annulation. */
export function isTerminalLaunch(status: TaskLaunchStatus): boolean {
  return TERMINAL_LAUNCH_STATUSES.includes(status);
}

/**
 * Indice UI (le serveur revérifie, DEC-0152) : seul le demandeur ou un
 * administrateur annule, et seulement un lancement non terminal. Identité
 * inconnue : le bouton reste masqué, jamais accordé par défaut.
 */
export function canCancelLaunch(
  launch: TaskLaunch,
  identity: AuthIdentity | null | undefined,
): boolean {
  if (isTerminalLaunch(launch.status)) return false;
  if (identity === null || identity === undefined) return false;
  if (identity.role === "admin") return true;
  return identity.user_id === launch.requested_by_user_id;
}

export function cancelLaunchConfirmText(launch: TaskLaunch): string {
  return (
    `Annuler ce lancement sur le poste ${machineLabel(launch.machine_id)} ? ` +
    `Le serveur marque la demande annulée ; seule la machine cible rapporte ensuite l'arrêt de son exécution.`
  );
}

export function taskLaunchStatusLabel(status: TaskLaunchStatus): string {
  return LAUNCH_STATUS_FR[status] ?? status;
}

export function taskLaunchStatusTone(
  status: TaskLaunchStatus,
): "neutral" | "success" | "warning" | "danger" | "info" {
  switch (status) {
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
      // `succeeded` reste neutre : un code de sortie 0 décrit le processus,
      // pas le travail rendu par l'agent (voir le badge de protocole).
      return "neutral";
  }
}

/**
 * Preuve de protocole d'un lancement, telle que la liste projet la dérive.
 * Son absence (lecture par id, serveur plus ancien) vaut « non vérifié » :
 * l'UI ne comble jamais le trou par une lecture du code de sortie.
 */
export function launchProtocolStatus(launch: TaskLaunchWithProtocol): TaskLaunchProtocolStatus {
  return launch.protocol?.status ?? "unverified";
}

/**
 * Statut de la tâche au moment du handoff. `completed` reste « à relire » :
 * une tâche marquée terminée par l'agent n'est ni relue ni validée ici.
 */
export function launchProtocolTaskLabel(taskStatus: string | null | undefined): string | null {
  if (taskStatus === null || taskStatus === undefined || taskStatus === "") return null;
  if (taskStatus === "completed") return "à relire";
  return taskStatusLabel(taskStatus);
}

export function launchProtocolBadgeLabel(protocol: TaskLaunchProtocol | null | undefined): string | null {
  const status = protocol?.status ?? "unverified";
  if (status === "not_applicable") return null;
  if (status === "awaiting") return "Handoff attendu";
  if (status === "unverified") return "Protocole non vérifié";
  const taskLabel = launchProtocolTaskLabel(protocol?.task_status);
  return taskLabel === null ? "Handoff reçu" : `Handoff reçu · tâche : ${taskLabel}`;
}

/** Ton du badge : un handoff reçu n'est jamais un succès, donc jamais vert. */
export function launchProtocolBadgeTone(status: TaskLaunchProtocolStatus): DsTone {
  switch (status) {
    case "awaiting":
      return "info";
    case "unverified":
      return "warning";
    default:
      return "neutral";
  }
}

/** Badge de protocole à côté du statut ; vide quand le protocole ne s'applique pas. */
export function launchProtocolBadgeHtml(launch: TaskLaunchWithProtocol): string {
  const status = launchProtocolStatus(launch);
  const label = launchProtocolBadgeLabel(launch.protocol);
  if (label === null) return "";
  return dsBadge(label, launchProtocolBadgeTone(status));
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

const REASON_CODE_FR: Record<string, string> = {
  none: "aucun",
  not_opted_in: "poste non opt-in",
  project_not_registered: "projet non enregistré sur le poste",
  harness_not_allowed: "harnais non autorisé",
  harness_not_found: "harnais introuvable",
  agent_not_found: "agent introuvable",
  capacity_reached: "capacité atteinte",
  preparation_failed: "préparation échouée",
  harness_exited: "harnais interrompu",
  cancelled_by_requester: "annulé par le demandeur",
  expired_unpulled: "expiré sans avoir été tiré",
  expired_timeout: "expiré (délai dépassé)",
};

export function launchReasonCodeLabel(reasonCode: string): string {
  return REASON_CODE_FR[reasonCode] ?? reasonCode;
}

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
    return `<option value="">— Choisissez un poste, puis un mode d'exécution —</option>`;
  }
  const rows = harnesses.map((harness) => {
    const selected = harness.harness_id === state.selectedHarnessId ? " selected" : "";
    const disabled = harness.detected ? "" : " disabled";
    const mark = harness.detected ? (harness.configured ? "" : " (non configuré)") : " (non détecté)";
    return `<option value="${esc(harness.harness_id)}"${disabled}${selected}>${esc(harness.harness_id)}${mark}</option>`;
  });
  return `<option value="">— Choisir un mode d'exécution —</option>${rows.join("")}`;
}

/** Nom lisible d'un modèle d'agent : la clé technique (`review-helper`) devient « Review helper ». */
export function agentDisplayName(stableKey: string): string {
  const spaced = stableKey.replace(/[-_.]+/g, " ").trim();
  return spaced === "" ? stableKey : spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function agentOptions(state: LaunchPanelState, data: LaunchPanelData): string {
  const rows = data.agents.map(
    (agent) =>
      `<option value="${esc(agent.stable_key)}"${agent.stable_key === state.agentStableKey ? " selected" : ""}>${esc(agentDisplayName(agent.stable_key))}</option>`,
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
    lines.push(`Compétences : ${resolved.skills.map((skill) => skill.stable_key).join(", ")}`);
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
    return `<p class="ds-list-sub">Choisissez un agent puis affichez la configuration de lancement avant de lancer.</p>`;
  }
  const lines = previewLines(state.preview);
  return `<ul class="ds-list" data-testid="launch-preview-list">${lines
    .map((line) => `<li class="ds-list-item"><div class="grow">${esc(line)}</div></li>`)
    .join("")}</ul>`;
}

/**
 * Lien vers la session liée et, si elle est terminée, vers le travail IA /
 * handoff de la tâche. L'état affiché vient des sessions chargées ; à défaut
 * le lien reste, sans inventer d'état.
 */
export function linkedSessionHtml(state: LaunchPanelState, latest: TaskLaunchWithProtocol): string {
  if (!latest.session_id) return "";
  const linked = state.data?.sessions?.find((session) => session.id === latest.session_id) ?? null;
  const ended = linked !== null && linked.ended_at !== null && linked.ended_at !== undefined && linked.ended_at !== "";
  const stateLabel = linked === null ? "" : ended ? " (terminée)" : " (en cours)";
  const sessionLink =
    `<a href="#task-sessions" data-testid="launch-session-link">Voir la session${stateLabel}</a>`;
  const handoff = ended
    ? ` · <a href="#task-ai-work" data-testid="launch-handoff-link">voir le travail rendu par l'agent</a>`
    : "";
  return `<div class="ds-list-sub">${sessionLink}${handoff}</div>`;
}

export function latestHtml(state: LaunchPanelState): string {
  const latest = state.data?.latest ?? null;
  if (latest === null) {
    return dsEmptyState("Aucun lancement", "Aucun lancement n'est enregistré pour cette tâche.");
  }
  const details = [
    `Poste ${esc(latest.machine_id)}`,
    `Harnais ${esc(latest.harness_id)}`,
    latest.agent_stable_key ? `Agent ${esc(latest.agent_stable_key)}` : "Sans agent",
  ];
  if (latest.reason_code !== "none") details.push(`Motif ${esc(launchReasonCodeLabel(latest.reason_code))}`);
  const actions =
    `<div class="tasks-footer" data-testid="launch-actions">` +
    `<button class="ds-btn" type="button" data-action="launch-refresh"${state.latestLoading ? " disabled" : ""}>` +
    `${state.latestLoading ? "Actualisation…" : "Actualiser l'état"}</button>` +
    (state.canCancel
      ? `<button class="ds-btn ds-btn--danger" type="button" data-action="launch-cancel">Annuler le lancement</button>`
      : "") +
    `</div>`;
  const protocolBadge = launchProtocolBadgeHtml(latest);
  const badges =
    dsBadge(taskLaunchStatusLabel(latest.status), taskLaunchStatusTone(latest.status)) +
    (protocolBadge === "" ? "" : ` ${protocolBadge}`);
  return `<div class="ds-list-item" data-testid="launch-latest"><div class="grow">` +
    `<div class="ds-list-title">${esc(details.join(" · "))}</div>` +
    `<div class="ds-list-sub">Demandé ${esc(fmtTime(latest.created_at))} · expire ${esc(fmtTime(latest.expires_at))}` +
    (latest.finished_at ? ` · terminé ${esc(fmtTime(latest.finished_at))}` : "") +
    `</div>` +
    linkedSessionHtml(state, latest) +
    (latest.output_excerpt ? `<pre class="mono">${esc(latest.output_excerpt)}</pre>` : "") +
    actions +
    `</div>${badges}</div>`;
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
    `<p class="ds-list-sub">Le lancement reste une demande : le poste choisi la récupère dès qu'il est disponible, l'exécute localement, puis rapporte l'état réel.</p>`;

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
    `<button class="ds-btn" type="button" data-action="launch-preview"${canPreview ? "" : " disabled"}>Afficher la configuration de lancement</button>` +
    `<button class="ds-btn ds-btn--primary" type="button" data-action="launch-submit"${canLaunch ? "" : " disabled"}>Lancer sur cette machine</button>` +
    `</div>` +
    `</div>`;

  return `<section class="task-detail-section" aria-label="Lancer sur une machine" data-testid="launch-panel">` +
    `${header}${intro}${notice}${error}${form}` +
    `<div data-testid="launch-preview">${previewHtml(state)}</div>` +
    `<p class="ds-list-sub"><strong>Dernier lancement</strong> — l'état affiché est celui rapporté par la machine cible.</p>` +
    latestHtml(state) +
    `</section>`;
}
