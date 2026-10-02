/**
 * UI-5 — Détail d'une tâche : vraie page de travail en français.
 *
 * - Vérité : GET /api/v1/tasks/{id}. Compléments en lecture seule :
 *   GET /sessions?task_id, GET /ai-work?task_id, GET /claims?project_id
 *   (filtré côté client sur task_id). Machines et agents affichés par leur
 *   nom (actorNames), identifiant en infobulle.
 * - Sections verticales lisibles : vue générale, modification (PATCH +
 *   If-Match-Version affiché), prise en charge (claim/release machine —
 *   à ne pas confondre avec les réservations de ressources), sessions,
 *   travail IA, informations techniques repliées.
 * - 409 version_conflict → explication humaine + relecture immédiate, AUCUN
 *   retry automatique : l'utilisateur réapplique consciemment.
 * - Les compléments sont best-effort : leur échec n'efface jamais la tâche
 *   et affiche une mention « indisponible », jamais une erreur bloquante.
 * - Le compteur de réservations liées n'apparaît que lorsque la donnée a
 *   pu être chargée ; sinon il est omis discrètement.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { claimTask, getTask, patchTask, releaseTask, type Task } from "../tasksApi";
import {
  dsBadge,
  dsEmptyState,
  dsField,
  focusDsErrorBox,
  dsNotify,
  dsPageHeader,
  dsSectionHeader,
  dsSkeleton,
} from "../ds/ds";
import { taskClaimHint, taskStatusLabel, taskStatusTone } from "../taskStatus";
import { agentLabel, agentRef, machineLabel, machineRef } from "../actorNames";
import { describeError, esc, fmtTime, shortId } from "../ui";
import { fetchIdentity, type AuthIdentity } from "../identityApi";
import { newIdempotencyKey } from "../claimsApi";
import { listLibraryResources } from "../libraryApi";
import { postResolution } from "../resolutionApi";
import {
  cancelTaskLaunch,
  createTaskLaunch,
  getEligibleMachines,
  getTaskLaunch,
  listTaskLaunches,
  type TaskLaunch,
} from "../taskLaunchesApi";
import {
  canCancelLaunch,
  cancelLaunchConfirmText,
  isTerminalLaunch,
  launchConfirmText,
  launchPanelHtml,
  selectedMachine,
  type AgentOption,
  type LaunchPanelData,
  type LaunchPanelState,
} from "./taskLaunchPanel";

export interface TaskDetailContext {
  client: StudioClient;
  authed: boolean;
  /** Identité de l'appelant (`/auth/me`) ; `null` = inconnue, le serveur tranche. */
  identity?: AuthIdentity | null;
}

export interface SessionRow {
  id: string;
  machine_id: string;
  agent_id?: string | null;
  started_at: string;
  ended_at?: string | null;
}

export interface WorkRow {
  id: string;
  summary: string;
  status: string;
  started_at: string;
  agent_id?: string | null;
  machine_id?: string | null;
  agent_profile?: string | null;
  model?: string | null;
  changed_files?: string[];
  tests_run?: string[];
}

