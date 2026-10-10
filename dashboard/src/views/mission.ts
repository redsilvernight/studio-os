/**
 * Mission Control — onglet Exécutions et section de la vue d'ensemble
 * (P02-mission-ui, contrat DOM : docs/mission-control/ui.md).
 *
 * - Source unique : GET /api/v1/projects/{project_id}/mission. Le verdict
 *   serveur est affiché tel quel, jamais re-dérivé ; verdict, raison, état
 *   de protocole ou lacune inconnus → « inconnu » + code brut, ton neutre.
 * - Lecture seule : aucune action de mutation (lancer, annuler, valider).
 * - Un run = un <details> : lancement → session → résultat, lien vers la
 *   tâche. Aucun UUID visible hors dsTechDetails repliés.
 * - Temps réel : le shell re-rend la vue sur SSE. En `lost`, bandeau +
 *   rafraîchissement automatique borné (30 s, 10 essais) puis arrêt annoncé ;
 *   arrêt immédiat si la vue est détachée ou si le direct revient.
 */
import type { StudioClient } from "../api";
import { ApiError } from "../api";
import { dsBadge, dsErrorState, dsSectionHeader, dsSkeleton, dsStateHtml, dsTechDetails, type DsTechRow, type DsTone } from "../ds/ds";
import { fetchProjectMission, type MissionRun, type ProjectMission } from "../missionApi";
import { describeError, esc, fmtTime } from "../ui";
import { ACTION_LABEL, FALLBACK_LABEL } from "../language";

export type LiveState = "live" | "lost" | "off";

export interface MissionViewContext {
  client: StudioClient;
  projectId: string;
  authed: boolean;
  /** État du flux SSE du shell ; absent = considéré `off`. */
  live?: () => LiveState;
  /** Délai entre deux rafraîchissements automatiques en `lost` (défaut 30 s). */
  pollMs?: number;
  /** Nombre maximal de rafraîchissements automatiques (défaut 10). */
  maxPolls?: number;
}

export const MISSION_POLL_MS = 30_000;
export const MISSION_MAX_POLLS = 10;
/** Verdicts mis en avant dans la vue d'ensemble, dans cet ordre de priorité. */
export const MISSION_ATTENTION_VERDICTS = ["waiting_human", "needs_attention", "stale", "failed"] as const;
export const MISSION_SUMMARY_MAX = 3;

const VERDICT_LABEL: Record<string, string> = {
  pending: "En attente",
  running: "En cours",
  waiting_human: "Attend une personne",
  needs_attention: "À vérifier",
  stale: "Sans nouvelles",
  done: "Terminée",
  failed: "Échouée",
  cancelled: "Annulée",
};

const VERDICT_TONE: Record<string, DsTone> = {
  pending: "neutral",
  running: "info",
  waiting_human: "warning",
  needs_attention: "warning",
  stale: "warning",
  done: "success",
  failed: "danger",
  cancelled: "neutral",
};

const REASON_LABEL: Record<string, string> = {
  launch_cancelled: "Lancement annulé",
  launch_failed: "Lancement échoué",
  launch_rejected: "Lancement refusé",
  launch_expired: "Lancement expiré",
  review_requested: "Relecture demandée",
  decision_proposed: "Décision proposée en attente",
  handed_off: "Résultat transmis",
  process_exited_without_session: "Processus terminé sans session",
  session_ended_without_handoff: "Session terminée sans résultat transmis",
  process_exited_session_open: "Processus terminé, session encore ouverte",
  session_expired: "Session expirée",
  machine_offline: "Poste hors ligne",
  launch_pending: "Lancement en préparation",
  process_running: "Processus en cours",
  session_idle: "Session inactive",
};

const PROTOCOL_LABEL: Record<string, string> = {
  open: "Session ouverte",
  handed_off: "Résultat transmis",
  ended_without_handoff: "Session terminée sans résultat transmis",
  missing: "Aucune session",
};

