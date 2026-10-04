/**
 * UI-6 + P05-agents — Agents IA : liste compacte, fiche lisible.
 *
 * Page calme (ni table de processus, ni monitoring) : qui sont les agents,
 * que font-ils, sur quoi travaillent-ils, avec quel environnement.
 * Distinctions imposées (jamais fusionnées) : Agent (identité/provenance)
 * ≠ Machine (exécution) ≠ Model (modèle IA) ≠ Runtime (provider/harness)
 * ≠ Binding (association stockée). Seules les relations backend réelles
 * sont affichées (voir agentsApi) : aucune définition associée simulée,
 * aucun mapping runtime/model inventé, aucune présence canonique.
 *
 * P05-agents (docs/ux/desktop-dashboard-v2/wireframes/agents.html) :
 * la liste montre rôle, disponibilité et projet — nom + rôle + projet par
 * ligne, groupées par disponibilité, statut porté par un point de couleur.
 * Modèle, permissions et identifiants dorment dans « Détails techniques »
 * (repliés) ; les actions d'administration vivent dans une section séparée,
 * hors du flux quotidien. Aucune fonction experte perdue : tout ce que les
 * cartes affichaient reste accessible en fiche.
 *
 * Activité toujours DERIVED : « Actif récemment » / « Dernière activité »
 * signifient « activité observée via sessions, AI work, tâches, events » —
 * jamais « en ligne ». Une source secondaire en échec dégrade en
 * « Activité inconnue », sans faire tomber la liste canonique.
 */
import type { StudioClient } from "../api";
import {
  aiWorkStatusLabel,
  aiWorkStatusTone,
  deriveAgentActivity,
  fetchAgentEvents,
  fetchAgentProjects,
  fetchAgentSessions,
  fetchAgents,
  fetchAgentTasks,
  fetchAgentWork,
  filterAgents,
  type Agent,
  type AgentActivity,
  type AgentEvent,
  type AgentProject,
  type AgentSignal,
  type AgentTask,
  type AIWorkLog,
  type WorkSession,
} from "../agentsApi";
import {
  dsBadge,
  dsEmptyState,
  dsPageHeader,
  dsSkeleton,
  dsStatus,
  dsStatusDot,
  dsTechDetails,
} from "../ds/ds";
import { machineName, machineRef } from "../actorNames";
import { describeError, esc, fmtTime } from "../ui";
import { FALLBACK_LABEL } from "../language";
// Styles colocalisés : la page reste autonome sans toucher au CSS global.
import "./agents.css";

export interface AgentsContext {
  client: StudioClient;
  authed: boolean;
}

export interface AgentNames {
  tasksById: Map<string, AgentTask>;
  projectsById: Map<string, AgentProject>;
}

export function buildAgentNames(tasks: AgentTask[], projects: AgentProject[]): AgentNames {
  return {
    tasksById: new Map(tasks.map((task) => [task.id, task])),
    projectsById: new Map(projects.map((project) => [project.id, project])),
  };
}

export function projectName(names: AgentNames, projectId: string | null | undefined): string | null {
  if (projectId === null || projectId === undefined) return null;
  return names.projectsById.get(projectId)?.name ?? null;
}

/* ------------------------------------------------------------------ */
/* Activité DERIVED : pastille + libellé explicite, jamais « En ligne ». */
/* ------------------------------------------------------------------ */

export function agentSignalHtml(activity: AgentActivity): string {
  switch (activity.signal) {
    case "open-session":
      return `${dsStatus("info", "Session de travail ouverte")}<p class="ds-list-sub">Signal d'activité — pas une preuve de connexion.</p>`;
    case "recent":
      return `${dsStatus("info", "Actif récemment")}<p class="ds-list-sub">Activité observée · dernière activité le ${fmtTime(activity.lastActivityAt)} — pas une présence garantie.</p>`;
    case "past":
      return `${dsStatus("idle", `Dernière activité le ${fmtTime(activity.lastActivityAt)}`)}<p class="ds-list-sub">Activité observée, potentiellement ancienne.</p>`;
    case "unknown":
      return `${dsStatus("idle", "Activité inconnue")}<p class="ds-list-sub">Sources secondaires indisponibles — aucune activité affirmée.</p>`;
    case "none":
    default:
      return `${dsStatus("idle", "Aucune activité observée")}<p class="ds-list-sub">Ni session, ni travail, ni événement attribué à cet agent.</p>`;
  }
}