async function fetchJson<T>(
  client: StudioClient,
  path: "/api/v1/sessions" | "/api/v1/ai-work" | "/api/v1/claims",
  query: Record<string, string>,
): Promise<T> {
  const result = await client.GET(path, { params: { query } });
  if (result.response.ok && result.data !== undefined) return result.data as T;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export function taskDetailLoadingHtml(taskId: string): string {
  return `${dsPageHeader("Tâche", `Chargement de ${shortId(taskId)}…`)}${dsSkeleton(4)}`;
}

export function taskDetailErrorHtml(taskId: string, message: string): string {
  return (
    `${dsPageHeader("Tâche", `Identifiant ${shortId(taskId)}`)}` +
    `<div class="ds-notice ds-notice--danger" role="alert"><strong>Tâche indisponible.</strong> ${esc(message)}</div>`
  );
}

/** Explication humaine d'un conflit de version, données déjà rechargées. */
export function taskConflictNotice(version: number): string {
  return `Cette tâche a changé ailleurs (version ${version}). Les dernières données ont été rechargées — vérifiez puis appliquez à nouveau votre modification.`;
}

const AI_WORK_LABEL_FR: Record<string, string> = {
  started: "Commencé",
  completed: "Terminé",
  failed: "Échoué",
  review_requested: "En relecture",
  approved: "Approuvé",
  changes_requested: "Modifications demandées",
};

export function aiWorkStatusLabel(status: string): string {
  return AI_WORK_LABEL_FR[status] ?? status;
}

export function aiWorkStatusTone(status: string): "neutral" | "success" | "warning" | "danger" | "ai" | "info" {
  switch (status) {
    case "completed":
    case "approved":
      return "success";
    case "failed":
      return "danger";
    case "changes_requested":
      return "warning";
    case "review_requested":
      return "ai";
    case "started":
      return "info";
    default:
      return "neutral";
  }
}

export function sessionStateLabel(session: SessionRow): { label: string; tone: "info" | "neutral" } {
  return session.ended_at === null || session.ended_at === undefined || session.ended_at === ""
    ? { label: "En cours", tone: "info" }
    : { label: "Terminée", tone: "neutral" };
}

/** Confirmation de libération : nomme la machine (et l'agent) détenteurs. */
export function releaseTaskConfirmText(task: Task): string {
  const agent = task.claimed_by_agent_id ? ` (agent ${agentLabel(task.claimed_by_agent_id)})` : "";
  return (
    `Libérer la tâche « ${task.title} », prise par la machine ${machineLabel(task.claimed_by_machine_id)}${agent} ? ` +
    `Réservé au détenteur ou à un administrateur ; le statut reste inchangé.`
  );
}

/**
 * Indice UI (le serveur revérifie, DEC-0036) : seule la machine détentrice ou
 * un administrateur peut libérer. Identité inconnue : bouton laissé actif.
 */
export function canReleaseTask(task: Task, authed: boolean, identity: AuthIdentity | null | undefined): boolean {
  const holder = task.claimed_by_machine_id;
  if (!authed || holder === null || holder === undefined || holder === "") return false;
  if (identity === null || identity === undefined || typeof identity.machine_id !== "string") return true;
  return identity.role === "admin" || identity.machine_id === holder;
}

function claimSectionHtml(task: Task, authed: boolean, canRelease: boolean): string {
  const held = task.claimed_by_machine_id !== null && task.claimed_by_machine_id !== undefined && task.claimed_by_machine_id !== "";
  const stateLine = held
    ? `<p>Prise par la machine ${machineRef(task.claimed_by_machine_id)}${task.claimed_by_agent_id ? ` · agent ${agentRef(task.claimed_by_agent_id)}` : ""}.</p>`
    : `<p>Disponible — personne ne travaille dessus actuellement.</p>`;
  return `<section class="task-detail-section" aria-label="Prise en charge">` +
    `${dsSectionHeader("Prise en charge")}${stateLine}` +
    `<p class="ds-list-sub">Prendre signale que votre machine travaille dessus et passe le statut à « En cours ». ` +
    `Libérer garde le statut tel quel : modifiez-le explicitement si besoin.</p>` +
    `<p class="ds-list-sub">À ne pas confondre avec les réservations de ressources (onglet Réservations du projet) : ` +
    `ici, « prendre » désigne qui travaille sur la tâche, pas la réservation d'un fichier.</p>` +
    `<div class="tasks-footer">` +
    `<button class="ds-btn${held ? "" : " ds-btn--primary"}" type="button" data-claim${authed && !held ? "" : " disabled"}>Prendre cette tâche</button>` +
    `<button class="ds-btn" type="button" data-release${canRelease ? "" : " disabled"}>Libérer la tâche</button>` +
    `</div>` +
    (authed && held && !canRelease
      ? `<p class="ds-list-sub">Seule la machine qui a pris la tâche, ou un administrateur, peut la libérer.</p>`
      : "") +
    `</section>`;
}

function sessionsSectionHtml(sessions: SessionRow[] | null): string {
  let body: string;
  if (sessions === null) {
    body = `<div class="ds-notice ds-notice--warning" role="status">Sessions indisponibles pour le moment — la tâche ci-dessus reste fiable.</div>`;
  } else if (sessions.length === 0) {
    body = dsEmptyState("Aucune session", "Aucune session de travail n'est liée à cette tâche.");
  } else {
    body =
      `<ul class="ds-list">` +
      sessions
        .map((session) => {
          const state = sessionStateLabel(session);
          const agent = session.agent_id === null || session.agent_id === undefined || session.agent_id === "" ? "Agent non renseigné" : `Agent ${agentRef(session.agent_id)}`;
          return `<li class="ds-list-item"><div class="grow">` +
            `<div class="ds-list-title">${agent}</div>` +
            `<div class="ds-list-sub">Début ${esc(fmtTime(session.started_at))} · ${session.ended_at ? `Fin ${esc(fmtTime(session.ended_at))}` : "toujours active"} · machine ${machineRef(session.machine_id)}</div>` +
            `</div>${dsBadge(state.label, state.tone)}</li>`;
        })
        .join("") +
      `</ul>`;
  }
  return `<section class="task-detail-section" id="task-sessions" aria-label="Sessions">${dsSectionHeader(`Sessions (${sessions === null ? "?" : sessions.length})`)}${body}</section>`;
}

function aiWorkSectionHtml(worklogs: WorkRow[] | null): string {
  let body: string;
  if (worklogs === null) {
    body = `<div class="ds-notice ds-notice--warning" role="status">Travail IA indisponible pour le moment — la tâche ci-dessus reste fiable.</div>`;
  } else if (worklogs.length === 0) {
    body = dsEmptyState("Aucun travail IA", "Aucun travail IA n'est enregistré pour cette tâche.");
  } else {
    body =
      `<ul class="ds-list">` +
      worklogs
        .map((work) => {
          const context: string[] = [];
          if (work.agent_profile !== null && work.agent_profile !== undefined && work.agent_profile !== "") {
            context.push(`Profil ${work.agent_profile}`);
          } else if (work.agent_id !== null && work.agent_id !== undefined && work.agent_id !== "") {
            context.push(`Agent ${agentLabel(work.agent_id)}`);
          }
          if (work.model !== null && work.model !== undefined && work.model !== "") context.push(work.model);
          const files = work.changed_files?.length ?? 0;
          const tests = work.tests_run?.length ?? 0;
          if (files > 0) context.push(`${files} fichier(s)`);
          if (tests > 0) context.push(`${tests} test(s)`);
          const summary = work.summary.length > 140 ? `${work.summary.slice(0, 140)}…` : work.summary;
          return `<li class="ds-list-item"><div class="grow">` +
            `<div class="ds-list-title">${esc(summary)}</div>` +
            `<div class="ds-list-sub">${context.length === 0 ? `Démarré ${esc(fmtTime(work.started_at))}` : `${context.map((part) => esc(part)).join(" · ")} · ${esc(fmtTime(work.started_at))}`}</div>` +
            `</div>${dsBadge(aiWorkStatusLabel(work.status), aiWorkStatusTone(work.status))}</li>`;
        })
        .join("") +
      `</ul>`;
  }
  return `<section class="task-detail-section" id="task-ai-work" aria-label="Travail IA">${dsSectionHeader(`Travail IA (${worklogs === null ? "?" : worklogs.length})`)}${body}</section>`;
}

function techDetailsHtml(task: Task): string {
  return `<details class="task-tech"><summary>Informations techniques</summary><dl>` +
    `<div><dt>Identifiant</dt><dd><code class="mono">${esc(task.id)}</code></dd></div>` +
    (task.readable_id ? `<div><dt>Référence lisible</dt><dd><code class="mono">${esc(task.readable_id)}</code></dd></div>` : "") +
    `<div><dt>Projet</dt><dd><code class="mono">${esc(task.project_id)}</code></dd></div>` +
    `<div><dt>Version</dt><dd>${task.version}</dd></div>` +
    `<div><dt>Statut interne</dt><dd><code class="mono">${esc(task.status)}</code></dd></div>` +
    `<div><dt>Machine en charge</dt><dd>${task.claimed_by_machine_id ? machineRef(task.claimed_by_machine_id) : "—"}</dd></div>` +
    `<div><dt>Créée le</dt><dd>${esc(fmtTime(task.created_at))}</dd></div>` +
    `<div><dt>Mise à jour le</dt><dd>${esc(fmtTime(task.updated_at))}</dd></div>` +
    `</dl></details>`;
}

export interface TaskDetailData {
  task: Task;
  sessions: SessionRow[] | null;
  worklogs: WorkRow[] | null;
  /** null = chargement best-effort échoué : la mention est omise, sans erreur. */
  taskClaims: number | null;
  notice: string;
  noticeTone?: "danger" | "info";
  authed: boolean;
  /** Absent = détenue et connecté (comportement historique). */
  canRelease?: boolean;
  /** null/absent = données de lancement non chargées (best-effort). */
  launch?: LaunchPanelData | null;
}

export function taskEditFormHtml(task: Task, authed: boolean): string {
  const statusOptions = (["created", "in_progress", "blocked", "completed"] as const)
    .map(
      (status) =>
        `<option value="${status}"${task.status === status ? " selected" : ""}>${esc(taskStatusLabel(status))}</option>`,
    )
    .join("");
  return `<form id="task-edit-form" novalidate>` +
    dsField("task-edit-title", "Titre", `<input class="ds-input" id="FIELD" name="title" required autocomplete="off" value="${esc(task.title)}"${authed ? "" : " disabled"} />`) +
    dsField(
      "task-edit-desc",
      "Description (facultative)",
      `<textarea class="ds-textarea" id="FIELD" name="description" rows="4"${authed ? "" : " disabled"}>${esc(task.description ?? "")}</textarea>`,
    ) +
    dsField("task-edit-status", "Statut", `<select class="ds-select" id="FIELD" name="status"${authed ? "" : " disabled"}>${statusOptions}</select>`) +
    `<p class="ds-list-sub">Modification protégée par la version ${task.version} : si la tâche change ailleurs, vos changements ne sont pas écrasés — rechargez puis réappliquez.</p>` +
    `<div class="ds-field-error" id="task-edit-error" role="alert" hidden></div>` +
    `<div class="ds-dialog-actions"><button class="ds-btn ds-btn--primary" type="submit" id="task-edit-submit"${authed ? "" : " disabled"}>Enregistrer</button></div>` +
    (authed ? "" : `<p class="ds-list-sub">Lecture seule : connectez-vous pour modifier cette tâche.</p>`) +
    `</form>`;
}

export function launchSectionHtml(data: TaskDetailData): string {
  const state: LaunchPanelState = {
    data: data.launch ?? null,
    authed: data.authed,
    canCancel: false,
    selectedMachineId: "",
    selectedHarnessId: "",
    agentStableKey: "",
    preview: null,
    previewLoading: false,
    previewError: "",
    latestLoading: false,
    notice: "",
    error: "",
  };
  return `<div id="task-launch-panel">${launchPanelHtml(state)}</div>`;
}

export function taskDetailHtml(data: TaskDetailData): string {
  const { task } = data;
  const held = task.claimed_by_machine_id !== null && task.claimed_by_machine_id !== undefined && task.claimed_by_machine_id !== "";
  const canRelease = data.canRelease ?? (data.authed && held);
  const subtitle = `${task.readable_id ? `${task.readable_id} · ` : ""}${taskStatusLabel(task.status)} · ${taskClaimHint(task)}`;
  const header = dsPageHeader(task.title, subtitle, [
    ...(data.authed
      ? held
        ? canRelease
          ? [{ label: "Libérer", id: "task-head-release", variant: "secondary" as const }]
          : []
        : [{ label: "Prendre", id: "task-head-take", variant: "primary" as const }]
      : []),
    { label: "Modifier", id: "task-head-edit", variant: "ghost" as const },
  ]);
  const notice =
    data.notice === ""
      ? ""
      : `<div class="ds-notice ds-notice--${data.noticeTone ?? "danger"}" role="alert">${esc(data.notice)}</div>`;
  const description = (task.description ?? "").trim();
  const overview =
    `<section class="task-detail-section" aria-label="Vue générale">` +
    `${dsSectionHeader("Vue générale")}` +
    `<div class="task-overview">${dsBadge(taskStatusLabel(task.status), taskStatusTone(task.status))}` +
    `<p><a href="#/projects/${esc(task.project_id)}">Ouvrir le projet</a></p></div>` +
    (description === "" ? `<p class="ds-list-sub">Sans description.</p>` : `<p class="task-description">${esc(description)}</p>`) +
    `</section>`;
  const edit =
    `<section class="task-detail-section" aria-label="Modifier la tâche" id="task-edit-section">` +
    `${dsSectionHeader("Modifier la tâche")}${taskEditFormHtml(task, data.authed)}</section>`;
  const claimsLine =
    data.taskClaims === null
      ? ""
      : `<p class="ds-list-sub">Réservations de ressources liées : ${data.taskClaims} — <a href="#/projects/${esc(task.project_id)}/claims">voir l'onglet Réservations du projet</a>.</p>`;
  return `<div class="tasks task-detail">${header}${notice}${overview}${edit}${claimSectionHtml(task, data.authed, canRelease)}` +
    `${launchSectionHtml(data)}` +
    `<div data-msg class="ds-list-sub" role="status" aria-live="polite"></div>` +
    `${sessionsSectionHtml(data.sessions)}${aiWorkSectionHtml(data.worklogs)}${claimsLine}${techDetailsHtml(task)}</div>`;
}

export async function renderTaskDetail(root: HTMLElement, baseCtx: TaskDetailContext, taskId: string): Promise<void> {
  root.innerHTML = taskDetailLoadingHtml(taskId);
  const ctx: TaskDetailContext = {
    ...baseCtx,
    identity: baseCtx.identity ?? (baseCtx.authed ? await fetchIdentity(baseCtx.client) : null),
  };
  let task: Task;
  try {
    task = await getTask(ctx.client, taskId);
  } catch (error) {
    root.innerHTML = taskDetailErrorHtml(taskId, describeError(error));
    return;
  }

  // Compléments best-effort : la tâche est la vérité, leur échec n'efface rien.
  let sessions: SessionRow[] | null = null;
  let worklogs: WorkRow[] | null = null;
  let taskClaims: number | null = null;
  try {
    const [fetchedSessions, fetchedWork, fetchedClaims] = await Promise.all([
      fetchJson<SessionRow[]>(ctx.client, "/api/v1/sessions", { task_id: task.id }),
      fetchJson<WorkRow[]>(ctx.client, "/api/v1/ai-work", { task_id: task.id }),
      fetchJson<{ id: string; task_id?: string | null }[]>(ctx.client, "/api/v1/claims", { project_id: task.project_id }),
    ]);
    sessions = fetchedSessions;
    worklogs = fetchedWork;
    taskClaims = fetchedClaims.filter((claim) => claim.task_id === task.id).length;
  } catch {
    // Best-effort : sections « indisponible », compteur omis, page intacte.
  }

  const launch = ctx.authed ? await loadLaunchData(ctx.client, task, sessions) : null;
  paint(root, ctx, { task, sessions, worklogs, taskClaims, notice: "", authed: ctx.authed, launch });
}

function paint(root: HTMLElement, ctx: TaskDetailContext, data: TaskDetailData): void {
  root.innerHTML = taskDetailHtml({ ...data, canRelease: canReleaseTask(data.task, data.authed, ctx.identity) });
  bind(root, ctx, data);
}

function setMsg(root: HTMLElement, human: string, technical = ""): void {
  const node = root.querySelector("[data-msg]");
  if (node === null) return;
  node.innerHTML =
    human === ""
      ? ""
      : `${esc(human)}${technical === "" ? "" : ` <span class="tasks-msg-tech">${esc(technical)}</span>`}`;
}

function setEditError(root: HTMLElement, message: string): void {
  const node = root.querySelector("#task-edit-error");
  if (node === null) return;
  if (message === "") {
    node.setAttribute("hidden", "");
    node.textContent = "";
  } else {
    node.removeAttribute("hidden");
    node.textContent = message;
    if (node instanceof HTMLElement) focusDsErrorBox(node);
  }
}

function bind(root: HTMLElement, ctx: TaskDetailContext, data: TaskDetailData): void {
  const { task } = data;
  root.querySelector<HTMLElement>("#task-head-edit")?.addEventListener("click", () => {
    const section = root.querySelector<HTMLElement>("#task-edit-section");
    section?.scrollIntoView({ block: "start" });
    root.querySelector<HTMLElement>("#task-edit-title")?.focus();
  });
  root.querySelector<HTMLElement>("#task-head-take")?.addEventListener("click", () => {
    void doClaim(root, ctx, task.id);
  });
  root.querySelector<HTMLElement>("#task-head-release")?.addEventListener("click", () => {
    void doRelease(root, ctx, task);
  });

  const form = root.querySelector<HTMLFormElement>("#task-edit-form");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const title = String(formData.get("title") ?? "").trim();
    if (title === "") {
      setEditError(root, "Le titre est obligatoire.");
      root.querySelector<HTMLElement>("#task-edit-title")?.focus();
      return;
    }
    const submit = root.querySelector<HTMLButtonElement>("#task-edit-submit");
    if (submit !== null) {
      submit.disabled = true;
      submit.textContent = "Enregistrement en cours…";
    }
    setEditError(root, "");
    const description = String(formData.get("description") ?? "").trim();
    patchTask(
      ctx.client,
      task.id,
      {
        title,
        description: description === "" ? null : description,
        status: String(formData.get("status") ?? task.status) as Task["status"],
      },
      task.version,
    )
      .then(() => {
        dsNotify("Tâche enregistrée.", "success");
        void importSessionsWork(root, ctx, task.id);
      })
      .catch((error: unknown) => {
        if (submit !== null) {
          submit.disabled = false;
          submit.textContent = "Enregistrer";
        }
        if (error instanceof ApiError && error.errorCode === "version_conflict") {
          // Pas de retry automatique : on relit la vérité serveur,
          // l'utilisateur réapplique consciemment sa modification.
          getTask(ctx.client, task.id).then(
            (fresh) => {
              const notice = taskConflictNotice(fresh.version);
              paint(root, ctx, { task: fresh, sessions: null, worklogs: null, taskClaims: null, notice, authed: ctx.authed });
              void importSessionsWork(root, ctx, fresh.id, notice);
            },
            (reloadError: unknown) =>
              setMsg(
                root,
                "Cette tâche a changé ailleurs, et le rechargement a échoué.",
                describeError(reloadError),
              ),
          );
        } else {
          setEditError(root, describeError(error));
        }
      });
  });

  root.querySelector("[data-claim]")?.addEventListener("click", () => {
    void doClaim(root, ctx, task.id);
  });
  root.querySelector("[data-release]")?.addEventListener("click", () => {
    void doRelease(root, ctx, task);
  });

  bindLaunchPanel(root, ctx, task, data.launch ?? null);
}

