/**
 * UI-6 — Agents IA : première surface dédiée aux collaborateurs logiciels.
 *
 * Page calme (ni table de processus, ni monitoring) : qui sont les agents,
 * que font-ils, sur quoi travaillent-ils, avec quel environnement.
 * Distinctions imposées (jamais fusionnées) : Agent (identité/provenance)
 * ≠ Machine (exécution) ≠ Model (modèle IA) ≠ Runtime (provider/harness)
 * ≠ Binding (association stockée). Seules les relations backend réelles
 * sont affichées (voir agentsApi) : aucune définition associée simulée,
 * aucun mapping runtime/model inventé, aucune présence canonique.
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
  type AgentTask,
  type AIWorkLog,
  type WorkSession,
} from "../agentsApi";
import {
  dsAvatar,
  dsBadge,
  dsEmptyState,
  dsPageHeader,
  dsSkeleton,
  dsStatus,
} from "../ds/ds";
import { describeError, esc, fmtTime, shortId } from "../ui";
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
  if (task === undefined) return `<code class="mono" title="${esc(fallbackId)}">${esc(shortId(fallbackId))}</code>`;
  return `<a href="#/tasks/${esc(task.id)}">« ${esc(task.title)} »</a>`;
}

function projectSuffixHtml(names: AgentNames, projectId: string | null | undefined): string {
  if (projectId === null || projectId === undefined) return "";
  const name = projectName(names, projectId);
  if (name === null) return "";
  return ` — <a href="#/projects/${esc(projectId)}">${esc(name)}</a>`;
}

/** « Travaille sur » honnête : session ouverte > dernier AI work > tâche prise > rien affirmé. */
export function agentWorkSummaryHtml(
  agent: Agent,
  activity: AgentActivity,
  sessions: WorkSession[],
  aiWork: AIWorkLog[],
  tasks: AgentTask[],
  names: AgentNames,
): string {
  const secondaryDown = activity.signal === "unknown";
  if (activity.openSession !== null) {
    const task = names.tasksById.get(activity.openSession.task_id);
    return `<p class="agent-work"><strong>Travaille sur</strong> ${taskLinkHtml(task, activity.openSession.task_id)}${projectSuffixHtml(names, task?.project_id)}</p>`;
  }
  const ownWork = aiWork
    .filter((work) => work.agent_id === agent.id)
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
  const latest = ownWork[0];
  if (latest !== undefined) {
    const task = latest.task_id !== null && latest.task_id !== undefined ? names.tasksById.get(latest.task_id) : undefined;
    const taskPart = latest.task_id === null || latest.task_id === undefined ? "" : ` sur ${taskLinkHtml(task, latest.task_id)}`;
    const projectPart = task !== undefined ? projectSuffixHtml(names, task.project_id) : projectSuffixHtml(names, latest.project_id);
    return `<p class="agent-work"><strong>Dernier travail observé</strong> — ${esc(latest.summary)}${taskPart}${projectPart} ${dsBadge(aiWorkStatusLabel(latest.status), aiWorkStatusTone(latest.status))}</p>`;
  }
  const claimed = tasks
    .filter((task) => task.claimed_by_agent_id === agent.id)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0];
  if (claimed !== undefined) {
    return `<p class="agent-work"><strong>Tâche prise</strong> ${taskLinkHtml(claimed, claimed.id)}${projectSuffixHtml(names, claimed.project_id)}</p>`;
  }
  void sessions;
  if (secondaryDown) {
    return `<p class="agent-work ds-list-sub">Travail inconnu — sources secondaires indisponibles.</p>`;
  }
  return `<p class="agent-work ds-list-sub">Aucun travail observé pour cet agent.</p>`;
}

/* ------------------------------------------------------------------ */
/* Carte agent : identité d'abord, technique en second.                 */
/* ------------------------------------------------------------------ */

function declaredTechHtml(agent: Agent): string {
  const parts: string[] = [];
  if (agent.provider !== null && agent.provider !== undefined && agent.provider !== "") {
    parts.push(`Fournisseur déclaré : ${esc(agent.provider)}`);
  }
  if (agent.model !== null && agent.model !== undefined && agent.model !== "") {
    parts.push(`Modèle déclaré : ${esc(agent.model)}`);
  }
  if (agent.harness !== null && agent.harness !== undefined && agent.harness !== "") {
    parts.push(`Harnais déclaré : ${esc(agent.harness)}`);
  }
  if (parts.length === 0) return "";
  return `<p class="ds-list-sub">${parts.join(" · ")}</p>`;
}

export function agentCardHtml(
  agent: Agent,
  activity: AgentActivity,
  sessions: WorkSession[],
  aiWork: AIWorkLog[],
  tasks: AgentTask[],
  names: AgentNames,
): string {
  const kind = agent.agent_kind.trim() === "" ? null : agent.agent_kind;
  const profile =
    agent.agent_profile !== null && agent.agent_profile !== undefined && agent.agent_profile.trim() !== ""
      ? agent.agent_profile
      : null;
  return (
    `<li class="ds-card agent-card"><div class="agent-card-top">${dsAvatar(agent.display_name)}` +
    `<div class="grow"><h3 class="agent-card-title"><a href="#/agents/${esc(agent.id)}">${esc(agent.display_name)}</a></h3>` +
    (kind !== null ? `<p class="ds-list-sub">Nature déclarée : <code class="mono">${esc(kind)}</code></p>` : "") +
    (profile !== null ? `<p>${esc(profile)}</p>` : "") +
    `</div></div>` +
    `<div class="agent-signal" role="status">${agentSignalHtml(activity)}</div>` +
    `${agentWorkSummaryHtml(agent, activity, sessions, aiWork, tasks, names)}` +
    `<p class="ds-list-sub">Exécuté sur la machine <a href="#/machines"><code class="mono" title="${esc(agent.machine_id ?? "")}">${esc(shortId(agent.machine_id))}</code></a> · <a href="#/agents/${esc(agent.id)}">Ouvrir la fiche</a></p>` +
    `${declaredTechHtml(agent)}` +
    `</li>`
  );
}