/* ------------------------------------------------------------------ */
/* Résumé du travail : uniquement les relations réelles.                */
/* ------------------------------------------------------------------ */

function taskLinkHtml(task: AgentTask | undefined, fallbackId: string): string {
  if (task === undefined) return `<span class="actor-name actor-name--unknown">${esc(FALLBACK_LABEL.task)}</span>`;
  return `<a href="#/tasks/${esc(task.id)}">« ${esc(task.title)} »</a>`;
}

function projectSuffixHtml(names: AgentNames, projectId: string | null | undefined): string {
  if (projectId === null || projectId === undefined) return "";
  const name = projectName(names, projectId);
  if (name === null) return "";
  return ` — <a href="#/projects/${esc(projectId)}">${esc(name)}</a>`;
}

/* ------------------------------------------------------------------ */
/* Identité humaine : nom et rôle, jamais d'identifiant (C2).          */
/* ------------------------------------------------------------------ */

/** Nom humain, repli générique — jamais un UUID ni un préfixe d'UUID. */
export function agentDisplayName(agent: Agent): string {
  const name = agent.display_name.trim();
  return name === "" ? FALLBACK_LABEL.agent : name;
}

/** Rôle déclaré (nature) : null quand non renseigné. */
export function agentRoleLabel(agent: Agent): string | null {
  const kind = agent.agent_kind.trim();
  return kind === "" ? null : kind;
}

/* ------------------------------------------------------------------ */
/* Projet prioritaire : session ouverte > dernier AI work > tâche prise.*/
/* Même ordre honnête que le résumé, réduit au seul projet pour la     */
/* ligne compacte (le détail complet vit dans le héros de la fiche).   */
/* ------------------------------------------------------------------ */

export interface AgentPrimaryProject {
  id: string;
  name: string;
}