const LAUNCH_POLL_INTERVAL_MS = 5000;

function bindLaunchPanel(
  root: HTMLElement,
  ctx: TaskDetailContext,
  task: Task,
  initial: LaunchPanelData | null,
): void {
  const found = root.querySelector<HTMLElement>("#task-launch-panel");
  if (found === null || !ctx.authed) return;
  const container: HTMLElement = found;
  const state: LaunchPanelState = {
    data: initial,
    authed: true,
    canCancel: initial !== null && initial.latest !== null ? canCancelLaunch(initial.latest, ctx.identity) : false,
    selectedMachineId: "",
    selectedHarnessId: "",
    agentStableKey: "",
    preview: null,
    previewLoading: false,
    previewError: "",
    latestLoading: false,
    notice: "",
    error: "",
  };
  let pollTimer: number | null = null;

  /** Adopte une lecture serveur comme seule vérité affichée. */
  function applyLatest(launch: TaskLaunch): void {
    if (state.data === null) return;
    state.data = { ...state.data, latest: launch };
    state.canCancel = canCancelLaunch(launch, ctx.identity);
  }

  function bindPanel(): void {
    container.querySelector<HTMLSelectElement>("#launch-machine")?.addEventListener("change", (event) => {
      state.selectedMachineId = (event.target as HTMLSelectElement).value;
      state.selectedHarnessId = "";
      state.preview = null;
      state.previewError = "";
      state.error = "";
      render();
    });
    container.querySelector<HTMLSelectElement>("#launch-harness")?.addEventListener("change", (event) => {
      state.selectedHarnessId = (event.target as HTMLSelectElement).value;
      render();
    });
    container.querySelector<HTMLSelectElement>("#launch-agent")?.addEventListener("change", (event) => {
      state.agentStableKey = (event.target as HTMLSelectElement).value;
      state.preview = null;
      state.previewError = "";
      render();
    });
    container.querySelector("[data-action=launch-preview]")?.addEventListener("click", () => void doPreview());
    container.querySelector("[data-action=launch-submit]")?.addEventListener("click", () => void doLaunch());
    container.querySelector("[data-action=launch-refresh]")?.addEventListener("click", () => void doRefresh(false));
    container.querySelector("[data-action=launch-cancel]")?.addEventListener("click", () => void doCancel());
  }

  function render(): void {
    container.innerHTML = launchPanelHtml(state);
    bindPanel();
    schedulePoll();
  }

  /** Suivi borné : relit l'état tant que le lancement n'est pas terminal. */
  function schedulePoll(): void {
    if (pollTimer !== null) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
    const latest = state.data?.latest ?? null;
    if (latest === null || isTerminalLaunch(latest.status) || !container.isConnected) return;
    pollTimer = window.setTimeout(() => {
      pollTimer = null;
      void doRefresh(true);
    }, LAUNCH_POLL_INTERVAL_MS);
  }

  async function doPreview(): Promise<void> {
    if (state.agentStableKey === "") return;
    state.previewLoading = true;
    state.previewError = "";
    render();
    try {
      state.preview = await postResolution(ctx.client, {
        stable_key: state.agentStableKey,
        project_id: task.project_id,
        session_overrides: [],
      });
    } catch (error) {
      state.preview = null;
      state.previewError = describeError(error);
    } finally {
      state.previewLoading = false;
      render();
    }
  }

  async function doRefresh(silent: boolean): Promise<void> {
    const latest = state.data?.latest ?? null;
    if (latest === null) return;
    if (silent && !container.isConnected) return;
    if (!silent) {
      state.latestLoading = true;
      state.error = "";
      render();
    }
    try {
      const [fresh, sessions] = await Promise.all([
        getTaskLaunch(ctx.client, latest.id),
        fetchJson<SessionRow[]>(ctx.client, "/api/v1/sessions", { task_id: task.id }).catch(() => null),
      ]);
      applyLatest(fresh);
      if (sessions !== null && state.data !== null) state.data = { ...state.data, sessions };
      if (!silent) state.notice = "";
    } catch (error) {
      if (!silent) state.error = describeError(error);
    } finally {
      if (!silent) state.latestLoading = false;
      render();
    }
  }

  /** Relit un lancement précis après un conflit : aucune réapplication aveugle. */
  async function reloadLatest(note: string): Promise<void> {
    const latest = state.data?.latest ?? null;
    if (latest === null) return;
    try {
      const fresh = await getTaskLaunch(ctx.client, latest.id);
      applyLatest(fresh);
      state.notice = note;
    } catch (error) {
      state.error = describeError(error);
    }
  }

  async function doCancel(): Promise<void> {
    const latest = state.data?.latest ?? null;
    if (latest === null || !state.canCancel) return;
    if (!window.confirm(cancelLaunchConfirmText(latest))) return;
    state.error = "";
    state.notice = "";
    const button = container.querySelector<HTMLButtonElement>("[data-action=launch-cancel]");
    if (button !== null) button.disabled = true;
    try {
      const cancelled = await cancelTaskLaunch(ctx.client, latest.id, latest.version);
      applyLatest(cancelled);
      state.notice = "Lancement annulé : le poste cible n'exécutera pas (ou plus) cette demande.";
      dsNotify("Lancement annulé.", "success");
    } catch (error) {
      if (error instanceof ApiError && error.errorCode === "version_conflict") {
        await reloadLatest("Ce lancement a changé ailleurs : état rechargé — vérifiez avant d'annuler à nouveau.");
      } else if (error instanceof ApiError && error.errorCode === "invalid_launch_transition") {
        await reloadLatest("Ce lancement est déjà terminé : état rechargé.");
      } else if (error instanceof ApiError && error.errorCode === "forbidden") {
        state.error = "Seul le demandeur de ce lancement (ou un administrateur) peut l'annuler.";
      } else {
        state.error = describeError(error);
      }
    } finally {
      render();
    }
  }

  async function doLaunch(): Promise<void> {
    const machine = selectedMachine(state);
    if (machine === null || !machine.eligible || state.selectedHarnessId === "") return;
    if (!window.confirm(launchConfirmText(machine, state.selectedHarnessId, state.agentStableKey))) return;
    state.error = "";
    state.notice = "";
    const submit = container.querySelector<HTMLButtonElement>("[data-action=launch-submit]");
    if (submit !== null) submit.disabled = true;
    try {
      const created = await createTaskLaunch(
        ctx.client,
        task.project_id,
        {
          task_id: task.id,
          machine_id: machine.machine_id,
          harness_id: state.selectedHarnessId,
          ...(state.agentStableKey === "" ? {} : { agent_stable_key: state.agentStableKey }),
          expires_in_seconds: 900,
        },
        newIdempotencyKey(),
      );
      applyLatest(created);
      state.notice = "Lancement demandé : en attente de la machine cible, qui seule rapporte l'exécution.";
      dsNotify("Lancement demandé.", "success");
      render();
    } catch (error) {
      state.error = describeError(error);
      render();
    }
  }

  render();
}

