/**
 * UI-9 — Machines : une infrastructure compréhensible par un humain.
 *
 * Une MACHINE est l'environnement enregistré sur lequel du travail peut
 * s'exécuter ou être observé — ce n'est ni un agent (qui travaille), ni un
 * utilisateur, ni un modèle, ni un runtime (voir rapport UI-9).
 *
 * Sources réelles (audit UI-9) :
 * - `GET /machines` (DEC-0082) donne la liste canonique et `last_seen_at`
 *   (heartbeat). Face à un backend antérieur (404/405/501) la sonde
 *   dégrade vers `null` et la page construit une présence DÉDUITE depuis
 *   `GET /agents`, `GET /sessions`, `GET /events?since=24h` et
 *   `GET /runtimes` (best-effort). Pas de `GET /machines/{id}`.
 * - `display_name` canonique indisponible en liste : titre humain quand il
 *   existe, sinon "Machine sans nom enregistré" + identifiant court —
 *   jamais "Machine 1/2" fabriqué.
 * - Vocabulaire honnête : le déduit parle d'ACTIVITÉ ("Activité récente",
 *   "Aucune activité récente connue"), jamais "En ligne"/"Hors ligne".
 * - Aucune action machine exposée : révocation et création sont des
 *   opérations admin hors interface (constat documenté, pas de bouton).
 * - Pas de route détail `#/machines/<id>` (aucun endpoint) : liste de
 *   cartes + tiroir DS.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { getToken } from "../auth";
import {
  activityLabelFr,
  buildMachineRows,
  fetchAgents,
  fetchCanonicalMachines,
  fetchSessions,
  filterMachineRows,
  formatRelativeFr,
  initialMachinesState,
  isMachinesDefaultState,
  machineDisplayTitle,
  MACHINE_PRESENCE_EVENT_TYPES,
  type Agent,
  type EventEnvelope,
  type Machine,
  type MachineActivityFilter,
  type MachineRow,
  type MachinesPageState,
  type WorkSession,
} from "../machinesApi";
import { listRuntimes, type RuntimeRegistration } from "../runtimesApi";
import {
  dsBadge,
  dsDrawerHtml,
  dsEmptyState,
  dsPageHeader,
  dsSkeleton,
  dsStatus,
  openDsDialog,
} from "../ds/ds";
import { describeError, esc, fmtTime, shortId } from "../ui";
import "./machines.css";

export interface MachinesContext {
  client: StudioClient;
  baseUrl: string;
  authed: boolean;
}

type Settled<T> = { ok: true; value: T } | { ok: false; error: unknown };

async function settle<T>(promise: Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, value: await promise };
  } catch (error) {
    return { ok: false, error };
  }
}

export function machinesLoadingHtml(): string {
  return (
    `<div class="machines">` +
    `${dsPageHeader("Machines", "Environnements enregistrés sur lesquels le travail s'exécute.")}` +
    `${dsSkeleton(4)}</div>`
  );
}

const ACTIVITY_OPTIONS: { value: MachineActivityFilter; label: string }[] = [
  { value: "all", label: "Toutes les activités" },
  { value: "online", label: "Activité récente" },
  { value: "idle", label: "Peu d'activité récente" },
  { value: "offline", label: "Aucune activité récente connue" },
];

export function machinesToolbarHtml(state: MachinesPageState, shown: number, total: number): string {
  const options = ACTIVITY_OPTIONS.map(
    (option) =>
      `<option value="${option.value}"${state.activity === option.value ? " selected" : ""}>${esc(option.label)}</option>`,
  ).join("");
  return (
    `<div class="machines-toolbar" role="search" aria-label="Filtrer les machines chargées">` +
    `<div class="ds-search"><span class="ds-search-icon" aria-hidden="true">⌕</span>` +
    `<label class="ds-sr-only" for="machines-search">Filtrer les machines déjà chargées</label>` +
    `<input class="ds-input" type="search" id="machines-search" value="${esc(state.query)}" placeholder="Filtrer par nom ou identifiant…" autocomplete="off" /></div>` +
    `<label class="machines-activity-filter"><span>Activité</span>` +
    `<select class="ds-select" id="machines-activity">${options}</select></label>` +
    `<button class="ds-btn ds-btn--ghost" type="button" data-reset${isMachinesDefaultState(state) ? " disabled" : ""}>Réinitialiser</button>` +
    `<p class="ds-list-sub" role="status" aria-live="polite">${shown} machine(s) affichée(s) sur ${total} chargée(s) — recherche et filtre locaux.</p>` +
    `</div>`
  );
}

/** Pastille d'activité : couleur + libellé + source, jamais la couleur seule. */
export function machineStatusHtml(row: MachineRow): string {
  const activity = activityLabelFr(row.status, row.statusSource);
  const source = row.statusSource === "canonical" ? "Serveur" : "Déduit";
  return (
    `<span class="machine-status" title="${esc(activity.hint)}">` +
    `${dsStatus(activity.tone, activity.label)}${dsBadge(source)}</span>`
  );
}