export function agentPrimaryProject(
  agent: Agent,
  activity: AgentActivity,
  aiWork: AIWorkLog[],
  tasks: AgentTask[],
  names: AgentNames,
): AgentPrimaryProject | null {
  if (activity.openSession !== null) {
    const task = names.tasksById.get(activity.openSession.task_id);
    const projectId = task?.project_id;
    if (projectId !== null && projectId !== undefined) {
      const name = projectName(names, projectId);
      if (name !== null) return { id: projectId, name };
    }
  }
  const ownWork = aiWork
    .filter((work) => work.agent_id === agent.id)
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
  const latest = ownWork[0];
  if (latest !== undefined) {
    const task = latest.task_id !== null && latest.task_id !== undefined
      ? names.tasksById.get(latest.task_id)
      : undefined;
    const projectId = task?.project_id ?? latest.project_id;
    if (projectId !== null && projectId !== undefined) {
      const name = projectName(names, projectId);
      if (name !== null) return { id: projectId, name };
    }
  }
  const claimed = tasks
    .filter((task) => task.claimed_by_agent_id === agent.id)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0];
  if (claimed !== undefined && claimed.project_id !== null && claimed.project_id !== undefined) {
    const name = projectName(names, claimed.project_id);
    if (name !== null) return { id: claimed.project_id, name };
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Ligne compacte : nom + rôle + projet, point de couleur pour la      */
/* disponibilité (le groupe porte le libellé, la pastille est le seul  */
/* rappel visuel par ligne). Technique et IDs : en fiche uniquement.   */
/* ------------------------------------------------------------------ */

export type AgentAvailabilityGroup = "active" | "recent" | "inactive";

/** Projection lisible des 5 signaux en 3 groupes (les signaux exacts restent en fiche). */
export function agentAvailabilityGroup(signal: AgentSignal): AgentAvailabilityGroup {
  switch (signal) {
    case "open-session":
      return "active";
    case "recent":
      return "recent";
    default:
      return "inactive";
  }
}

function agentDotLabel(activity: AgentActivity): string {
  switch (activity.signal) {
    case "open-session":
      return "Session de travail ouverte";
    case "recent":
      return "Actif récemment";
    case "past":
      return `Dernière activité le ${fmtTime(activity.lastActivityAt)}`;
    case "unknown":
      return "Activité inconnue";
    case "none":
    default:
      return "Aucune activité observée";
  }
}

function agentDotState(activity: AgentActivity): "info" | "success" | "idle" {
  switch (activity.signal) {
    case "open-session":
      return "info";
    case "recent":
      return "success";
    default:
      return "idle";
  }
}

export function agentRowHtml(
  agent: Agent,
  activity: AgentActivity,
  primaryProject: AgentPrimaryProject | null,
): string {
  const name = agentDisplayName(agent);
  const role = agentRoleLabel(agent);
  const sub = role !== null
    ? (primaryProject !== null ? `${role} · ${primaryProject.name}` : role)
    : (primaryProject !== null ? `Rôle non renseigné · ${primaryProject.name}` : "Rôle non renseigné · aucun projet");
  return (
    `<li class="agent-row"><a class="agent-row-link" href="#/agents/${esc(agent.id)}">` +
    `${dsStatusDot(agentDotState(activity), agentDotLabel(activity), true)}` +
    `<span class="grow"><span class="agent-row-name">${esc(name)}</span>` +
    `<span class="ds-list-sub">${esc(sub)}</span></span>` +
    `<span class="agent-row-chev" aria-hidden="true">›</span></a></li>`
  );
}

/* ------------------------------------------------------------------ */
/* Héros de fiche : « Travaille sur… » + unique action primaire (C1).  */
/* Même ordre honnête que la liste : session ouverte > dernier AI work */
/* > tâche prise > rien affirmé.                                       */
/* ------------------------------------------------------------------ */

export interface AgentHeroTarget {
  title: string;
  body: string;
  taskId: string | null;
  taskTitle: string | null;
  projectId: string | null;
  projectName: string | null;
}

export function agentHeroTarget(
  agent: Agent,
  activity: AgentActivity,
  sessions: WorkSession[],
  aiWork: AIWorkLog[],
  tasks: AgentTask[],
  names: AgentNames,
): AgentHeroTarget {
  const secondaryDown = activity.signal === "unknown";
  if (activity.openSession !== null) {
    const task = names.tasksById.get(activity.openSession.task_id);
    const taskId = activity.openSession.task_id;
    const taskTitle = task?.title ?? FALLBACK_LABEL.task;
    const projectId = task?.project_id ?? null;
    const name = projectId !== null && projectId !== undefined ? projectName(names, projectId) : null;
    return {
      title: `Travaille sur « ${taskTitle} »`,
      body: name !== null
        ? `${name} · session de travail ouverte : signal d'activité, pas preuve de connexion.`
        : "Session de travail ouverte : signal d'activité, pas preuve de connexion.",
      taskId,
      taskTitle,
      projectId: projectId ?? null,
      projectName: name,
    };
  }
  void sessions;
  const ownWork = aiWork
    .filter((work) => work.agent_id === agent.id)
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
  const latest = ownWork[0];
  if (latest !== undefined) {
    const task = latest.task_id !== null && latest.task_id !== undefined ? names.tasksById.get(latest.task_id) : undefined;
    const taskTitle = task?.title ?? (latest.task_id === null || latest.task_id === undefined ? null : FALLBACK_LABEL.task);
    const projectId = task?.project_id ?? latest.project_id ?? null;
    const name = projectId !== null && projectId !== undefined ? projectName(names, projectId) : null;
    const where = taskTitle !== null ? ` sur « ${taskTitle} »` : "";
    const projectPart = name !== null ? ` · ${name}` : "";
    return {
      title: `Dernier travail : ${latest.summary}`,
      body: `${aiWorkStatusLabel(latest.status)}${where}${projectPart} · ${fmtTime(latest.started_at)}.`,
      taskId: latest.task_id ?? null,
      taskTitle,
      projectId,
      projectName: name,
    };
  }
  const claimed = tasks
    .filter((task) => task.claimed_by_agent_id === agent.id)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0];
  if (claimed !== undefined) {
    const name = claimed.project_id !== null && claimed.project_id !== undefined
      ? projectName(names, claimed.project_id)
      : null;
    return {
      title: `Tâche prise : « ${claimed.title} »`,
      body: name !== null ? `${name} · prise par cet agent.` : "Prise par cet agent.",
      taskId: claimed.id,
      taskTitle: claimed.title,
      projectId: claimed.project_id ?? null,
      projectName: name,
    };
  }
  if (secondaryDown) {
    return {
      title: "Travail inconnu",
      body: "Sources secondaires indisponibles — aucun travail affirmé.",
      taskId: null,
      taskTitle: null,
      projectId: null,
      projectName: null,
    };
  }
  return {
    title: "Aucun travail observé",
    body: "Ni session, ni travail, ni tâche attribués à cet agent.",
    taskId: null,
    taskTitle: null,
    projectId: null,
    projectName: null,
  };
}

