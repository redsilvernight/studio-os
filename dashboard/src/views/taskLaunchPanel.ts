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
import type { UsageSummary } from "../usageApi";
import { usageTotalText } from "./usage";
import type {
  ExecutionSnapshot,
  ExecutionSnapshotPayload,
  ReplayDifference,
  ReplayLimitation,
  TaskLaunchReplayPreview,
  HarnessReport,
  IneligibilityReason,
  MachineEligibility,
  SnapshotAppliedParameters,
  SnapshotCaptureError,
  SnapshotResolution,
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
  /**
   * Snapshot figé du dernier lancement (DEC-0199). `undefined` = pas encore
   * lu, `null` = la machine n'a rien enregistré (404). Dans les deux cas la
   * provenance ne comble rien : elle nomme l'absence.
   */
  snapshot?: ExecutionSnapshot | null;
  /** Usage rattaché à ce lancement (ledger) ; mêmes conventions que `snapshot`. */
  usage?: UsageSummary | null;
  /** Aperçu de rejeu (DEC-0214), lecture seule ; mêmes conventions que `snapshot`. */
  replay?: TaskLaunchReplayPreview | null;
}

export interface LaunchPanelState {
  data: LaunchPanelData | null;
  authed: boolean;
  /** Droit d'annuler le dernier lancement affiché, recalculé à chaque relecture. */
  canCancel: boolean;
  selectedMachineId: string;
  selectedHarnessId: string;
  agentStableKey: string;
  allowProduction?: boolean;
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
 * Statut courant de la tâche après le handoff. `completed` reste « à relire » :
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
  launch_safety_unsupported: "mise à jour du poste requise pour les lancements protégés",
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
    latest.allow_production ? "Production autorisée pour ce lancement" : "Mode protégé",
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
  allowProduction = false,
): string {
  const agent = agentStableKey === "" ? "sans agent résolu" : `avec l'agent « ${agentStableKey} »`;
  return (
    `Lancer cette tâche sur « ${machine?.display_name ?? "?"} » (harnais ${harnessId || "?"}, ${agent}) ? ` +
    (allowProduction
      ? `Vous autorisez explicitement les commandes et les actions de production pour ce lancement uniquement. `
      : `Mode protégé : édition locale uniquement, sans exécution de commandes. `) +
    `Le poste cible décide localement (opt-in, projet enregistré) et rapporte l'exécution ; le statut affiché ne vient que de lui.`
  );
}

/**
 * Provenance (DEC-0199) — neuf questions sur ce qu'une exécution a été, lues
 * dans le seul enregistrement figé du run.
 *
 * Deux règles structurent la section. Le rendu ne lit jamais la configuration
 * courante (profil, résolveur, postes) : seul le snapshot fait foi, seul le
 * lancement figé complète ce que la capture ne porte pas. Et chaque fait manquant
 * est nommé « inconnu » avec sa cause — une case vide serait lue comme une
 * information, donc comme une valeur inventée.
 */
export interface ProvenanceFact {
  /** Ancre stable : une question par identifiant, dans l'ordre d'affichage. */
  id: string;
  question: string;
  answer: string;
}

const UNKNOWN = "inconnu";

/** Fait absent : le trou est nommé, jamais comblé. */
function unknown(note = ""): string {
  return note === "" ? UNKNOWN : `${UNKNOWN} (${note})`;
}

function rawText(value: string | null | undefined): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/** Date affichée sans échappement interne : la réponse entière est échappée une fois. */
function timeText(value: string | null | undefined): string {
  const raw = rawText(value);
  if (raw === null) return unknown("date absente");
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString("fr-FR");
}

/** Empreinte affichée abrégée : elle prouve une identité, elle ne la reconstitue pas. */
export function shortDigest(digest: string): string {
  const separator = digest.indexOf(":");
  const prefix = separator === -1 ? "" : digest.slice(0, separator + 1);
  const body = separator === -1 ? digest : digest.slice(separator + 1);
  return body.length <= 12 ? digest : `${prefix}${body.slice(0, 12)}…`;
}