const GAP_LABEL: Record<string, string> = {
  machine_unknown: "poste inconnu",
  session_not_found: "session introuvable",
  task_not_found: "tâche introuvable",
};

const LAUNCH_STATUS_LABEL: Record<string, string> = {
  requested: "demandé",
  accepted: "accepté",
  preparing: "en préparation",
  running: "en cours",
  succeeded: "processus terminé",
  failed: "échoué",
  cancelled: "annulé",
  rejected: "refusé",
  expired: "expiré",
};

const SESSION_STATUS_LABEL: Record<string, string> = {
  active: "active",
  idle: "inactive",
  expired: "expirée",
  ended: "terminée",
};

const MACHINE_STATUS_LABEL: Record<string, string> = {
  online: "en ligne",
  idle: "inactif",
  offline: "hors ligne",
};

/** Libellé connu, sinon « inconnu » + code brut (vocabulaires additifs). */
function labelOf(map: Record<string, string>, code: string): string {
  return Object.prototype.hasOwnProperty.call(map, code) ? (map[code] as string) : `inconnu (${code})`;
}

export function verdictLabel(verdict: string): string {
  return labelOf(VERDICT_LABEL, verdict);
}

export function verdictTone(verdict: string): DsTone {
  return Object.prototype.hasOwnProperty.call(VERDICT_TONE, verdict) ? (VERDICT_TONE[verdict] as DsTone) : "neutral";
}

export function reasonLabel(reason: string): string {
  return labelOf(REASON_LABEL, reason);
}

export function protocolLabel(state: string): string {
  return labelOf(PROTOCOL_LABEL, state);
}

function gapHtml(gap: string): string {
  return `<p class="ds-list-sub" data-mission-gap="${esc(gap)}">Donnée manquante : ${esc(labelOf(GAP_LABEL, gap))}</p>`;
}

function launchStepHtml(run: MissionRun): string {
  const launch = run.launch;
  if (launch === null || launch === undefined) {
    const text = run.source === "session" ? "Aucun lancement distant (session ouverte à la main)" : "Aucun lancement";
    return `<li><strong>Lancement</strong> · ${esc(text)}</li>`;
  }
  const finished = launch.finished_at ? ` · fin ${fmtTime(launch.finished_at)}` : "";
  return (
    `<li><strong>Lancement</strong> · ${esc(labelOf(LAUNCH_STATUS_LABEL, launch.status))} · ${esc(launch.harness_id)}` +
    ` · demandé ${fmtTime(launch.created_at)}${finished}</li>`
  );
}

function sessionStepHtml(run: MissionRun, gaps: string[]): string {
  const session = run.session;
  if (session === null || session === undefined) {
    const body = gaps.includes("session_not_found") ? "" : " · Aucune session";
    return `<li><strong>Session</strong>${body}${gaps.includes("session_not_found") ? gapHtml("session_not_found") : ""}</li>`;
  }
  const ended = session.ended_at ? ` · fin ${fmtTime(session.ended_at)}` : "";
  const activity = !session.ended_at && session.last_activity_at ? ` · dernière activité ${fmtTime(session.last_activity_at)}` : "";
  return (
    `<li><strong>Session</strong> · ${esc(labelOf(SESSION_STATUS_LABEL, session.status))}` +
    ` · début ${fmtTime(session.started_at)}${ended}${activity}</li>`
  );
}

function resultStepHtml(run: MissionRun): string {
  const handoff = run.handoff;
  const body =
    handoff === null || handoff === undefined
      ? `<p class="ds-list-sub">Aucun résultat transmis</p>`
      : `<p>${esc(handoff.summary)}</p>${handoff.completed_at ? `<p class="ds-list-sub">Transmis ${fmtTime(handoff.completed_at)}</p>` : ""}`;
  return `<li data-mission-result><strong>Résultat</strong> · ${esc(protocolLabel(run.protocol_state))}${body}</li>`;
}