/** Héros : une seule action primaire « verbe + objet » vers la tâche (C1), projet en secondaire. */
export function agentHeroHtml(target: AgentHeroTarget): string {
  let actions = "";
  if (target.taskId !== null) {
    const primaryLabel = target.taskTitle !== null
      ? `Ouvrir le travail « ${target.taskTitle} »`
      : "Ouvrir le travail";
    const secondary = target.projectId !== null && target.projectName !== null
      ? `<a class="ds-hero-link" href="#/projects/${esc(target.projectId)}">Ouvrir le projet « ${esc(target.projectName)} »</a>`
      : "";
    actions =
      `<div class="ds-hero-actions"><a class="ds-btn ds-btn--primary" href="#/tasks/${esc(target.taskId)}">${esc(primaryLabel)}</a>${secondary}</div>`;
  } else if (target.projectId !== null && target.projectName !== null) {
    actions =
      `<div class="ds-hero-actions"><a class="ds-btn ds-btn--primary" href="#/projects/${esc(target.projectId)}">Ouvrir le projet « ${esc(target.projectName)} »</a></div>`;
  }
  return (
    `<section class="ds-hero agent-hero" aria-label="Travail actuel">` +
    `<p class="ds-hero-eyebrow">Travail actuel</p><h2>${esc(target.title)}</h2>` +
    `<p class="ds-hero-body">${esc(target.body)}</p>${actions}</section>`
  );
}

/* ------------------------------------------------------------------ */
/* Page liste.                                                          */
/* ------------------------------------------------------------------ */

const AGENT_GROUPS: Array<{ key: AgentAvailabilityGroup; title: string }> = [
  { key: "active", title: "En activité" },
  { key: "recent", title: "Actifs récemment" },
  { key: "inactive", title: "Inactifs" },
];

export function agentsListHtml(
  agents: Agent[],
  activities: Map<string, AgentActivity>,
  evidence: { sessions: WorkSession[]; aiWork: AIWorkLog[]; tasks: AgentTask[] },
  names: AgentNames,
  query: string,
  secondaryOk: boolean,
): string {
  const visible = filterAgents(agents, query);
  const toolbar =
    `<div class="agents-toolbar" role="search" aria-label="Rechercher parmi les agents chargés">` +
    `<div class="ds-search"><span class="ds-search-icon" aria-hidden="true">⌕</span>` +
    `<label class="ds-sr-only" for="agents-search">Rechercher un agent déjà chargé</label>` +
    `<input class="ds-input" type="search" id="agents-search" value="${esc(query)}" placeholder="Rechercher par nom ou rôle…" autocomplete="off" /></div>` +
    `<p class="ds-list-sub" role="status" aria-live="polite">${visible.length} agent(s) affiché(s) sur ${agents.length} chargé(s) — recherche locale.</p></div>`;
  const notice = secondaryOk
    ? ""
    : `<div class="ds-notice ds-notice--warning" role="note"><strong>Activité inconnue.</strong> Les sources secondaires (sessions, travail, tâches, événements) sont indisponibles : la liste ci-dessous n'affirme aucune activité.</div>`;
  let body: string;
  if (agents.length === 0) {
    body = dsEmptyState(
      "Aucun agent enregistré",
      "Un agent est une identité de travail attachée à une machine : c'est ce qui permet d'attribuer à qui de droit le travail produit (sessions, AI work, événements). Aucun agent n'est encore enregistré pour ce compte — l'enregistrement se fait depuis chaque machine, il n'y a donc rien à créer ici.",
    );
  } else if (visible.length === 0) {
    body = dsEmptyState(
      "Aucun résultat pour cette recherche",
      "Modifiez la recherche pour retrouver vos agents déjà chargés.",
    );
  } else {
    const activityOf = (agent: Agent): AgentActivity =>
      activities.get(agent.id) ?? {
        signal: secondaryOk ? ("none" as const) : ("unknown" as const),
        openSession: null,
        lastActivityAt: null,
        lastActivitySource: null,
        workCount: 0,
        sessionCount: 0,
      };
    const sections = AGENT_GROUPS.map((group) => {
      const members = visible.filter((agent) => agentAvailabilityGroup(activityOf(agent).signal) === group.key);
      if (members.length === 0) return "";
      const rows = members
        .map((agent) => {
          const activity = activityOf(agent);
          return agentRowHtml(agent, activity, agentPrimaryProject(agent, activity, evidence.aiWork, evidence.tasks, names));
        })
        .join("");
      return (
        `<section class="agents-group" aria-label="${esc(group.title)}">` +
        `<h2 class="agents-group-title">${esc(group.title)} <span class="ds-list-sub">(${members.length})</span></h2>` +
        `<ul class="agents-list">${rows}</ul></section>`
      );
    }).join("");
    body = `<div class="agents-groups">${sections}</div>`;
  }
  return (
    `${dsPageHeader("Agents IA", "Rôle, disponibilité et projet visibles d'un coup d'œil. Le reste dort dans la fiche.")}` +
    `${notice}${toolbar}${body}`
  );
}