function machineTimeHtml(iso: string | null, now: number): string {
  if (iso === null) return "—";
  const relative = formatRelativeFr(iso, now);
  const suffix = relative === null || relative === "à l'instant" ? "" : ` <span class="meta">(${esc(relative)})</span>`;
  return `<time datetime="${esc(iso)}">${fmtTime(iso)}</time>${suffix}`;
}

export interface MachineCardInfo {
  agentNames: string[];
  activeSession: WorkSession | null;
}

function machineContextLine(row: MachineRow, info: MachineCardInfo): string {
  const parts: string[] = [];
  if (info.agentNames.length === 0) {
    parts.push("Aucun agent observé");
  } else if (info.agentNames.length === 1) {
    parts.push(`Agent observé : ${info.agentNames[0] ?? ""}`);
  } else {
    parts.push(`${info.agentNames.length} agents observés (${info.agentNames.slice(0, 2).join(", ")}…)`);
  }
  parts.push(info.activeSession === null ? "Aucune session en cours" : "Session en cours");
  return parts.map((part) => esc(part)).join(" · ");
}

export function machineCardHtml(row: MachineRow, info: MachineCardInfo, now: number): string {
  return (
    `<li class="ds-list-item machine-row"><div class="grow">` +
    `<h3 class="ds-list-title">${esc(machineDisplayTitle(row))}</h3>` +
    `<div class="ds-list-sub"><code class="mono" title="${esc(row.machineId)}">${esc(shortId(row.machineId))}</code></div>` +
    `<div class="ds-list-sub">${machineContextLine(row, info)}</div>` +
    `<div class="ds-list-sub">Dernière activité : ${machineTimeHtml(row.lastActivityAt, now)}</div>` +
    `</div><div class="machine-side">${machineStatusHtml(row)}` +
    `<button class="ds-btn ds-btn--sm" type="button" data-machine-details="${esc(row.machineId)}">Détails</button></div></li>`
  );
}

export function machinesListHtml(rows: MachineRow[], infos: Map<string, MachineCardInfo>, now: number): string {
  return (
    `<ul class="ds-list machines-list">` +
    rows.map((row) => machineCardHtml(row, infos.get(row.machineId) ?? { agentNames: [], activeSession: null }, now)).join("") +
    `</ul>`
  );
}

export function machinesEmptyHtml(): string {
  return dsEmptyState(
    "Aucune machine observée",
    "Une machine est l'environnement enregistré sur lequel le travail s'exécute — à distinguer des agents qui y travaillent. " +
      "Les machines sont provisionnées par un administrateur hors de cette interface : aucune n'a encore laissé de trace visible pour ce jeton.",
  );
}

export function machinesNoMatchHtml(): string {
  return dsEmptyState(
    "Aucune machine ne correspond",
    "Modifiez la recherche ou le filtre d'activité pour retrouver vos machines déjà chargées.",
  );
}

function runtimeSummary(runtime: RuntimeRegistration): string {
  const refs = [runtime.harness_ref, runtime.provider_ref, runtime.model_ref].filter(
    (ref): ref is string => ref !== null && ref !== undefined && ref !== "",
  );
  return refs.length === 0 ? "Runtime sans référence déclarée" : refs.join(" · ");
}