async function doClaim(root: HTMLElement, ctx: TaskDetailContext, taskId: string): Promise<void> {
  for (const button of root.querySelectorAll<HTMLButtonElement>("[data-claim], #task-head-take")) {
    button.disabled = true;
  }
  try {
    await claimTask(ctx.client, taskId);
    dsNotify("Tâche prise — statut passé à « En cours ».", "success");
    await importSessionsWork(root, ctx, taskId);
  } catch (error) {
    for (const button of root.querySelectorAll<HTMLButtonElement>("[data-claim], #task-head-take")) {
      button.disabled = false;
    }
    if (error instanceof ApiError && error.errorCode === "already_claimed") {
      setMsg(root, "Cette tâche est déjà prise par une autre machine.", describeError(error));
    } else {
      setMsg(root, "Prise en charge impossible.", describeError(error));
    }
  }
}

async function doRelease(root: HTMLElement, ctx: TaskDetailContext, task: Task): Promise<void> {
  if (!window.confirm(releaseTaskConfirmText(task))) return;
  const taskId = task.id;
  for (const button of root.querySelectorAll<HTMLButtonElement>("[data-release], #task-head-release")) {
    button.disabled = true;
  }
  try {
    await releaseTask(ctx.client, taskId, task.version);
    const data = await readComplements(root, ctx, taskId);
    paint(root, ctx, {
      ...data,
      notice: "Tâche libérée. Le statut reste inchangé (règle du serveur) — modifiez-le explicitement si besoin.",
      noticeTone: "info",
      authed: ctx.authed,
    });
  } catch (error) {
    for (const button of root.querySelectorAll<HTMLButtonElement>("[data-release], #task-head-release")) {
      button.disabled = false;
    }
    if (error instanceof ApiError && error.errorCode === "version_conflict") {
      // La tâche a changé depuis la lecture (reprise, autre libération…) :
      // on relit et on laisse l'utilisateur redécider, jamais de retry aveugle.
      try {
        const data = await readComplements(root, ctx, taskId);
        paint(root, ctx, {
          ...data,
          notice: `Cette tâche a changé ailleurs (version ${data.task.version}) : rien n'a été libéré. Vérifiez son état puis relancez la libération si besoin.`,
          authed: ctx.authed,
        });
      } catch {
        // readComplements a déjà signalé l'échec du rechargement.
      }
      return;
    }
    setMsg(root, "Libération impossible.", describeError(error));
  }
}