export function agentsLoadingHtml(): string {
  return `${dsPageHeader("Agents IA", "Vos collaborateurs logiciels.")}${dsSkeleton(4)}`;
}

export async function renderAgents(root: HTMLElement, ctx: AgentsContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML =
      `<div class="agents">${dsPageHeader("Agents IA", "Vos collaborateurs logiciels.")}` +
      dsEmptyState("Connectez-vous pour voir les agents", "Saisissez votre jeton machine pour charger les agents.") +
      `</div>`;
    return;
  }
  root.innerHTML = `<div class="agents">${agentsLoadingHtml()}</div>`;

  let agents: Agent[];
  try {
    agents = await fetchAgents(ctx.client);
  } catch (error) {
    root.innerHTML =
      `<div class="agents">${dsPageHeader("Agents IA", "Vos collaborateurs logiciels.")}` +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Agents indisponibles.</strong>${esc(describeError(error))}</div></div>`;
    return;
  }

  const settled = await Promise.allSettled([
    fetchAgentSessions(ctx.client),
    fetchAgentWork(ctx.client),
    fetchAgentTasks(ctx.client),
    fetchAgentProjects(ctx.client),
    fetchAgentEvents(ctx.client),
  ]);
  const sessions = settled[0].status === "fulfilled" ? settled[0].value : [];
  const aiWork = settled[1].status === "fulfilled" ? settled[1].value : [];
  const tasks = settled[2].status === "fulfilled" ? settled[2].value : [];
  const projects = settled[3].status === "fulfilled" ? settled[3].value : [];
  const events: AgentEvent[] = settled[4].status === "fulfilled" ? settled[4].value : [];
  const secondaryOk = settled.every((result) => result.status === "fulfilled");
  const names = buildAgentNames(tasks, projects);

  let query = "";
  const paint = (): void => {
    const activities = new Map<string, AgentActivity>();
    for (const agent of agents) {
      activities.set(
        agent.id,
        deriveAgentActivity(agent.id, { sessions, aiWork, tasks, events, secondaryOk }),
      );
    }
    root.innerHTML = `<div class="agents">${agentsListHtml(agents, activities, { sessions, aiWork, tasks }, names, query, secondaryOk)}</div>`;
    const search = root.querySelector<HTMLInputElement>("#agents-search");
    search?.addEventListener("input", () => {
      query = search.value;
      paint();
      const next = root.querySelector<HTMLInputElement>("#agents-search");
      if (next !== null) {
        next.focus();
        next.setSelectionRange(next.value.length, next.value.length);
      }
    });
  };
  paint();
}

/* ------------------------------------------------------------------ */
/* Fiche agent : construite côté client depuis la liste + secondaires  */
/* (aucun GET /agents/{id} serveur — l'agrégation suffit à une fiche   */
/* utile : identité, travail, activité, environnement).                 */
/* ------------------------------------------------------------------ */

export function agentNotFoundHtml(id: string): string {
  return (
    `${dsPageHeader("Agent introuvable", "")}` +
    `<p><a href="#/agents">← Retour aux agents</a></p>` +
    dsEmptyState("Agent introuvable", `Cet agent n'apparaît pas parmi les agents chargés. Il a peut-être été révoqué, ou votre jeton ne le voit pas.`)
  );
}