export function machineDrawerBodyHtml(
  row: MachineRow,
  agents: Agent[],
  sessions: WorkSession[],
  runtimes: RuntimeRegistration[],
  now: number,
): string {
  const activity = activityLabelFr(row.status, row.statusSource);
  const active = sessions.filter((session) => session.ended_at === null || session.ended_at === undefined);
  const past = sessions
    .filter((session) => session.ended_at !== null && session.ended_at !== undefined)
    .sort((a, b) => (b.ended_at ?? "").localeCompare(a.ended_at ?? ""))
    .slice(0, 3);
  const agentById = new Map(agents.map((agent) => [agent.id, agent]));
  const linked = runtimes.filter((runtime) => runtime.machine_id === row.machineId);

  const sessionItem = (session: WorkSession): string =>
    `<li><a href="#/tasks/${esc(session.task_id)}">Tâche ${esc(shortId(session.task_id))}</a>` +
    ` · démarrée le ${machineTimeHtml(session.started_at, now)}` +
    (session.agent_id !== null && session.agent_id !== undefined && agentById.has(session.agent_id)
      ? ` · agent <a href="#/agents/${esc(session.agent_id)}">${esc(agentById.get(session.agent_id)?.display_name ?? shortId(session.agent_id))}</a>`
      : "") +
    `</li>`;

  const observedAgents = agents
    .filter((agent) => agent.machine_id === row.machineId)
    .map((agent) => `<a href="#/agents/${esc(agent.id)}">${esc(agent.display_name)}</a>`)
    .join(", ");

  const summary =
    `<div class="machine-drawer-summary">${machineStatusHtml(row)}` +
    `<p class="ds-list-sub">${esc(activity.hint)}</p>` +
    `<dl class="machine-facts">` +
    `<div><dt>Dernière activité connue</dt><dd>${machineTimeHtml(row.lastActivityAt, now)}</dd></div>` +
    `<div><dt>Agents observés</dt><dd>${agents.length === 0 ? "Aucun" : observedAgents}</dd></div>` +
    `<div><dt>Sessions en cours</dt><dd>${active.length === 0 ? "Aucune" : String(active.length)}</dd></div>` +
    `</dl></div>`;

  const usage =
    `<h3>Utilisation récente</h3>` +
    (active.length === 0 && past.length === 0
      ? `<p class="ds-list-sub">Aucune session observée pour cette machine.</p>`
      : `<ul class="machine-sessions">${active.map(sessionItem).join("")}${past.map(sessionItem).join("")}</ul>`);

  const environment =
    `<h3>Environnement</h3>` +
    (linked.length === 0
      ? `<p class="ds-list-sub">Aucun runtime rattaché à cette machine. La configuration des runtimes reste dans Paramètres.</p>`
      : `<ul class="machine-runtimes">` +
        linked
          .map(
            (runtime) =>
              `<li><a href="#/configuration/runtimes/${esc(runtime.id)}">${esc(runtimeSummary(runtime))}</a> ` +
              `${runtime.status === "active" ? dsBadge("Actif", "success") : dsBadge("Révoqué", "neutral")}</li>`,
          )
          .join("") +
        `</ul>`);

  const technical =
    `<details class="machine-technical"><summary>Informations techniques</summary><dl class="machine-facts">` +
    `<div><dt>Identifiant complet</dt><dd><code class="mono">${esc(row.machineId)}</code></dd></div>` +
    `<div><dt>Nom enregistré</dt><dd>${row.displayName === null || row.displayName.trim() === "" ? "Non renseigné" : esc(row.displayName)}</dd></div>` +
    `<div><dt>Propriétaire</dt><dd>${row.ownerUserId === null ? "Inconnu — lecture canonique indisponible" : esc(shortId(row.ownerUserId))}</dd></div>` +
    `<div><dt>Dernier heartbeat serveur</dt><dd>${row.lastSeenAt === null ? "Indisponible — pas de lecture canonique" : machineTimeHtml(row.lastSeenAt, now)}</dd></div>` +
    `<div><dt>Statut technique</dt><dd><code class="mono">${esc(row.status)}</code> (${row.statusSource === "canonical" ? "canonique" : "déduit"})</dd></div>` +
    `</dl><p class="ds-list-sub">Révocation : action administrateur, non proposée dans cette interface.</p></details>`;

  return `<h3 class="machine-drawer-title">${esc(machineDisplayTitle(row))}</h3>` + summary + usage + environment + technical;
}