function techRows(run: MissionRun): DsTechRow[] {
  const rows: DsTechRow[] = [
    { label: "Exécution", value: run.run_id, mono: true },
    { label: "Tâche", value: run.task_id, mono: true },
    { label: "Poste", value: run.machine_id, mono: true },
  ];
  if (run.launch) rows.push({ label: "Lancement", value: run.launch.id, mono: true });
  if (run.session) rows.push({ label: "Session", value: run.session.id, mono: true });
  if (run.handoff) rows.push({ label: "Travail IA", value: run.handoff.ai_work_id, mono: true });
  rows.push({ label: "Verdict (code)", value: run.verdict, mono: true });
  if (run.reasons.length > 0) rows.push({ label: "Raisons (codes)", value: run.reasons.join(", "), mono: true });
  return rows;
}

/** Un run : <details> fermé, résumé (verdict, tâche, raison, mise à jour) puis détail. */
export function missionRunHtml(run: MissionRun): string {
  const gaps: string[] = run.data_gaps ?? [];
  const reason = run.reasons[0];
  const title =
    run.task_title !== null && run.task_title !== undefined && run.task_title !== ""
      ? esc(run.task_title)
      : gaps.includes("task_not_found")
        ? `<span data-mission-gap="task_not_found">Donnée manquante : tâche introuvable</span>`
        : esc(FALLBACK_LABEL.task);
  const otherReasons = run.reasons.slice(1);
  const others =
    otherReasons.length === 0
      ? ""
      : `<p class="ds-list-sub">Autres raisons : ${otherReasons.map((r) => esc(reasonLabel(r))).join(" · ")}</p>`;
  const machine = gaps.includes("machine_unknown")
    ? gapHtml("machine_unknown")
    : run.machine_status
      ? `<p class="ds-list-sub">Poste ${esc(labelOf(MACHINE_STATUS_LABEL, run.machine_status))}</p>`
      : "";
  const claims = run.active_claims > 0 ? `<p class="ds-list-sub">${run.active_claims} réservation(s) active(s)</p>` : "";
  // Lacunes non rattachées à une étape (vocabulaire additif) : mention générique.
  const extraGaps = gaps.filter((g) => !["machine_unknown", "session_not_found", "task_not_found"].includes(g)).map(gapHtml).join("");
  return (
    `<details class="ds-panel mission-run" data-mission-run="${esc(run.run_id)}" data-verdict="${esc(run.verdict)}">` +
    `<summary>${dsBadge(verdictLabel(run.verdict), verdictTone(run.verdict))} <strong>${title}</strong>` +
    `${reason !== undefined ? ` · <span>${esc(reasonLabel(reason))}</span>` : ""}` +
    ` · <span class="ds-list-sub">mis à jour ${fmtTime(run.updated_at)}</span></summary>` +
    `<div class="body"><ol class="mission-steps">${launchStepHtml(run)}${sessionStepHtml(run, gaps)}${resultStepHtml(run)}</ol>` +
    `${others}${machine}${claims}${extraGaps}` +
    `<p><a href="#/tasks/${esc(run.task_id)}">${esc(ACTION_LABEL.openTask)}</a></p>` +
    `${dsTechDetails(techRows(run))}</div></details>`
  );
}

/** Compteurs par verdict sur toute la fenêtre (`counts`), jamais recomptés sur la page. */
export function missionCountsHtml(mission: ProjectMission): string {
  const byVerdict = mission.counts.by_verdict;
  const known = Object.keys(VERDICT_LABEL).filter((v) => (byVerdict[v] ?? 0) > 0);
  const unknown = Object.keys(byVerdict).filter((v) => !(v in VERDICT_LABEL) && (byVerdict[v] ?? 0) > 0);
  const items = [...known, ...unknown]
    .map((v) => `<li data-count-verdict="${esc(v)}">${dsBadge(`${verdictLabel(v)} : ${byVerdict[v] ?? 0}`, verdictTone(v))}</li>`)
    .join("");
  return (
    `<div data-mission-counts><p><strong>${mission.counts.total}</strong> exécution(s) sur ${mission.window_hours} h` +
    `${mission.truncated ? " (fenêtre tronquée)" : ""}</p>${items === "" ? "" : `<ul class="mission-counts">${items}</ul>`}</div>`
  );
}