function digestText(value: string | null | undefined, note = "empreinte absente"): string {
  const raw = rawText(value);
  return raw === null ? unknown(note) : shortDigest(raw);
}

function profileText(profile: { stable_key: string; contract_version: number; digest: string } | null | undefined): string | null {
  const key = rawText(profile?.stable_key);
  if (key === null) return null;
  const version = typeof profile?.contract_version === "number" ? ` v${profile.contract_version}` : "";
  const digest = rawText(profile?.digest);
  return `${key}${version}${digest === null ? "" : ` (${shortDigest(digest)})`}`;
}

const RESOURCE_ROLE_FR: Record<string, string> = {
  agent: "agent",
  rule: "règle",
  skill: "compétence",
  model_profile: "profil de modèle",
  workflow: "flux",
  composed_agent: "agent composé",
};

function resourceText(resource: NonNullable<SnapshotResolution["resources"]>[number]): string {
  const key = rawText(resource.stable_key);
  if (key === null) return unknown("clé stable absente");
  const role = RESOURCE_ROLE_FR[resource.role] ?? resource.role;
  const version = typeof resource.version === "number" ? ` v${resource.version}` : "";
  const digest = rawText(resource.content_digest);
  return `${role} ${key}${version}${digest === null ? "" : ` (${shortDigest(digest)})`}`;
}

function runtimeText(resolution: SnapshotResolution | null | undefined): string {
  const runtime = resolution?.runtime ?? null;
  const level = rawText(runtime?.level);
  if (runtime === null || runtime === undefined || level === null) return unknown("runtime non capturé");
  const matched = rawText(runtime.matched_stable_key);
  const refs = [
    rawText(runtime.harness_ref) === null ? null : `harnais ${String(rawText(runtime.harness_ref))}`,
    rawText(runtime.provider_ref) === null ? null : `fournisseur ${String(rawText(runtime.provider_ref))}`,
    rawText(runtime.model_ref) === null ? null : `modèle ${String(rawText(runtime.model_ref))}`,
  ].filter((line): line is string => line !== null);
  return (
    `${level}${matched === null ? "" : ` → ${matched}`}` +
    (refs.length === 0 ? "" : ` (${refs.join(", ")})`) +
    ` · capacités ${digestText(runtime?.capabilities_digest)}`
  );
}

function projectionsText(applied: SnapshotAppliedParameters | null | undefined): string {
  const projections = applied?.projections ?? [];
  if (projections.length === 0) return unknown("aucune projection enregistrée");
  return projections
    .map((projection) => `${rawText(projection.target) ?? unknown("cible absente")} (${digestText(projection.digest)})`)
    .join(" · ");
}

function contextText(payload: ExecutionSnapshotPayload | null | undefined): string {
  const resolution = payload?.resolution ?? null;
  const applied = payload?.applied ?? null;
  if (resolution === null && applied === null) return unknown("résolution et paramètres non capturés");
  const resources = resolution?.resources ?? [];
  return [
    `agent ${rawText(resolution?.agent_stable_key) ?? unknown("agent non capturé")}`,
    resources.length === 0 ? "aucune ressource résolue" : resources.map(resourceText).join(" · "),
    `runtime : ${runtimeText(resolution)}`,
    `projections : ${projectionsText(applied)}`,
  ].join(" · ");
}