export interface MachinesPageData {
  rows: MachineRow[];
  agents: Agent[];
  sessions: WorkSession[];
  runtimes: RuntimeRegistration[];
  state: MachinesPageState;
  canonicalAvailable: boolean;
  problems: string[];
  now: number;
}

export function machinesPageHtml(data: MachinesPageData): string {
  const header = dsPageHeader(
    "Machines",
    "Environnements enregistrés sur lesquels le travail s'exécute — à distinguer des agents qui y travaillent.",
    [{ label: "Actualiser", id: "machines-reload" }],
  );
  const notice = data.canonicalAvailable
    ? `<div class="machines-notice" role="status">Présence confirmée par le serveur (heartbeat).</div>`
    : `<div class="machines-notice" role="status">Présence déduite des agents, sessions et événements récents — <strong>pas un état de connexion garanti</strong>. ` +
      `Aucune mesure CPU, RAM ou disponibilité n'est collectée par Studi'OS.</div>`;
  const degraded =
    data.problems.length === 0
      ? ""
      : `<div class="machines-notice machines-notice--warning" role="status">Données partielles : ${esc(data.problems.join(" · "))} — la liste reste consultable.</div>`;
  const infos = cardInfos(data.rows, data.agents, data.sessions);
  const visible = filterMachineRows(data.rows, data.state);
  let body: string;
  if (data.rows.length === 0) {
    body = machinesEmptyHtml();
  } else if (visible.length === 0) {
    body = machinesNoMatchHtml();
  } else {
    body = machinesListHtml(visible, infos, data.now);
  }
  return (
    `<div class="machines">${header}${notice}${degraded}` +
    (data.rows.length === 0 ? "" : machinesToolbarHtml(data.state, visible.length, data.rows.length)) +
    `<div id="machines-list">${body}</div>` +
    `${dsDrawerHtml({ id: "machine-drawer", title: "Détails de la machine", body: `<div id="machine-drawer-body"></div>`, actions: [{ label: "Fermer", variant: "primary" }] })}</div>`
  );
}

export function cardInfos(
  rows: MachineRow[],
  agents: Agent[],
  sessions: WorkSession[],
): Map<string, MachineCardInfo> {
  const infos = new Map<string, MachineCardInfo>();
  for (const row of rows) infos.set(row.machineId, { agentNames: [], activeSession: null });
  for (const agent of agents) {
    if (agent.machine_id === null || agent.machine_id === undefined) continue;
    const info = infos.get(agent.machine_id);
    if (info !== undefined) info.agentNames.push(agent.display_name);
  }
  for (const session of sessions) {
    const info = infos.get(session.machine_id);
    if (info !== undefined && (session.ended_at === null || session.ended_at === undefined) && info.activeSession === null) {
      info.activeSession = session;
    }
  }
  return infos;
}

export async function renderMachines(root: HTMLElement, ctx: MachinesContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML =
      `<div class="machines">${dsPageHeader("Machines", "Environnements enregistrés sur lesquels le travail s'exécute.")}` +
      `${dsEmptyState("Connexion requise", "Définissez un jeton pour voir les machines visibles pour ce jeton.")}</div>`;
    return;
  }
  root.innerHTML = machinesLoadingHtml();

  const token = getToken();
  const [agents, sessions, events, canonical, runtimes] = await Promise.all([
    settle(fetchAgents(ctx.client)),
    settle(fetchSessions(ctx.client)),
    settle(fetchEvents(ctx.client)),
    token === null
      ? Promise.resolve({ ok: true as const, value: null as Machine[] | null })
      : settle(fetchCanonicalMachines(ctx.baseUrl, token)),
    settle(listRuntimes(ctx.client)),
  ]);

  const now = Date.now();
  const rows = buildMachineRows({
    machines: canonical.ok ? canonical.value : null,
    agents: agents.ok ? agents.value : [],
    sessions: sessions.ok ? sessions.value : [],
    events: events.ok ? events.value : [],
    now,
  });

  const problems: string[] = [];
  if (!agents.ok) problems.push(`agents indisponibles (${describeError(agents.error)})`);
  if (!sessions.ok) problems.push(`sessions indisponibles (${describeError(sessions.error)})`);
  if (!events.ok) problems.push(`événements indisponibles (${describeError(events.error)})`);
  if (!runtimes.ok) problems.push(`runtimes indisponibles (${describeError(runtimes.error)})`);
  if (!canonical.ok) problems.push(`lecture canonique indisponible (${describeError(canonical.error)})`);

  if (rows.length === 0 && problems.length > 0) {
    root.innerHTML =
      `<div class="machines">${dsPageHeader("Machines", "Environnements enregistrés sur lesquels le travail s'exécute.", [{ label: "Actualiser", id: "machines-reload" }])}` +
      `<div class="state error" role="alert">Impossible de charger les machines : ${esc(problems.join(" · "))}</div></div>`;
    root.querySelector("#machines-reload")?.addEventListener("click", () => {
      void renderMachines(root, ctx);
    });
    return;
  }

  const data: MachinesPageData = {
    rows,
    agents: agents.ok ? agents.value : [],
    sessions: sessions.ok ? sessions.value : [],
    runtimes: runtimes.ok ? runtimes.value : [],
    state: initialMachinesState(),
    canonicalAvailable: canonical.ok && canonical.value !== null,
    problems,
    now,
  };
  root.innerHTML = machinesPageHtml(data);
  bindMachines(root, ctx, data);
}