/* ------------------------------------------------------------------ */
/* Page liste.                                                          */
/* ------------------------------------------------------------------ */

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
    `<input class="ds-input" type="search" id="agents-search" value="${esc(query)}" placeholder="Rechercher par nom, nature ou modèle déclaré…" autocomplete="off" /></div>` +
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
    const cards = visible
      .map((agent) => {
        const activity = activities.get(agent.id) ?? {
          signal: secondaryOk ? ("none" as const) : ("unknown" as const),
          openSession: null,
          lastActivityAt: null,
          lastActivitySource: null,
          workCount: 0,
          sessionCount: 0,
        };
        return agentCardHtml(agent, activity, evidence.sessions, evidence.aiWork, evidence.tasks, names);
      })
      .join("");
    body = `<ul class="agents-list">${cards}</ul>`;
  }
  return (
    `${dsPageHeader("Agents IA", "Vos collaborateurs logiciels : qui ils sont, sur quoi ils travaillent, avec quel environnement.")}` +
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
    dsEmptyState("Agent introuvable", `Aucun agent « ${shortId(id)} » parmi les agents chargés. Il a peut-être été révoqué, ou votre jeton ne le voit pas.`)
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
  const kind = agent.agent_kind.trim() === "" ? null : agent.agent_kind;
  const ownWork = aiWork
    .filter((work) => work.agent_id === agent.id)
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
  const ownSessions = sessions
    .filter((session) => session.agent_id === agent.id)
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
  const declared: Array<[string, string | null | undefined]> = [
    ["Nature déclarée", kind],
    ["Profil déclaré", agent.agent_profile],
    ["Harnais déclaré", agent.harness],
    ["Fournisseur déclaré", agent.provider],
    ["Modèle déclaré", agent.model],
  ];
  const declaredHtml = declared
    .map(([label, value]) => {
      const text = value !== null && value !== undefined && value.trim() !== "" ? esc(value) : '<span class="ds-list-sub">—</span>';
      return `<div><dt>${esc(label)}</dt><dd>${text}</dd></div>`;
    })
    .join("");

  return (
    `<p><a href="#/agents">← Retour aux agents</a></p>` +
    `${dsPageHeader(agent.display_name, kind !== null ? `Nature déclarée : ${kind}` : "Collaborateur logiciel.")}` +
    `<section class="ds-panel" aria-label="Activité"><header><h2>Activité</h2></header><div class="body" role="status">${agentSignalHtml(activity)}</div></section>` +
    `<section class="ds-panel" aria-label="Travail actuel"><header><h2>Travail actuel</h2></header><div class="body">${agentWorkSummaryHtml(agent, activity, sessions, aiWork, [...names.tasksById.values()], names)}</div></section>` +
    `<section class="ds-panel" aria-label="Résumé"><header><h2>Résumé</h2></header><div class="body"><dl class="library-kv">${declaredHtml}</dl>` +
    `<p class="ds-list-sub">${ownWork.length} travail(aux) · ${ownSessions.length} session(s) attribué(s) à cet agent.</p></div></section>` +
    `<section class="ds-panel" aria-label="Travail produit"><header><h2>Travail produit</h2><span class="ds-list-sub">${ownWork.length} entrée(s) — la relecture détaillée se fait dans Décisions, onglet À examiner</span></header><div class="body">` +
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
    `<p>Exécuté sur la machine <a href="#/machines"><code class="mono" title="${esc(agent.machine_id ?? "")}">${esc(shortId(agent.machine_id))}</code></a>.</p>` +
    `<p class="ds-list-sub">Le nom de cette machine n'est pas connu du tableau de bord. L'agent n'est pas une sous-catégorie de la machine — voir <a href="#/machines">Machines</a> pour l'environnement d'exécution.</p>` +
    `<p class="ds-list-sub">Aucune définition d'agent n'est associée : la nature déclarée est une simple étiquette libre, sans lien avec la <a href="#/library/agent-definitions">Bibliothèque</a>. Aucune configuration runtime détaillée ici : voir <a href="#/configuration/runtimes">Paramètres</a>.</p>` +
    `</div></section>` +
    `<details class="library-tech"><summary>Informations techniques</summary><dl class="library-tech-list">` +
    `<div><dt>Identifiant agent</dt><dd><code class="mono">${esc(agent.id)}</code></dd></div>` +
    `<div><dt>Identifiant machine</dt><dd>${agent.machine_id ? `<code class="mono">${esc(agent.machine_id)}</code>` : '<span class="ds-list-sub">—</span>'}</dd></div>` +
    `<div><dt>Révision</dt><dd>v${agent.version}</dd></div>` +
    `<div><dt>Créé le</dt><dd>${fmtTime(agent.created_at)}</dd></div>` +
    `<div><dt>Mis à jour le</dt><dd>${fmtTime(agent.updated_at)}</dd></div>` +
    `</dl></details>`
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