function configurationText(payload: ExecutionSnapshotPayload | null | undefined): string {
  const applied = payload?.applied ?? null;
  const resolution = payload?.resolution ?? null;
  const appliedProfile = profileText(applied?.profile);
  const previewProfile = profileText(resolution?.profile);
  const profile = appliedProfile ?? previewProfile ?? unknown("profil non capturé");
  const drift =
    appliedProfile !== null && previewProfile !== null && appliedProfile !== previewProfile
      ? ` · dérive par rapport à la preview : ${previewProfile}`
      : "";
  const harness = rawText(applied?.harness_id);
  const harnessVersion = rawText(applied?.harness_version);
  const accessMode =
    rawText(applied?.access_mode) ??
    (applied !== null && applied.access_mode === null ? "aucun mode imposé" : unknown("mode non capturé"));
  return (
    `profil ${profile}${drift}` +
    ` · harnais ${harness ?? unknown("harnais non capturé")}` +
    ` ${harnessVersion ?? unknown("version inconnue")}` +
    ` · mode d'accès ${accessMode}`
  );
}

function codeText(applied: SnapshotAppliedParameters | null | undefined): string {
  const sha = rawText(applied?.git_sha);
  const dirty =
    typeof applied?.git_dirty === "boolean"
      ? applied.git_dirty
        ? "worktree modifié"
        : "worktree propre"
      : unknown("propreté non capturée");
  return `commit ${sha ?? unknown("commit non capturé")} · ${dirty}`;
}

function whenText(launch: TaskLaunch | null): string {
  if (launch === null) return unknown("lancement absent");
  return (
    `demandé le ${timeText(launch.created_at)}` +
    ` · terminé le ${rawText(launch.finished_at) === null ? unknown("lancement non terminé") : timeText(launch.finished_at)}` +
    ` · expire le ${timeText(launch.expires_at)}`
  );
}

function outcomeText(launch: TaskLaunch | null): string {
  if (launch === null) return unknown("lancement absent");
  const withProtocol = launch as TaskLaunchWithProtocol;
  const protocol = launchProtocolBadgeLabel(withProtocol.protocol) ?? "protocole non applicable";
  const reason = launch.reason_code !== "none" ? launchReasonCodeLabel(launch.reason_code) : "aucun motif signalé";
  return `${taskLaunchStatusLabel(launch.status)} · ${reason} · ${protocol}`;
}

const CAPTURE_STATUS_FR: Record<string, string> = {
  ok: "capture complète",
  partial: "capture partielle",
  failed: "capture échouée",
};

export function captureStatusLabel(status: string): string {
  return CAPTURE_STATUS_FR[status] ?? status;
}

/** `ok` décrit la capture, pas le travail rendu : le badge reste neutre. */
export function captureStatusTone(status: string): DsTone {
  if (status === "failed") return "danger";
  if (status === "partial") return "warning";
  return "neutral";
}

function captureErrorsText(snapshot: ExecutionSnapshot | null | undefined): string {
  if (snapshot === null || snapshot === undefined) return unknown("aucune capture");
  const errors: SnapshotCaptureError[] = snapshot.payload?.capture_errors ?? [];
  const status = captureStatusLabel(rawText(snapshot.capture_status) ?? UNKNOWN);
  const reason = rawText(snapshot.capture_reason);
  if (errors.length === 0) {
    return `${status} · ${reason === null ? "aucune erreur de capture" : `motif : ${reason}`}`;
  }
  return (
    `${status} · ${errors
      .map((error) => {
        const field = rawText(error.field);
        return `${error.code}${field === null ? "" : ` (${field})`} : ${error.detail}`;
      })
      .join(" · ")}`
  );
}

function howMuchText(usage: UsageSummary | null | undefined): string {
  if (usage === undefined) return unknown("consommation pas encore chargée");
  if (usage === null) return unknown("consommation illisible");
  const total = usage.total;
  if (total.entries === 0) return unknown("aucune mesure d'usage rattachée à ce lancement");
  return `${total.entries} mesure${total.entries > 1 ? "s" : ""} · ${usageTotalText(total)}`;
}

/**
 * Les neuf réponses, toujours neuf. `launch`, `snapshot` et l'usage enregistré
 * pour ce lancement sont les seules entrées : la configuration courante n'a
 * aucun chemin vers cette fonction.
 */