function refreshList(root: HTMLElement, data: MachinesPageData): void {
  const list = root.querySelector("#machines-list");
  if (list === null) return;
  const infos = cardInfos(data.rows, data.agents, data.sessions);
  const visible = filterMachineRows(data.rows, data.state);
  if (data.rows.length === 0) list.innerHTML = machinesEmptyHtml();
  else if (visible.length === 0) list.innerHTML = machinesNoMatchHtml();
  else list.innerHTML = machinesListHtml(visible, infos, data.now);
  const toolbar = root.querySelector(".machines-toolbar");
  if (toolbar !== null) {
    const fresh = document.createElement("div");
    fresh.innerHTML = machinesToolbarHtml(data.state, visible.length, data.rows.length);
    toolbar.replaceWith(...fresh.childNodes);
    bindToolbar(root, data);
  }
  bindDetails(root, data);
}

function bindToolbar(root: HTMLElement, data: MachinesPageData): void {
  const search = root.querySelector<HTMLInputElement>("#machines-search");
  search?.addEventListener("input", () => {
    data.state.query = search.value;
    refreshList(root, data);
    const again = root.querySelector<HTMLInputElement>("#machines-search");
    if (again !== null) {
      again.focus();
      again.setSelectionRange(again.value.length, again.value.length);
    }
  });
  const activity = root.querySelector<HTMLSelectElement>("#machines-activity");
  activity?.addEventListener("change", () => {
    data.state.activity = (activity.value as MachineActivityFilter) ?? "all";
    refreshList(root, data);
  });
  root.querySelector("[data-reset]")?.addEventListener("click", () => {
    data.state = initialMachinesState();
    refreshList(root, data);
  });
}

function bindDetails(root: HTMLElement, data: MachinesPageData): void {
  root.querySelectorAll<HTMLElement>("[data-machine-details]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.getAttribute("data-machine-details") ?? "";
      const row = data.rows.find((candidate) => candidate.machineId === id);
      if (row === undefined) return;
      const body = root.querySelector("#machine-drawer-body");
      if (body !== null) {
        body.innerHTML = machineDrawerBodyHtml(
          row,
          data.agents.filter((agent) => agent.machine_id === id),
          data.sessions.filter((session) => session.machine_id === id),
          data.runtimes,
          data.now,
        );
      }
      openDsDialog(root, "machine-drawer", button);
    });
  });
}

function bindMachines(root: HTMLElement, ctx: MachinesContext, data: MachinesPageData): void {
  root.querySelector("#machines-reload")?.addEventListener("click", () => {
    void renderMachines(root, ctx);
  });
  bindToolbar(root, data);
  bindDetails(root, data);
}

async function fetchEvents(client: StudioClient): Promise<EventEnvelope[]> {
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const result = await client.GET("/api/v1/events", { params: { query: { limit: 200, since } } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

/** Types d'événements qui justifient le re-rendu temps réel du shell. */
export { MACHINE_PRESENCE_EVENT_TYPES };