function workRowHtml(work: AIWorkLog, names: AgentNames): string {
  const task = work.task_id !== null && work.task_id !== undefined ? names.tasksById.get(work.task_id) : undefined;
  const taskPart = work.task_id === null || work.task_id === undefined ? "" : ` · sur ${taskLinkHtml(task, work.task_id)}`;
  const projectPart = task !== undefined ? projectSuffixHtml(names, task.project_id) : projectSuffixHtml(names, work.project_id);
  return (
    `<li class="ds-list-item"><span class="grow"><span class="ds-list-title">${esc(work.summary)}</span>` +
    `<br /><span class="ds-list-sub">${fmtTime(work.started_at)}${work.ended_at !== null ? ` → ${fmtTime(work.ended_at)}` : ""}${taskPart}${projectPart}</span></span>` +
    `${dsBadge(aiWorkStatusLabel(work.status), aiWorkStatusTone(work.status))}</li>`
  );
}

function sessionRowHtml(session: WorkSession, names: AgentNames): string {
  const task = names.tasksById.get(session.task_id);
  const state = session.ended_at === null || session.ended_at === undefined
    ? dsBadge("Ouverte", "info")
    : dsBadge("Terminée", "neutral");
  return (
    `<li class="ds-list-item"><span class="grow"><span class="ds-list-title">Session sur ${taskLinkHtml(task, session.task_id)}</span>` +
    `<br /><span class="ds-list-sub">Depuis le ${fmtTime(session.started_at)}${session.ended_at ? ` → ${fmtTime(session.ended_at)}` : " (toujours ouverte : signal d'activité, pas preuve de connexion)"}</span></span>${state}</li>`
  );
}

export function agentDetailHtml(
  agent: Agent,
  activity: AgentActivity,
  sessions: WorkSession[],
  aiWork: AIWorkLog[],
  names: AgentNames,
): string {
  const name = agentDisplayName(agent);
  const role = agentRoleLabel(agent);
  const hero = agentHeroTarget(agent, activity, sessions, aiWork, [...names.tasksById.values()], names);
  const subtitle = `${role ?? "Rôle non renseigné"} · ${hero.projectName ?? "aucun projet"}`;
  const ownWork = aiWork
    .filter((work) => work.agent_id === agent.id)
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
  const ownSessions = sessions
    .filter((session) => session.agent_id === agent.id)
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
  const declaredOrDash = (value: string | null | undefined): string =>
    value !== null && value !== undefined && value.trim() !== "" ? value : "—";

  return (
    `<p><a href="#/agents">← Retour aux agents</a></p>` +
    `${dsPageHeader(name, subtitle)}` +
    `${agentHeroHtml(hero)}` +
    `<section class="ds-panel" aria-label="Activité"><header><h2>Activité</h2></header><div class="body" role="status">${agentSignalHtml(activity)}</div></section>` +
    `<section class="ds-panel" aria-label="Travail produit"><header><h2>Travail produit</h2><span class="ds-list-sub">${ownWork.length} entrée(s) — la relecture détaillée se fait dans Décisions, onglet À valider</span></header><div class="body">` +
    (ownWork.length === 0
      ? `<p class="ds-list-sub">Aucun travail attribué à cet agent.</p>`
      : `<ul class="ds-list">${ownWork.map((work) => workRowHtml(work, names)).join("")}</ul>`) +
    `</div></section>` +
    `<section class="ds-panel" aria-label="Sessions"><header><h2>Sessions</h2><span class="ds-list-sub">${ownSessions.length} session(s) — une session ouverte est un signal, pas une preuve de connexion</span></header><div class="body">` +
    (ownSessions.length === 0
      ? `<p class="ds-list-sub">Aucune session attribuée à cet agent.</p>`
      : `<ul class="ds-list">${ownSessions.map((session) => sessionRowHtml(session, names)).join("")}</ul>`) +
    `</div></section>` +
    `<section class="ds-panel" aria-label="Environnement"><header><h2>Environnement</h2></header><div class="body">` +
    `<p>Exécuté sur la machine <a href="#/machines">${machineRef(agent.machine_id)}</a>.</p>` +
    `<p class="ds-list-sub">${machineName(agent.machine_id) === undefined ? "Le nom de cette machine n'est pas connu du tableau de bord. " : ""}L'agent n'est pas une sous-catégorie de la machine — voir <a href="#/machines">Machines</a> pour l'environnement d'exécution.</p>` +
    `<p class="ds-list-sub">Aucune définition d'agent n'est associée : la nature déclarée est une simple étiquette libre, sans lien avec la <a href="#/library/agent-definitions">Bibliothèque</a>. Aucune configuration runtime détaillée ici : voir <a href="#/configuration/runtimes">Paramètres</a>.</p>` +
    `</div></section>` +
    dsTechDetails(
      [
        { label: "Modèle déclaré", value: declaredOrDash(agent.model) },
        { label: "Fournisseur déclaré", value: declaredOrDash(agent.provider) },
        { label: "Harnais déclaré", value: declaredOrDash(agent.harness) },
        {
          label: "Permissions",
          value: "Aucune permission déclarée par l'agent — voir Paramètres runtime",
        },
        { label: "Définition liée", value: "Aucune définition associée" },
        { label: "Identifiant agent", value: agent.id, mono: true },
        {
          label: "Identifiant machine",
          value: agent.machine_id ? agent.machine_id : "—",
          mono: agent.machine_id ? true : undefined,
        },
        { label: "Révision", value: `v${agent.version}`, mono: true },
        { label: "Créé le", value: fmtTime(agent.created_at) },
        { label: "Mis à jour le", value: fmtTime(agent.updated_at) },
      ],
      "Détails techniques · modèle, permissions, identifiants",
    ) +
    `<section class="ds-panel agent-admin" aria-label="Administration"><header><h2>Administration</h2><span class="ds-list-sub">séparée du quotidien</span></header><div class="body">` +
    `<p class="ds-list-sub">Réglages sensibles : ils ne changent pas le statut du jour et restent ici, hors du flux de travail. Renommer et révoquer se font depuis la machine d'exécution — il n'y a aucune action à distance ici.</p>` +
    `<p class="agent-admin-actions"><a class="ds-btn" href="#/machines">Voir la machine</a> <a class="ds-btn" href="#/configuration/runtimes">Paramètres runtime</a></p>` +
    `</div></section>`
  );
}