async function loadLaunchData(
  client: StudioClient,
  task: Task,
  sessions: SessionRow[] | null,
): Promise<LaunchPanelData | null> {
  const [machines, agents, launches] = await Promise.allSettled([
    getEligibleMachines(client, task.id),
    listLibraryResources(client, { kind: "agent_definition", limit: 100 }),
    listTaskLaunches(client, task.project_id),
  ]);
  const machineList =
    machines.status === "fulfilled" && Array.isArray(machines.value.machines) ? machines.value.machines : null;
  if (machineList === null) return null;
  const agentOptions: AgentOption[] =
    agents.status === "fulfilled" && Array.isArray(agents.value)
      ? agents.value
          .filter((resource) => typeof resource.stable_key === "string")
          .map((resource) => ({ stable_key: resource.stable_key }))
      : [];
  const rawLaunches = launches.status === "fulfilled" && Array.isArray(launches.value) ? launches.value : [];
  const forTask = rawLaunches.filter((launch) => launch.task_id === task.id);
  return {
    machines: machineList,
    agents: agentOptions,
    latest: forTask.length === 0 ? null : (forTask[forTask.length - 1] ?? null),
    sessions,
  };
}

async function readComplements(
  root: HTMLElement,
  ctx: TaskDetailContext,
  taskId: string,
): Promise<Omit<TaskDetailData, "notice" | "authed">> {
  let fresh: Task;
  try {
    fresh = await getTask(ctx.client, taskId);
  } catch (error) {
    setMsg(root, "Rechargement impossible.", describeError(error));
    throw error;
  }
  let sessions: SessionRow[] | null = null;
  let worklogs: WorkRow[] | null = null;
  let taskClaims: number | null = null;
  try {
    const [fetchedSessions, fetchedWork, fetchedClaims] = await Promise.all([
      fetchJson<SessionRow[]>(ctx.client, "/api/v1/sessions", { task_id: fresh.id }),
      fetchJson<WorkRow[]>(ctx.client, "/api/v1/ai-work", { task_id: fresh.id }),
      fetchJson<{ id: string; task_id?: string | null }[]>(ctx.client, "/api/v1/claims", { project_id: fresh.project_id }),
    ]);
    sessions = fetchedSessions;
    worklogs = fetchedWork;
    taskClaims = fetchedClaims.filter((claim) => claim.task_id === fresh.id).length;
  } catch {
    // Best-effort : sections « indisponible », compteur omis, page intacte.
  }
  const launch = ctx.authed ? await loadLaunchData(ctx.client, fresh, sessions) : null;
  return { task: fresh, sessions, worklogs, taskClaims, launch };
}

async function importSessionsWork(
  root: HTMLElement,
  ctx: TaskDetailContext,
  taskId: string,
  notice = "",
): Promise<void> {
  try {
    const data = await readComplements(root, ctx, taskId);
    paint(root, ctx, { ...data, notice, authed: ctx.authed });
  } catch {
    // readComplements a déjà signalé l'échec ; la page reste telle quelle.
  }
}
