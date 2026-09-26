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
import { agentLabel, agentRef, machineRef } from "../actorNames";
import { describeError, esc, fmtTime, shortId } from "../ui";

export interface TaskDetailContext {
  client: StudioClient;
  authed: boolean;
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

function claimSectionHtml(task: Task, authed: boolean): string {
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
    `<button class="ds-btn" type="button" data-release${authed && held ? "" : " disabled"}>Libérer la tâche</button>` +
    `</div></section>`;
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
  return `<section class="task-detail-section" aria-label="Sessions">${dsSectionHeader(`Sessions (${sessions === null ? "?" : sessions.length})`)}${body}</section>`;
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
  return `<section class="task-detail-section" aria-label="Travail IA">${dsSectionHeader(`Travail IA (${worklogs === null ? "?" : worklogs.length})`)}${body}</section>`;
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

export function taskDetailHtml(data: TaskDetailData): string {
  const { task } = data;
  const held = task.claimed_by_machine_id !== null && task.claimed_by_machine_id !== undefined && task.claimed_by_machine_id !== "";
  const subtitle = `${task.readable_id ? `${task.readable_id} · ` : ""}${taskStatusLabel(task.status)} · ${taskClaimHint(task)}`;
  const header = dsPageHeader(task.title, subtitle, [
    ...(data.authed
      ? held
        ? [{ label: "Libérer", id: "task-head-release", variant: "secondary" as const }]
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
  return `<div class="tasks task-detail">${header}${notice}${overview}${edit}${claimSectionHtml(task, data.authed)}` +
    `<div data-msg class="ds-list-sub" role="status" aria-live="polite"></div>` +
    `${sessionsSectionHtml(data.sessions)}${aiWorkSectionHtml(data.worklogs)}${claimsLine}${techDetailsHtml(task)}</div>`;
}

export async function renderTaskDetail(root: HTMLElement, ctx: TaskDetailContext, taskId: string): Promise<void> {
  root.innerHTML = taskDetailLoadingHtml(taskId);
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

  paint(root, ctx, { task, sessions, worklogs, taskClaims, notice: "", authed: ctx.authed });
}

function paint(root: HTMLElement, ctx: TaskDetailContext, data: TaskDetailData): void {
  root.innerHTML = taskDetailHtml(data);
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
    void doRelease(root, ctx, task.id);
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
    void doRelease(root, ctx, task.id);
  });
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

async function doRelease(root: HTMLElement, ctx: TaskDetailContext, taskId: string): Promise<void> {
  for (const button of root.querySelectorAll<HTMLButtonElement>("[data-release], #task-head-release")) {
    button.disabled = true;
  }
  try {
    await releaseTask(ctx.client, taskId);
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
    setMsg(root, "Libération impossible.", describeError(error));
  }
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
  try {
    const [sessions, worklogs, claims] = await Promise.all([
      fetchJson<SessionRow[]>(ctx.client, "/api/v1/sessions", { task_id: fresh.id }),
      fetchJson<WorkRow[]>(ctx.client, "/api/v1/ai-work", { task_id: fresh.id }),
      fetchJson<{ id: string; task_id?: string | null }[]>(ctx.client, "/api/v1/claims", { project_id: fresh.project_id }),
    ]);
    return { task: fresh, sessions, worklogs, taskClaims: claims.filter((claim) => claim.task_id === fresh.id).length };
  } catch {
    return { task: fresh, sessions: null, worklogs: null, taskClaims: null };
  }
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