function refreshButtonHtml(): string {
  return `<button type="button" class="ds-btn ds-btn--sm" data-mission-refresh>Actualiser</button>`;
}

function lostBannerHtml(generatedAt: string | null, polls: number, maxPolls: number, pollMs: number): string {
  const when = generatedAt === null ? "" : ` Données du ${fmtTime(generatedAt)}.`;
  const auto =
    polls >= maxPolls
      ? `<span data-mission-poll-stopped>Rafraîchissement automatique arrêté après ${maxPolls} essai(s) : utilisez Actualiser.</span>`
      : `<span>Rafraîchissement automatique toutes les ${Math.round(pollMs / 1000)} s (${polls}/${maxPolls}).</span>`;
  return (
    `<div class="ds-notice ds-notice--warning" role="status" data-mission-live="lost">` +
    `<strong>Mises à jour en direct interrompues.</strong>${when} ${auto} ${refreshButtonHtml()}</div>`
  );
}

function panelHtml(body: string): string {
  return `<section class="ds-panel" data-mission aria-label="Exécutions"><header><h2>Exécutions</h2></header><div class="body">${body}</div></section>`;
}

function deniedHtml(): string {
  return `<div data-mission-denied>${dsStateHtml("empty", {
    title: "Accès refusé",
    message: "Votre compte n'a pas accès aux exécutions de ce projet.",
  })}</div>`;
}