export function provenanceFacts(
  launch: TaskLaunch | null,
  snapshot: ExecutionSnapshot | null | undefined,
  usage?: UsageSummary | null,
): ProvenanceFact[] {
  const payload = snapshot?.payload ?? null;
  const resolution = payload?.resolution ?? null;
  const applied = payload?.applied ?? null;
  const requester = rawText(launch?.requested_by_user_id);
  const agent = rawText(resolution?.agent_stable_key) ?? rawText(launch?.agent_stable_key);
  const machine = rawText(launch?.machine_id);
  const branch = rawText(applied?.worktree_branch);
  return [
    {
      id: "who",
      question: "Qui",
      answer: `demandeur ${requester ?? unknown("demandeur non enregistré")} · agent ${agent ?? unknown("agent non capturé")}`,
    },
    {
      id: "where",
      question: "Où",
      answer: `poste ${machine ?? unknown("poste non enregistré")} · branche ${branch ?? unknown("branche non capturée")}`,
    },
    { id: "config", question: "Quelle configuration", answer: configurationText(payload) },
    { id: "context", question: "Quel contexte", answer: contextText(payload) },
    { id: "code", question: "Quel code", answer: codeText(applied) },
    { id: "when", question: "Quand", answer: whenText(launch) },
    { id: "how-much", question: "Combien", answer: howMuchText(usage) },
    { id: "outcome", question: "Quel résultat", answer: outcomeText(launch) },
    { id: "capture", question: "Quelles erreurs de capture", answer: captureErrorsText(snapshot) },
  ];
}

function provenanceNotice(snapshot: ExecutionSnapshot | null | undefined): string {
  if (snapshot === undefined) {
    return `<p class="ds-list-sub" data-testid="launch-provenance-notice">Snapshot pas encore chargé pour ce lancement.</p>`;
  }
  if (snapshot === null) {
    return (
      `<p class="ds-notice ds-notice--warning" role="status" data-testid="launch-provenance-notice">` +
      `Cet lancement n'a aucun snapshot d'exécution enregistré : la machine cible ne l'a pas encore rapporté.</p>`
    );
  }
  return (
    `<p class="ds-list-sub">Ce que la machine a réellement appliqué, figé au moment du run. ` +
    `Rien ici ne vient de la configuration courante ; les empreintes sont abrégées à l'affichage.</p>`
  );
}

export function provenanceHtml(
  launch: TaskLaunch | null,
  snapshot: ExecutionSnapshot | null | undefined,
  usage?: UsageSummary | null,
): string {
  const facts = provenanceFacts(launch, snapshot, usage);
  const status = rawText(snapshot?.capture_status);
  const badge = status === null ? "" : ` ${dsBadge(captureStatusLabel(status), captureStatusTone(status))}`;
  const rows = facts
    .map(
      (fact) =>
        `<div class="ds-list-item" data-testid="provenance-${fact.id}">` +
        `<div class="grow"><div class="ds-list-title">${esc(fact.question)}</div>` +
        `<div class="ds-list-sub">${esc(fact.answer)}</div></div></div>`,
    )
    .join("");
  return `<div data-testid="launch-provenance">${provenanceNotice(snapshot)}${badge}<ul class="ds-list">${rows}</ul></div>`;
}

const REPLAY_VERDICT_LABELS: Record<string, string> = {
  ready: "rejouable",
  limited: "rejouable avec limitations",
  refused: "rejeu refusé",
};