export async function renderAgentDetail(root: HTMLElement, ctx: AgentsContext, id: string): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML =
      `<div class="agents">${dsPageHeader("Agent", "")}` +
      dsEmptyState("Connectez-vous pour voir cet agent", "Saisissez votre jeton machine pour charger les agents.") +
      `</div>`;
    return;
  }
  root.innerHTML = `<div class="agents">${agentsLoadingHtml()}</div>`;

  let agents: Agent[];
  try {
    agents = await fetchAgents(ctx.client);
  } catch (error) {
    root.innerHTML =
      `<div class="agents">${dsPageHeader("Agent", "")}` +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Agent indisponible.</strong>${esc(describeError(error))}</div></div>`;
    return;
  }
  const agent = agents.find((candidate) => candidate.id === id);
  if (agent === undefined) {
    root.innerHTML = `<div class="agents">${agentNotFoundHtml(id)}</div>`;
    return;
  }

  const settled = await Promise.allSettled([
    fetchAgentSessions(ctx.client),
    fetchAgentWork(ctx.client),
    fetchAgentTasks(ctx.client),
    fetchAgentProjects(ctx.client),
    fetchAgentEvents(ctx.client),
  ]);
  const sessions = settled[0].status === "fulfilled" ? settled[0].value : [];
  const aiWork = settled[1].status === "fulfilled" ? settled[1].value : [];
  const tasks = settled[2].status === "fulfilled" ? settled[2].value : [];
  const projects = settled[3].status === "fulfilled" ? settled[3].value : [];
  const events: AgentEvent[] = settled[4].status === "fulfilled" ? settled[4].value : [];
  const secondaryOk = settled.every((result) => result.status === "fulfilled");
  const names = buildAgentNames(tasks, projects);
  const activity = deriveAgentActivity(agent.id, { sessions, aiWork, tasks, events, secondaryOk });
  const notice = secondaryOk
    ? ""
    : `<div class="ds-notice ds-notice--warning" role="note"><strong>Activité partielle.</strong> Certaines sources secondaires sont indisponibles : ce qui suit peut être incomplet.</div>`;
  root.innerHTML = `<div class="agents">${notice}${agentDetailHtml(agent, activity, sessions, aiWork, names)}</div>`;
}