function isDenied(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

/** Génération de rendu par racine : un rendu plus récent invalide les minuteries du précédent. */
const renderGenerations = new WeakMap<HTMLElement, number>();

export async function renderMissionInto(root: HTMLElement, ctx: MissionViewContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = panelHtml(
      dsStateHtml("empty", {
        title: "Connectez-vous pour voir les exécutions",
        message: "Saisissez votre jeton machine pour charger les exécutions du projet.",
      }),
    );
    return;
  }
  const generation = (renderGenerations.get(root) ?? 0) + 1;
  renderGenerations.set(root, generation);
  const current = (): boolean => renderGenerations.get(root) === generation && root.isConnected;
  const live = (): LiveState => ctx.live?.() ?? "off";
  const pollMs = ctx.pollMs ?? MISSION_POLL_MS;
  const maxPolls = ctx.maxPolls ?? MISSION_MAX_POLLS;
  let polls = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let runs: MissionRun[] = [];
  let mission: ProjectMission | null = null;

  root.innerHTML = panelHtml(dsSkeleton(4));

  const schedule = (): void => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    if (!current() || live() !== "lost" || polls >= maxPolls) return;
    timer = setTimeout(() => {
      timer = null;
      if (!current() || live() !== "lost") return;
      polls += 1;
      void load();
    }, pollMs);
  };

  const bindRefresh = (): void => {
    root.querySelectorAll<HTMLButtonElement>("[data-mission-refresh]").forEach((button) =>
      button.addEventListener("click", () => {
        button.disabled = true;
        polls = 0;
        void load();
      }),
    );
  };

  const paint = (): void => {
    if (mission === null) return;
    const banner = live() === "lost" ? lostBannerHtml(mission.generated_at, polls, maxPolls, pollMs) : "";
    const list =
      runs.length === 0
        ? dsStateHtml("empty", { title: "Aucune exécution", message: "Aucune exécution sur la fenêtre affichée." })
        : `<div class="mission-runs">${runs.map(missionRunHtml).join("")}</div>`;
    const more = mission.next_cursor
      ? `<button type="button" class="ds-btn" data-mission-more>Charger plus</button>`
      : "";
    root.innerHTML = panelHtml(
      `${banner}<p class="ds-list-sub">Lecture seule · données du ${fmtTime(mission.generated_at)}</p>` +
        `${missionCountsHtml(mission)}${list}${more}<div data-mission-msg class="ds-list-sub" role="status"></div>`,
    );
    bindRefresh();
    root.querySelector<HTMLButtonElement>("[data-mission-more]")?.addEventListener("click", (event) => {
      const button = event.currentTarget as HTMLButtonElement;
      const cursor = mission?.next_cursor;
      if (!cursor) return;
      button.disabled = true;
      fetchProjectMission(ctx.client, ctx.projectId, { cursor })
        .then((next) => {
          if (!current()) return;
          runs = [...runs, ...next.runs];
          // Les compteurs restent ceux de la fenêtre ; seule la pagination avance.
          mission = { ...next, runs };
          paint();
        })
        .catch((error: unknown) => {
          button.disabled = false;
          const msg = root.querySelector("[data-mission-msg]");
          if (msg !== null) msg.textContent = describeError(error);
        });
    });
  };

  const load = async (): Promise<void> => {
    try {
      const fresh = await fetchProjectMission(ctx.client, ctx.projectId);
      if (!current()) return;
      mission = fresh;
      runs = [...fresh.runs];
      paint();
    } catch (error) {
      if (!current()) return;
      if (isDenied(error)) {
        // 403 final : aucun nouvel essai, aucun détail d'un autre projet.
        root.innerHTML = panelHtml(deniedHtml());
        return;
      }
      const banner = live() === "lost" ? lostBannerHtml(mission?.generated_at ?? null, polls, maxPolls, pollMs) : "";
      root.innerHTML = panelHtml(
        banner + dsErrorState("Exécutions indisponibles", describeError(error)) + (banner === "" ? refreshButtonHtml() : ""),
      );
      bindRefresh();
    }
    schedule();
  };

  await load();
}

/** Runs à regarder pour la vue d'ensemble : verdicts d'attention, ordre de priorité, au plus 3. */
export function attentionRuns(runs: MissionRun[], max = MISSION_SUMMARY_MAX): MissionRun[] {
  const rank = (v: string): number => (MISSION_ATTENTION_VERDICTS as readonly string[]).indexOf(v);
  return runs
    .filter((r) => rank(r.verdict) >= 0)
    .sort((a, b) => rank(a.verdict) - rank(b.verdict))
    .slice(0, max);
}

function summaryHtml(projectId: string, body: string): string {
  return (
    `<section data-mission-summary aria-label="Exécutions">` +
    dsSectionHeader("Exécutions", { label: "Voir les exécutions", href: `#/projects/${projectId}/mission` }) +
    `${body}</section>`
  );
}

export async function renderMissionSummaryInto(root: HTMLElement, ctx: MissionViewContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = "";
    return;
  }
  root.innerHTML = summaryHtml(ctx.projectId, dsSkeleton(2));
  try {
    const mission = await fetchProjectMission(ctx.client, ctx.projectId);
    const watch = attentionRuns(mission.runs);
    const list =
      watch.length === 0
        ? `<p class="ds-list-sub">Aucune exécution n'attend d'attention.</p>`
        : `<div class="mission-runs">${watch.map(missionRunHtml).join("")}</div>`;
    root.innerHTML = summaryHtml(ctx.projectId, missionCountsHtml(mission) + list);
  } catch (error) {
    root.innerHTML = summaryHtml(
      ctx.projectId,
      isDenied(error)
        ? deniedHtml()
        : `<div class="ds-notice ds-notice--danger" role="alert"><strong>Exécutions indisponibles.</strong> ${esc(describeError(error))}</div>`,
    );
  }
}