const REPLAY_LIMITATION_LABELS: Record<string, string> = {
  launch_not_terminal: "le lancement n'est pas terminé",
  already_retried: "une nouvelle tentative existe déjà",
  snapshot_missing: "aucun snapshot d'exécution enregistré",
  snapshot_capture_failed: "la capture du snapshot a échoué",
  not_authorized: "droits insuffisants pour relancer",
  target_not_admissible: "poste ou politique non admissible aujourd'hui",
  agent_unresolvable: "l'agent ne se résout plus",
  resolution_unrecorded: "la résolution d'origine n'a pas été enregistrée",
  library_version_unavailable: "une version Library enregistrée n'existe plus",
  source_worktree_dirty: "le worktree source contenait des changements non commités",
  source_git_unrecorded: "l'état Git d'origine n'a pas été enregistré",
  git_state_not_pinned: "la branche de tâche est reprise telle qu'elle est aujourd'hui",
  profile_rechecked_on_machine: "le profil sera revérifié par le poste au démarrage",
  output_not_reproducible: "la sortie d'un agent n'est pas reproductible",
};

const REPLAY_CHANGE_LABELS: Record<string, string> = {
  unchanged: "inchangé",
  changed: "changé",
  added: "ajouté",
  removed: "retiré",
  unavailable: "indisponible",
};

export function replayVerdictTone(verdict: string): DsTone {
  if (verdict === "ready") return "success";
  if (verdict === "limited") return "warning";
  return "danger";
}

function replayLimitationText(item: ReplayLimitation): string {
  const label = REPLAY_LIMITATION_LABELS[item.code] ?? item.code;
  return item.severity === "refusal" ? `Refus : ${label}` : `Limitation : ${label}`;
}

function replayDifferenceText(item: ReplayDifference): string {
  const subject = item.role ? `${item.role} ${item.stable_key}` : item.stable_key;
  const change = REPLAY_CHANGE_LABELS[item.change] ?? item.change;
  return `${subject} — ${change} (${item.recorded ?? "—"} → ${item.current ?? "—"})`;
}

/**
 * Aperçu de rejeu (DEC-0214), lecture seule : ce qu'un retry utiliserait
 * aujourd'hui face au snapshot figé. Rien n'est lancé depuis ce bloc.
 */
export function replayPreviewHtml(replay: TaskLaunchReplayPreview | null | undefined): string {
  if (replay === undefined) return "";
  if (replay === null) {
    return `<p class="ds-list-sub" data-testid="launch-replay">Aperçu de rejeu indisponible.</p>`;
  }
  const verdict = REPLAY_VERDICT_LABELS[replay.verdict] ?? replay.verdict;
  const limits = (replay.limitations ?? [])
    .map((item) => `<li class="ds-list-sub" data-testid="replay-limitation-${esc(item.code)}">${esc(replayLimitationText(item))}</li>`)
    .join("");
  const changes = (replay.differences ?? [])
    .filter((item) => item.change !== "unchanged")
    .map((item) => `<li class="ds-list-sub">${esc(replayDifferenceText(item))}</li>`)
    .join("");
  const diffBlock = changes === ""
    ? `<p class="ds-list-sub">Aucune substitution par rapport au snapshot.</p>`
    : `<p class="ds-list-sub">Substitutions :</p><ul>${changes}</ul>`;
  return `<div data-testid="launch-replay">${dsBadge(verdict, replayVerdictTone(replay.verdict))}` +
    `<ul>${limits}</ul>${diffBlock}</div>`;
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
    `<label class="ds-checkbox"><input type="checkbox" id="launch-production"${state.allowProduction ? " checked" : ""}> Autoriser les commandes et les actions de production pour ce lancement</label>` +
    `<p class="ds-list-sub">Sans autorisation : édition locale uniquement, sans exécution de commandes. Un agent incompatible avec ce mode est refusé.</p>` +
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
    `<p class="ds-list-sub"><strong>Provenance</strong> — neuf questions sur ce qu'a été ce lancement, lues dans son enregistrement figé.</p>` +
    provenanceHtml(state.data.latest, state.data.snapshot, state.data.usage) +
    (state.data.replay === undefined
      ? ""
      : `<p class="ds-list-sub"><strong>Rejeu</strong> — ce qu'une nouvelle tentative utiliserait aujourd'hui, comparé au snapshot.</p>` +
        replayPreviewHtml(state.data.replay)) +
    `</section>`;
}
