/**
 * UI-8 — Decisions & Review : surface unifiée pour ce qui demande une action
 * (boîte de réception « À valider ») et l'historique des décisions durables.
 *
 * Deux onglets distincts :
 *   - "À valider" : boîte de réception de la file d'attente agrégée
 *     (ai_work_review, decision_proposal, roadmap_proposal, resource_conflict,
 *     build_failure, pr_ready). Les six types partagent UNE structure de carte :
 *     libellé humain, point de couleur, une ligne de contexte, un impact. Un
 *     objet n'apparaît qu'une fois (proposition + révisions d'un même plan
 *     regroupées sur une carte « Révision N du plan »), au plus deux actions par
 *     carte, et rien de technique visible par défaut (C2) : type brut, commit,
 *     branches et identifiants restent dans « Détails techniques » repliés.
 *     Filtres Tous / À décider / Signaux, tri requested_at décroissant.
 *   - "Décisions" : liste des décisions enregistrées (proposed/accepted/
 *     superseded) avec création en modale (POST /decisions + Idempotency-Key).
 *
 * Liens vers Agents (#/agents/<id>), Tâches (#/tasks/<id>), Projets
 * (#/projects/<id>) et Roadmap quand les IDs sont fiables. Aucun bouton
 * générique : ce qui ne se résout pas ici affiche ses liens de navigation et
 * le dit (« non résoluble ici »).
 *
 * Reprend la route globale #/decisions. La vue projet-scopée (#/projects/<id>/decisions)
 * réutilise le même renderer via un context projectId.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { getToken } from "../auth";
import { decodeJwtSubject, isUuid } from "../creationsApi";
import { isAdminIdentity } from "../identityApi";
import {
  dsBadge,
  dsEmptyState,
  dsPageHeader,
  dsSectionHeader,
  dsSkeleton,
  dsTabsHtml,
  dsModalHtml,
  dsField,
  dsTechDetails,
  focusDsErrorBox,
  initDsTabs,
  openDsDialog,
  closeDsDialog,
  dsNotify,
  dsAgentBadge,
  type DsTechRow,
} from "../ds/ds";
import { resolveReview, type ReviewResolution } from "../reviewApi";
import { agentLabel, projectLabel } from "../actorNames";
import { describeError, esc, fmtTime, newUuid } from "../ui";
import { ACTION_LABEL, FALLBACK_LABEL, REVIEW_KIND_LABEL as REVIEW_KIND_LABEL_SOURCE } from "../language";
import type { components } from "../openapi-schema";

type Decision = components["schemas"]["Decision"];
type DecisionCreate = components["schemas"]["DecisionCreate"];
type ReviewQueue = components["schemas"]["ReviewQueue"];
type ReviewQueueItem = ReviewQueue["items"][number];

export type { Decision, DecisionCreate, ReviewQueue, ReviewQueueItem };

export interface DecisionsContext {
  client: StudioClient;
  authed: boolean;
  projectId?: string;
}

export const REVIEW_KIND_LABEL: Record<ReviewQueueItem["kind"], string> = REVIEW_KIND_LABEL_SOURCE;

export const REVIEW_KIND_TONE: Record<ReviewQueueItem["kind"], "neutral" | "info" | "warning" | "danger" | "ai"> = {
  ai_work_review: "ai",
  decision_proposal: "info",
  resource_conflict: "warning",
  build_failure: "danger",
  pr_ready: "info",
  roadmap_proposal: "warning",
};

export const DECISION_STATUS_LABEL: Record<string, string> = {
  proposed: "Proposée",
  accepted: "Acceptée",
  superseded: "Remplacée",
};

export const DECISION_STATUS_TONE: Record<string, "neutral" | "info" | "warning" | "success" | "danger"> = {
  proposed: "info",
  accepted: "success",
  superseded: "warning",
};

export const PROPOSER_TYPE_LABEL: Record<string, string> = {
  user: "Utilisateur",
  agent: "Agent",
  system: "Système",
};

/** Détail lisible selon le kind (agent, readable_id, resource_path, workflow+branch, PR#). */
export function reviewQueueItemDetail(item: ReviewQueueItem): string {
  switch (item.kind) {
    case "ai_work_review":
      return `Relire le travail de ${agentLabel(item.agent_id)}`;
    case "decision_proposal":
      return `${item.readable_id} · ${PROPOSER_TYPE_LABEL[item.proposed_by_type] ?? item.proposed_by_type}`;
    case "resource_conflict":
      return `sur ${item.resource_path}`;
    case "build_failure":
      return `${item.workflow_name} sur ${item.branch}`;
    case "pr_ready":
      return `PR #${item.pr_number} · ${item.head_branch} → ${item.base_branch}`;
    case "roadmap_proposal": {
      const revision = item.revision_no ?? null;
      if (revision === null) return `plan soumis pour validation · par ${item.actor_type}`;
      const base = item.base_revision_no ?? null;
      return base === null
        ? `révision ${revision} · par ${item.actor_type}`
        : `révision ${revision} sur base ${base} · par ${item.actor_type}`;
    }
  }
}

/** ------------------- FILE « À VALIDER » : modèle de carte ------------------- */

/** « decide » : la décision se prend ici. « signal » : informatif, navigation seulement. */
export type ReviewChannel = "decide" | "signal";

export const REVIEW_CHANNEL: Record<ReviewQueueItem["kind"], ReviewChannel> = {
  ai_work_review: "decide",
  decision_proposal: "decide",
  roadmap_proposal: "decide",
  resource_conflict: "signal",
  build_failure: "signal",
  pr_ready: "signal",
};

/** Un objet de la file, dédoublonné : les six kinds partagent cette structure. */
export interface ReviewCard {
  /** Type réel de la file : libellé humain + point de couleur. */
  kind: ReviewQueueItem["kind"];
  /** Clé d'objet — un plan = une carte, même avec proposition et révisions. */
  key: string;
  /** Entrée la plus récente du groupe : celle qui est décrite et actionnable. */
  item: ReviewQueueItem;
  /** Entrées de la file regroupées sur cette carte (1 hors dédoublonnage). */
  grouped: number;
  channel: ReviewChannel;
}

export type ReviewFilter = "all" | "decide" | "signal";

export const REVIEW_FILTERS: ReadonlyArray<{ id: ReviewFilter; label: string }> = [
  { id: "all", label: "Tous" },
  { id: "decide", label: "À décider" },
  { id: "signal", label: "À surveiller" },
];

/** Ce que la décision change, en une ligne, pour chaque type de la file. */
export const REVIEW_IMPACT: Record<ReviewQueueItem["kind"], string> = {
  ai_work_review: "Impact : approuver publie le travail dans la tâche liée ; demander des modifications le renvoie à l'agent.",
  decision_proposal: "Impact : la décision devient la référence du dossier, et reste remplaçable ensuite.",
  roadmap_proposal: "Impact : le plan attend une relecture ; aucune étape n'est modifiée avant approbation.",
  resource_conflict: "Impact : risque d'écrasement sur le fichier partagé. Signal de 24 h, aucun état à trancher.",
  build_failure: "Impact : la fusion reste bloquée tant que le build échoue. Aucun état de build à trancher ici.",
  pr_ready: "Impact : à relire avant fusion. Le signal disparaît à la fusion, rien à trancher ici.",
};

/** Où l'objet se résout réellement : honnête, jamais un bouton générique. */
export const REVIEW_RESOLUTION: Record<ReviewQueueItem["kind"], string> = {
  ai_work_review: "relecture du travail IA lié",
  decision_proposal: "transition admin (accepter / remplacer)",
  roadmap_proposal: "surface Roadmap, file en lecture seule",
  resource_conflict: "signal de 24 h, sans état persistant",
  build_failure: "aucune transition de build, signal seulement",
  pr_ready: "signal, disparaît à la fusion",
};

/** Clé d'objet : une roadmap = une carte, quelles que soient ses entrées regroupées. */
export function reviewCardKey(item: ReviewQueueItem): string {
  return item.kind === "roadmap_proposal"
    ? `roadmap:${item.project_id}:${item.roadmap_id}`
    : `${item.kind}:${item.id}`;
}

/** Plus récent d'abord (contrat), repli stable par identifiant si la date est illisible. */
export function sortReviewItems(items: readonly ReviewQueueItem[]): ReviewQueueItem[] {
  return [...items].sort((a, b) => {
    const left = Date.parse(a.requested_at);
    const right = Date.parse(b.requested_at);
    if (!Number.isNaN(left) && !Number.isNaN(right) && left !== right) return right - left;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
}

/**
 * File → cartes : un objet par carte (proposition et révisions d'un même plan
 * regroupées), triés du plus récent au plus ancien.
 */
export function buildReviewCards(queue: ReviewQueue | null): ReviewCard[] {
  const cards: ReviewCard[] = [];
  const index = new Map<string, number>();
  for (const item of sortReviewItems(queue?.items ?? [])) {
    const key = reviewCardKey(item);
    const at = index.get(key);
    if (at !== undefined) {
      const grouped = cards[at];
      if (grouped !== undefined) grouped.grouped += 1;
      continue;
    }
    index.set(key, cards.length);
    cards.push({ kind: item.kind, key, item, grouped: 1, channel: REVIEW_CHANNEL[item.kind] });
  }
  return cards;
}

export interface ReviewCounts {
  total: number;
  decide: number;
  signal: number;
  byKind: Partial<Record<ReviewQueueItem["kind"], number>>;
}

/** Compteurs réels : par type, et par canal (décider / signaux). */
export function reviewCounts(cards: readonly ReviewCard[]): ReviewCounts {
  const byKind: Partial<Record<ReviewQueueItem["kind"], number>> = {};
  let decide = 0;
  for (const card of cards) {
    byKind[card.kind] = (byKind[card.kind] ?? 0) + 1;
    if (card.channel === "decide") decide += 1;
  }
  return { total: cards.length, decide, signal: cards.length - decide, byKind };
}

/** Titre humain de la carte : le nom de l'objet, révision comprise. */
export function reviewCardTitle(card: ReviewCard): string {
  const item = card.item;
  if (item.kind !== "roadmap_proposal") return item.title;
  const revision = item.revision_no ?? null;
  if (item.scope === "revision" && revision !== null) return `Révision ${revision} du plan « ${item.title} »`;
  return `Proposition de plan « ${item.title} »`;
}

/** Une seule ligne de contexte : objet, provenance, moment. Jamais d'identifiant. */
function reviewCardContextHtml(card: ReviewCard): string {
  const item = card.item;
  const parts: string[] = [];
  if (card.channel === "decide" && item.project_id) {
    parts.push(`<a href="#/projects/${esc(item.project_id)}">${esc(projectLabel(item.project_id))}</a>`);
  }
  parts.push(esc(reviewQueueItemDetail(item)));
  if (card.grouped > 1) parts.push(esc(`${card.grouped} propositions regroupées`));
  if (card.channel === "decide" && item.task_id) {
    parts.push(`<a href="#/tasks/${esc(item.task_id)}">${esc(ACTION_LABEL.openTask)}</a>`);
  }
  parts.push(`<time datetime="${esc(item.requested_at)}">${fmtTime(item.requested_at)}</time>`);
  return parts.join(`<span class="review-sep" aria-hidden="true">·</span>`);
}

/** Action d'une carte : bouton de résolution ou lien de navigation, deux au plus. */
export interface ReviewAction {
  label: string;
  element: "button" | "link";
  /** Attribut rendu tel quel (`data-review-approve="…"` ou `href="…"`). */
  attribute: string;
  variant: "primary" | "secondary" | "ghost";
  disabled?: boolean;
}

/** Au plus deux actions : résoudre, ou naviguer vers la surface qui sait résoudre. */
export function reviewCardActions(card: ReviewCard, authed: boolean, isAdmin: boolean): ReviewAction[] {
  const item = card.item;
  switch (item.kind) {
    case "ai_work_review":
      return [
        { label: "Approuver", element: "button", attribute: `data-review-approve="${esc(item.id)}"`, variant: "primary", disabled: !authed },
        { label: "Demander des modifications", element: "button", attribute: `data-review-changes="${esc(item.id)}"`, variant: "secondary", disabled: !authed },
      ];
    case "decision_proposal": {
      const allowed = authed && isAdmin;
      return [
        { label: "Accepter", element: "button", attribute: `data-decision-accept="${esc(item.id)}"`, variant: "primary", disabled: !allowed },
        { label: "Remplacer", element: "button", attribute: `data-decision-supersede="${esc(item.id)}"`, variant: "secondary", disabled: !allowed },
      ];
    }
    case "roadmap_proposal": {
      const revision = item.revision_no ?? null;
      return [
        {
          label: revision === null ? "Relire le plan" : `Relire la révision ${revision}`,
          element: "link",
          attribute: `href="#/projects/${esc(item.project_id)}/roadmap/${esc(item.roadmap_id)}"`,
          variant: "primary",
        },
        {
          label: "Ouvrir le plan",
          element: "link",
          attribute: `href="#/projects/${esc(item.project_id)}/roadmap"`,
          variant: "ghost",
        },
      ];
    }
    default: {
      // Signaux : aucune transition n'existe. On offre les deux sorties
      // possibles (le projet, la tâche liée) et la carte le dit.
      const links: ReviewAction[] = [];
      if (item.project_id) {
        links.push({ label: ACTION_LABEL.openProject, element: "link", attribute: `href="#/projects/${esc(item.project_id)}"`, variant: "secondary" });
      }
      if (item.task_id) {
        links.push({ label: ACTION_LABEL.openTask, element: "link", attribute: `href="#/tasks/${esc(item.task_id)}"`, variant: "ghost" });
      }
      return links;
    }
  }
}

/** Rendu des actions : boutons ou liens, la première en primaire. */
function reviewActionsHtml(actions: readonly ReviewAction[], small: boolean): string {
  return actions
    .map((action) => {
      const size = small ? " ds-btn--sm" : "";
      const cls = action.variant === "primary" ? `ds-btn${size} ds-btn--primary` : action.variant === "ghost" ? `ds-btn${size} ds-btn--ghost` : `ds-btn${size}`;
      if (action.element === "link") return `<a class="${cls}" ${action.attribute}>${esc(action.label)}</a>`;
      const disabled = action.disabled === true ? " disabled" : "";
      return `<button class="${cls}" type="button" ${action.attribute}${disabled}>${esc(action.label)}</button>`;
    })
    .join("");
}

/** Ce que la carte ne peut pas faire ici — honnêteté affichée, pas de silence. */
function reviewCardNoteHtml(card: ReviewCard, isAdmin: boolean): string {
  if (card.channel === "signal") {
    return `<p class="review-card-note">À traiter ailleurs : le projet ou la tâche liée indique où.</p>`;
  }
  if (card.kind === "decision_proposal" && !isAdmin) {
    return `<p class="review-card-note">Réservé au rôle admin.</p>`;
  }
  if (card.kind === "roadmap_proposal") {
    return `<p class="review-card-note">Se tranche sur la roadmap, pas dans cette file.</p>`;
  }
  return "";
}

/** Type brut, identifiants, commit, branches : repliés (C2). */
export function reviewCardTechRows(card: ReviewCard): DsTechRow[] {
  const item = card.item;
  const rows: DsTechRow[] = [
    { label: "Type", value: item.kind },
    { label: "Identifiant", value: item.id, mono: true },
    { label: "Résolution", value: REVIEW_RESOLUTION[card.kind] },
  ];
  if (item.project_id) rows.push({ label: "Projet", value: item.project_id, mono: true });
  if (item.task_id) rows.push({ label: "Tâche", value: item.task_id, mono: true });
  switch (item.kind) {
    case "ai_work_review":
      rows.push({ label: "Agent", value: item.agent_id, mono: true });
      break;
    case "decision_proposal":
      rows.push({ label: "Décision", value: item.readable_id, mono: true });
      rows.push({ label: "Proposé par", value: item.proposed_by_type });
      break;
    case "roadmap_proposal":
      rows.push({ label: "Roadmap", value: item.roadmap_id, mono: true });
      rows.push({ label: "Portée", value: item.scope });
      rows.push({ label: "Révision", value: String(item.revision_no ?? "—") });
      rows.push({ label: "Version de base", value: String(item.base_revision_no ?? "—") });
      rows.push({ label: "Statut", value: item.status });
      rows.push({ label: "Entrées regroupées", value: String(card.grouped) });
      if (item.summary) rows.push({ label: "Résumé", value: item.summary });
      break;
    case "resource_conflict":
      rows.push({ label: "Ressource", value: item.resource_path, mono: true });
      break;
    case "build_failure":
      rows.push({ label: "Workflow", value: item.workflow_name });
      rows.push({ label: "Branche", value: item.branch, mono: true });
      rows.push({ label: "Commit", value: item.commit_sha, mono: true });
      if (item.conclusion) rows.push({ label: "Conclusion", value: item.conclusion });
      break;
    case "pr_ready":
      rows.push({ label: "PR", value: `#${item.pr_number}` });
      rows.push({ label: "Branche source", value: item.head_branch, mono: true });
      rows.push({ label: "Branche cible", value: item.base_branch, mono: true });
      break;
  }
  rows.push({ label: "Demandé le", value: fmtTime(item.requested_at) });
  return rows;
}

/** Carte d'inbox : structure identique pour les six types de la file. */
export function reviewCardHtml(card: ReviewCard, authed: boolean, isAdmin: boolean): string {
  const item = card.item;
  const tone = REVIEW_KIND_TONE[card.kind];
  return `<li class="ds-card review-card" data-kind="${esc(card.kind)}" data-id="${esc(item.id)}" data-channel="${card.channel}">` +
    `<div class="review-card-top">` +
    `<span class="review-card-dot" data-tone="${esc(tone)}" aria-hidden="true"></span>` +
    `<div class="grow">` +
    `<div class="review-card-head">${dsBadge(REVIEW_KIND_LABEL[card.kind], tone)}` +
    `<h3 class="review-card-title">${esc(reviewCardTitle(card))}</h3></div>` +
    `<p class="review-card-context">${reviewCardContextHtml(card)}</p>` +
    `<p class="review-card-impact">${esc(REVIEW_IMPACT[card.kind])}</p>` +
    `</div></div>` +
    `<div class="review-card-actions" role="group" aria-label="Actions pour ${esc(REVIEW_KIND_LABEL[card.kind])}">${reviewActionsHtml(reviewCardActions(card, authed, isAdmin), true)}</div>` +
    reviewCardNoteHtml(card, isAdmin) +
    dsTechDetails(reviewCardTechRows(card), "Détails techniques") +
    `</li>`;
}

/** Titre d'action du héros : ce qu'il faut faire, pas le type technique. */
export function reviewHeroTitle(card: ReviewCard): string {
  const item = card.item;
  switch (item.kind) {
    case "ai_work_review":
      return `Relire « ${item.title} »`;
    case "decision_proposal":
      return `Trancher ${item.readable_id}`;
    case "roadmap_proposal": {
      const revision = item.revision_no ?? null;
      if (item.scope === "revision" && revision !== null) return `Approuver la révision ${revision} du plan`;
      return `Approuver « ${item.title} »`;
    }
    default:
      return `Examiner « ${item.title} »`;
  }
}

/**
 * Héros : la prochaine action, avec UNE action primaire (C1). Composé ici
 * plutôt qu'avec dsHeroCard, dont l'action primaire est obligatoirement un lien
 * alors que la résolution d'un travail IA ou d'une décision est un bouton.
 * L'objet promu est retiré de la file : un objet n'apparaît qu'une fois.
 */
export function reviewHeroHtml(card: ReviewCard, authed: boolean, isAdmin: boolean): string {
  const primary = reviewCardActions(card, authed, isAdmin)[0];
  const revision = card.item.kind === "roadmap_proposal" ? (card.item.revision_no ?? null) : null;
  const eyebrow = revision === null
    ? REVIEW_KIND_LABEL[card.kind]
    : `${REVIEW_KIND_LABEL[card.kind]} · révision ${revision}`;
  return `<section class="ds-hero review-hero" aria-labelledby="review-hero-title">` +
    `<p class="ds-hero-eyebrow">${esc(eyebrow)}</p>` +
    `<h2 id="review-hero-title">${esc(reviewHeroTitle(card))}</h2>` +
    `<p class="ds-hero-body">${esc(REVIEW_IMPACT[card.kind])}</p>` +
    (primary === undefined ? "" : `<div class="ds-hero-actions">${reviewActionsHtml([primary], false)}</div>`) +
    `</section>`;
}

/** Filtres Tous / À décider / Signaux, avec le compte réel de chaque vue. */
export function reviewFiltersHtml(
  cards: readonly ReviewCard[],
  filter: ReviewFilter,
  seeAll?: { label: string; href: string },
): string {
  const counts = reviewCounts(cards);
  const count = (id: ReviewFilter): number => (id === "all" ? counts.total : id === "decide" ? counts.decide : counts.signal);
  const buttons = REVIEW_FILTERS
    .map((item) => {
      const active = item.id === filter;
      const cls = active ? "ds-btn ds-btn--primary" : "ds-btn";
      return `<button class="${cls}" type="button" data-review-filter="${esc(item.id)}" aria-pressed="${active ? "true" : "false"}">${esc(item.label)} <span class="review-filter-count">${count(item.id)}</span></button>`;
    })
    .join("");
  const link = seeAll === undefined ? "" : `<a class="review-see-all" href="${esc(seeAll.href)}">${esc(seeAll.label)}</a>`;
  return `<div class="review-toolbar"><div class="review-filters" role="group" aria-label="Filtrer la file À valider">${buttons}</div>${link}</div>`;
}

/** Charge la review queue (global ou project-scopé). */
async function fetchReviewQueue(
  client: StudioClient,
  projectId?: string,
): Promise<ReviewQueue> {
  const params: Record<string, string> = {};
  if (projectId !== undefined) params.project_id = projectId;
  params.conflict_window_hours = "24";
  const result = await client.GET("/api/v1/review-queue", { params: { query: params } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

/** Charge les décisions (global ou project-scopé). */
async function fetchDecisions(
  client: StudioClient,
  projectId?: string,
): Promise<Decision[]> {
  const params: Record<string, string> = {};
  if (projectId !== undefined) params.project_id = projectId;
  const result = await client.GET("/api/v1/decisions", { params: { query: params } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

/** Crée une décision avec Idempotency-Key. */
async function createDecision(
  client: StudioClient,
  decisionIn: DecisionCreate,
  idempotencyKey: string,
): Promise<Decision> {
  const result = await client.POST("/api/v1/decisions", {
    body: decisionIn,
    headers: { "Idempotency-Key": idempotencyKey },
  });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

/** Accepte une décision proposée (transition, admin uniquement — DEC-0098). */
async function acceptDecision(client: StudioClient, decisionId: string): Promise<Decision> {
  const result = await client.POST("/api/v1/decisions/{decision_id}/accept", {
    params: { path: { decision_id: decisionId } },
  });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

/** Supersede une décision (transition, admin uniquement — DEC-0098). */
async function supersedeDecision(client: StudioClient, decisionId: string): Promise<Decision> {
  const result = await client.POST("/api/v1/decisions/{decision_id}/supersede", {
    params: { path: { decision_id: decisionId } },
  });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

/** Statuts depuis lesquels chaque transition est autorisée (miroir du service). */
const ACCEPTABLE_FROM = new Set(["proposed"]);
const SUPERSEDABLE_FROM = new Set(["proposed", "accepted"]);

function decisionActionsHtml(decision: Decision, isAdmin: boolean): string {
  const canAccept = ACCEPTABLE_FROM.has(decision.status);
  const canSupersede = SUPERSEDABLE_FROM.has(decision.status);
  if (!canAccept && !canSupersede) return "";
  const disabled = isAdmin ? "" : " disabled";
  const hint = isAdmin
    ? ""
    : `<span class="ds-list-sub" role="note">Réservé au rôle admin.</span>`;
  return (
    `<div class="decision-actions" role="group" aria-label="Actions pour cette décision">` +
    (canAccept
      ? `<button class="ds-btn ds-btn--sm ds-btn--primary" type="button" data-decision-accept="${esc(decision.id)}"${disabled}>Accepter</button>`
      : "") +
    (canSupersede
      ? `<button class="ds-btn ds-btn--sm" type="button" data-decision-supersede="${esc(decision.id)}"${disabled}>Remplacer</button>`
      : "") +
    hint +
    `</div>`
  );
}

/** Génère une clé d'idempotence côté client (UUID v4 simple). */
function generateIdempotencyKey(): string {
  return newUuid();
}

/** ------------------- RENDU FILE « À VALIDER » ------------------- */

export interface ReviewInboxOptions {
  authed: boolean;
  isAdmin: boolean;
  projectId?: string;
  error?: string;
  filter?: ReviewFilter;
}

/** Message d'un filtre sans résultat : honnête sur ce qui manque. */
function reviewFilterEmpty(filter: ReviewFilter): { title: string; message: string } {
  if (filter === "decide") {
    return { title: "Rien à décider", message: "Aucun travail IA, aucune décision et aucun plan n'attend de validation." };
  }
  return { title: "Aucun signal", message: "Aucun conflit, build en échec ou PR ouverte sur la fenêtre récente." };
}

/**
 * Boîte de réception : compteurs par type, filtres, héros de la prochaine
 * action puis les cartes restantes — triées du plus récent au plus ancien.
 */
export function reviewQueueHtml(queue: ReviewQueue | null, options: ReviewInboxOptions): string {
  const { authed, isAdmin, projectId, error } = options;
  const filter = options.filter ?? "all";
  // Sur la page globale, un lien de sortie pointerait vers elle-même : il
  // n'existe que dans l'espace projet.
  const seeAll = projectId !== undefined ? { label: "Voir la file globale", href: "#/decisions" } : undefined;
  const open = `<section class="review-section review-inbox" aria-label="À valider">`;

  if (error !== undefined) {
    return `${open}<div class="ds-notice ds-notice--danger" role="alert"><strong>File « À valider » indisponible.</strong>${esc(error)}</div></section>`;
  }

  const cards = buildReviewCards(queue);
  if (cards.length === 0) {
    return `${open}${dsEmptyState(
      "Rien à valider",
      "Aucun élément n'attend une décision humaine pour le moment.",
      seeAll,
    )}</section>`;
  }

  const visible = cards.filter((card) => filter === "all" || card.channel === filter);
  // Le héros promeut le premier objet à décider ; il est retiré de la file
  // pour qu'un objet n'apparaisse qu'une fois.
  const hero = visible.find((card) => card.channel === "decide") ?? null;
  const listed = hero === null ? visible : visible.filter((card) => card.key !== hero.key);
  const filters = reviewFiltersHtml(cards, filter, seeAll);

  if (visible.length === 0) {
    const empty = reviewFilterEmpty(filter);
    return `${open}${filters}${dsEmptyState(empty.title, empty.message)}</section>`;
  }

  const rows = listed.map((card) => reviewCardHtml(card, authed, isAdmin)).join("");
  return `${open}${filters}` +
    (hero === null ? "" : reviewHeroHtml(hero, authed, isAdmin)) +
    `<ul class="ds-list review-list" role="list">${rows}</ul></section>`;
}

/** ------------------- RENDU DECISIONS ------------------- */

export interface DecisionItemOptions {
  /** Décision la plus récente, mise en avant en tête de liste. */
  latest?: boolean;
  /** Lien projet dans la méta ; inutile dans l'espace d'un projet. */
  showProject?: boolean;
}

export function decisionHtml(decision: Decision, authed: boolean, isAdmin: boolean, options: DecisionItemOptions = {}): string {
  const { latest = false, showProject = true } = options;
  const statusLabel = DECISION_STATUS_LABEL[decision.status] ?? decision.status;
  const statusTone = DECISION_STATUS_TONE[decision.status] ?? "neutral";
  const proposerLabel = PROPOSER_TYPE_LABEL[decision.proposed_by_type] ?? decision.proposed_by_type;
  const time = fmtTime(decision.created_at);
  const agentLink = decision.proposed_by_type === "agent"
    ? `<a href="#/agents/${esc(decision.proposed_by_id)}">${dsAgentBadge(agentLabel(decision.proposed_by_id))}</a>`
    : esc(decision.proposed_by_type === "user" ? FALLBACK_LABEL.user : proposerLabel);

  const meta: string[] = [
    `<span class="decision-item-id">${esc(decision.readable_id)}</span>`,
    `<time datetime="${esc(decision.created_at)}">${esc(time)}</time>`,
    `<span>${agentLink}</span>`,
  ];
  if (showProject && decision.project_id) {
    meta.push(`<a href="#/projects/${esc(decision.project_id)}">${esc(projectLabel(decision.project_id))}</a>`);
  }
  if (decision.task_id) {
    meta.push(`<a href="#/tasks/${esc(decision.task_id)}">${esc(ACTION_LABEL.openTask)}</a>`);
  }

  const techDetails = `
    <details class="decision-tech"><summary>Informations techniques</summary><dl>
      <div><dt>Identifiant</dt><dd><code class="mono">${esc(decision.id)}</code></dd></div>
      <div><dt>Identifiant courant</dt><dd><code class="mono">${esc(decision.readable_id)}</code></dd></div>
      <div><dt>Projet</dt><dd>${decision.project_id ? `<code class="mono">${esc(decision.project_id)}</code>` : "—"}</dd></div>
      ${decision.task_id ? `<div><dt>Tâche</dt><dd><code class="mono">${esc(decision.task_id)}</code></dd></div>` : ""}
      <div><dt>Proposé par</dt><dd>${esc(decision.proposed_by_type)} <code class="mono">${esc(decision.proposed_by_id)}</code></dd></div>
      <div><dt>Créée le</dt><dd>${esc(time)}</dd></div>
    </dl></details>`;

  return `<li class="ds-list-item decision-item${latest ? " decision-item--latest" : ""}" data-id="${esc(decision.id)}">` +
    `<div class="grow">` +
    (latest ? `<p class="decision-item-eyebrow">Dernière décision</p>` : "") +
    `<div class="decision-item-title-row">` +
    `<h3 class="decision-item-title">${esc(decision.title)}</h3>` +
    `${dsBadge(statusLabel, statusTone)}` +
    `</div>` +
    `<p class="decision-item-meta">${meta.join(`<span class="meta-sep" aria-hidden="true">·</span>`)}</p>` +
    `<div class="decision-item-body">${esc(decision.body)}</div>` +
    (authed ? decisionActionsHtml(decision, isAdmin) : "") +
    `${techDetails}` +
    `</div>` +
    `</li>`;
}

/** Filtre d'état de l'historique : un statut, ou tout. */
export type DecisionFilter = "all" | "proposed" | "accepted" | "superseded";

export const DECISION_FILTERS: ReadonlyArray<{ id: DecisionFilter; label: string }> = [
  { id: "all", label: "Toutes" },
  { id: "proposed", label: "En attente" },
  { id: "accepted", label: "Acceptées" },
  { id: "superseded", label: "Remplacées" },
];

export const DECISIONS_PAGE_SIZE = 6;

export interface DecisionsView {
  filter: DecisionFilter;
  page: number;
}

/** Plus récentes d'abord ; repli stable par identifiant si la date est illisible. */
export function sortDecisions(decisions: readonly Decision[]): Decision[] {
  return [...decisions].sort((a, b) => {
    const left = Date.parse(a.created_at);
    const right = Date.parse(b.created_at);
    if (!Number.isNaN(left) && !Number.isNaN(right) && left !== right) return right - left;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
}

/** Page demandée, bornée à [1, nombre de pages] ; `pages` vaut au moins 1. */
export function paginateDecisions<T>(items: readonly T[], page: number, size = DECISIONS_PAGE_SIZE): { items: T[]; page: number; pages: number } {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(Math.max(1, Math.floor(page) || 1), pages);
  return { items: items.slice((current - 1) * size, current * size), page: current, pages };
}

function decisionsFiltersHtml(decisions: readonly Decision[], filter: DecisionFilter): string {
  const count = (id: DecisionFilter): number => (id === "all" ? decisions.length : decisions.filter((d) => d.status === id).length);
  const buttons = DECISION_FILTERS
    .filter((item) => item.id === "all" || count(item.id) > 0)
    .map((item) => {
      const active = item.id === filter;
      return `<button class="${active ? "ds-btn ds-btn--primary" : "ds-btn"}" type="button" data-decisions-filter="${item.id}" aria-pressed="${active ? "true" : "false"}">${esc(item.label)} <span class="review-filter-count">${count(item.id)}</span></button>`;
    })
    .join("");
  return `<div class="review-filters" role="group" aria-label="Filtrer l'historique des décisions">${buttons}</div>`;
}

function decisionsPagerHtml(page: number, pages: number): string {
  if (pages <= 1) return "";
  return `<nav class="decisions-pager" aria-label="Pagination des décisions">` +
    `<button type="button" class="ds-btn ds-btn--sm" data-decisions-page="${page - 1}"${page <= 1 ? " disabled" : ""}>Précédent</button>` +
    `<span class="ds-list-sub" aria-live="polite">Page ${page} sur ${pages}</span>` +
    `<button type="button" class="ds-btn ds-btn--sm" data-decisions-page="${page + 1}"${page >= pages ? " disabled" : ""}>Suivant</button></nav>`;
}

export function decisionsHtml(
  decisions: Decision[],
  authed: boolean,
  isAdmin: boolean,
  projectId?: string,
  decisionsError?: string,
  view: DecisionsView = { filter: "all", page: 1 },
): string {
  const seeGlobal = projectId
    ? `<a class="review-see-all" href="#/decisions">Voir les décisions globales</a>`
    : "";

  if (decisionsError !== undefined) {
    return `<section class="decisions-section" aria-label="Historique des décisions">` +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Décisions indisponibles.</strong>${esc(decisionsError)}</div></section>`;
  }

  const createBtn = authed
    ? `<button class="ds-btn ds-btn--primary" type="button" id="create-decision-btn">Créer une décision</button>`
    : "";

  if (decisions.length === 0) {
    return `<section class="decisions-section" aria-label="Historique des décisions">` +
      dsEmptyState(
        "Aucune décision",
        projectId
          ? "Aucune décision liée à ce projet pour le moment."
          : "Aucune décision globale pour le moment.",
      ) +
      (createBtn === "" && seeGlobal === "" ? "" : `<div class="decisions-toolbar">${createBtn}${seeGlobal}</div>`) +
      `</section>`;
  }

  const filtered = sortDecisions(decisions).filter((d) => view.filter === "all" || d.status === view.filter);
  const paged = paginateDecisions(filtered, view.page);
  const rows = paged.items
    .map((d, index) => decisionHtml(d, authed, isAdmin, { latest: paged.page === 1 && index === 0 && view.filter === "all", showProject: projectId === undefined }))
    .join("");
  const list = filtered.length === 0
    ? dsEmptyState("Aucune décision à afficher", "Aucune décision ne correspond à ce filtre.")
    : `<ul class="ds-list decisions-list" role="list">${rows}</ul>`;
  return `<section class="decisions-section" aria-label="Historique des décisions">` +
    `<div class="decisions-toolbar">${decisionsFiltersHtml(decisions, view.filter)}<span class="decisions-toolbar-end">${seeGlobal}${createBtn}</span></div>` +
    list + decisionsPagerHtml(paged.page, paged.pages) + `</section>`;
}

/** ------------------- MODALE CRÉATION DECISION ------------------- */

export function createDecisionFormHtml(
  authed: boolean,
  projectId: string | undefined,
  proposerId: string,
): string {
  const projectField =
    projectId !== undefined
      ? `<span class="meta">Projet: <code class="mono">${esc(projectId)}</code></span>`
      : dsField("decision-project_id", "Projet (facultatif)", `<input class="ds-input" id="FIELD" name="project_id" type="text" placeholder="Collez l'identifiant du projet" />`, "Laissez vide pour une décision globale.");

  return `<form data-create-decision class="decision-form">` +
    `<input type="hidden" name="idempotency_key" value="${generateIdempotencyKey()}" />` +
    `${projectField}` +
    `${dsField("decision-task_id", "Tâche (facultative)", `<input class="ds-input" id="FIELD" name="task_id" type="text" placeholder="Collez l'identifiant de la tâche" />`, "Liez cette décision à une tâche si pertinent.")}` +
    `${dsField("decision-title", "Titre", `<input class="ds-input" id="FIELD" name="title" type="text" required />`, "Titre clair et concis de la décision.")}` +
    `${dsField("decision-body", "Contenu", `<textarea class="ds-input" id="FIELD" name="body" rows="4" required></textarea>`, "Décrivez la décision, son contexte et ses implications.")}` +
    `${dsField("decision-proposed_by_type", "Proposé par", `<select class="ds-input" id="FIELD" name="proposed_by_type"><option value="user">Utilisateur</option><option value="agent">Agent</option><option value="system">Système</option></select>`)}` +
    `${dsField("decision-proposed_by_id", "Identifiant du proposant", `<input class="ds-input" id="FIELD" name="proposed_by_id" type="text" value="${esc(proposerId)}" required />`, "Prérempli avec votre identifiant ; ne le changez que pour proposer au nom d'un agent ou du système.")}` +
    `<div class="decision-form-actions">` +
    `<button class="ds-btn ds-btn--primary" type="submit" ${authed ? "" : "disabled"}>Créer la décision</button>` +
    `<button class="ds-btn" type="button" data-ds-close>Annuler</button>` +
    `</div>` +
    `<div data-create-msg class="ds-list-sub" role="alert"></div>` +
    `</form>`;
}

/** ------------------- RENDU PRINCIPAL ------------------- */

export function decisionsTabsHtml(activeTab: "review" | "decisions"): string {
  return dsTabsHtml("decisions-main", [
    { id: "review", label: "À valider", panel: '<div id="review-panel"></div>' },
    { id: "decisions", label: "Historique des décisions", panel: '<div id="decisions-panel"></div>' },
  ], activeTab, "À valider");
}

/**
 * Titre de page. Dans l'espace projet (`projectId`), la vue est un onglet du
 * workspace qui porte déjà le h1 : pas de second titre de page.
 */
function decisionsPageHeader(projectId: string | undefined): string {
  return projectId === undefined
    ? dsPageHeader("Décisions", "Ce qui attend votre validation, et l'historique des décisions.")
    : "";
}

export async function renderDecisionsV2(root: HTMLElement, ctx: DecisionsContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML =
      decisionsPageHeader(ctx.projectId) +
      dsEmptyState("Connectez-vous", "Saisissez votre jeton machine pour charger la file d'examen et les décisions.");
    return;
  }

  const projectId = ctx.projectId;
  root.innerHTML = decisionsPageHeader(projectId) + dsSkeleton(4);

  const [reviewResult, decisionsResult] = await Promise.allSettled([
    fetchReviewQueue(ctx.client, projectId),
    fetchDecisions(ctx.client, projectId),
  ]);

  const reviewQueue = reviewResult.status === "fulfilled" ? reviewResult.value : null;
  const reviewError = reviewResult.status === "rejected" ? describeError(reviewResult.reason) : undefined;
  const decisions = decisionsResult.status === "fulfilled" ? decisionsResult.value : [];
  const decisionsError = decisionsResult.status === "rejected" ? describeError(decisionsResult.reason) : undefined;
  const isAdmin = await isAdminIdentity(ctx.client);

  // Rendu initial avec onglets
  root.innerHTML =
    decisionsPageHeader(projectId) +
    decisionsTabsHtml("review") +
    `<div id="decision-modal-host"></div>`;

  initDsTabs(root, "decisions-main");

  const reviewPanel = root.querySelector<HTMLElement>("#review-panel");
  const decisionsPanel = root.querySelector<HTMLElement>("#decisions-panel");
  const decisionModalHost = root.querySelector<HTMLElement>("#decision-modal-host");

  // Rendu de la boîte de réception « À valider »
  if (reviewPanel !== null) {
    renderReviewInbox(root, reviewPanel, ctx, isAdmin, reviewQueue, reviewError);
  }

  // Rendu Decisions
  if (decisionsPanel !== null) {
    const proposer = decodeJwtSubject(getToken()) ?? "";
    paintDecisions(root, decisionsPanel, ctx, decisions, isAdmin, decisionsError);
    bindDecisionForm(root, ctx, proposer, isAdmin);
  }

  // Créer la modale de création décision (cachée, injectée dans decisionModalHost)
  if (decisionModalHost !== null && ctx.authed) {
    const proposer = decodeJwtSubject(getToken()) ?? "";
    decisionModalHost.innerHTML = dsModalHtml({
      id: "create-decision-modal",
      title: "Créer une décision",
      body: createDecisionFormHtml(ctx.authed, projectId, proposer),
      actions: [],
    });
  }
}

/** Filtre courant du panneau : survit aux re-rendus (approbation, transition). */
function readReviewFilter(panel: HTMLElement): ReviewFilter {
  const value = panel.dataset["reviewFilter"];
  return value === "decide" || value === "signal" ? value : "all";
}

/** Peint la boîte de réception et recâble ses filtres et ses actions. */
function renderReviewInbox(
  root: HTMLElement,
  panel: HTMLElement,
  ctx: DecisionsContext,
  isAdmin: boolean,
  queue: ReviewQueue | null,
  error: string | undefined,
): void {
  const filter = readReviewFilter(panel);
  panel.dataset["reviewFilter"] = filter;
  panel.innerHTML = reviewQueueHtml(queue, {
    authed: ctx.authed,
    isAdmin,
    projectId: ctx.projectId,
    error,
    filter,
  });
  bindReviewFilter(root, panel, ctx, isAdmin, queue, error);
  bindReviewActions(root, panel, ctx, isAdmin);
}

/** Filtres Tous / À décider / Signaux : re-paint local, aucun nouvel appel API. */
function bindReviewFilter(
  root: HTMLElement,
  panel: HTMLElement,
  ctx: DecisionsContext,
  isAdmin: boolean,
  queue: ReviewQueue | null,
  error: string | undefined,
): void {
  const buttons = panel.querySelectorAll<HTMLButtonElement>("[data-review-filter]");
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      panel.dataset["reviewFilter"] = button.dataset["reviewFilter"] ?? "all";
      const active = readReviewFilter(panel);
      renderReviewInbox(root, panel, ctx, isAdmin, queue, error);
      // Le panneau est repeint : le filtre actif reprend le focus.
      panel.querySelector<HTMLButtonElement>(`[data-review-filter="${CSS.escape(active)}"]`)?.focus();
    });
  });
}

function bindReviewActions(root: HTMLElement, panel: HTMLElement, ctx: DecisionsContext, isAdmin: boolean): void {
  const buttons = panel.querySelectorAll<HTMLButtonElement>("[data-review-approve], [data-review-changes]");
  buttons.forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.dataset.reviewApprove ?? button.dataset.reviewChanges ?? "";
      const resolution: ReviewResolution = button.dataset.reviewApprove !== undefined ? "approved" : "changes_requested";
      const label = resolution === "approved" ? "Approuver" : "Demander des modifications";

      // Désactiver tous les boutons pendant l'action
      buttons.forEach((b) => (b.disabled = true));
      button.textContent = `${label}…`;

      try {
        await resolveReview(ctx.client, id, resolution);
        dsNotify(`Travail IA ${resolution === "approved" ? "approuvé" : "refusé (modifications demandées)"}.`, "success");
        // Re-rendre la file « À valider » (le filtre courant est conservé)
        const reviewQueue = await fetchReviewQueue(ctx.client, ctx.projectId);
        const newPanel = root.querySelector<HTMLElement>("#review-panel");
        if (newPanel !== null) {
          renderReviewInbox(root, newPanel, ctx, isAdmin, reviewQueue, undefined);
        }
      } catch (error) {
        dsNotify(describeError(error), "danger");
        button.textContent = label;
        buttons.forEach((b) => (b.disabled = false));
      }
    });
  });
  bindDecisionTransitionButtons(root, panel, ctx, isAdmin);
}

/**
 * Accept/supersede buttons appear both on Review Queue `decision_proposal`
 * items and on the Decisions list itself (DEC-0098) — one handler, bound in
 * both panels, that resolves the transition then refreshes both (a
 * transition always changes whether the Decision still belongs in the
 * queue, and always changes its status in the list).
 */
function bindDecisionTransitionButtons(
  root: HTMLElement,
  panel: HTMLElement,
  ctx: DecisionsContext,
  isAdmin: boolean,
): void {
  const buttons = panel.querySelectorAll<HTMLButtonElement>(
    "[data-decision-accept], [data-decision-supersede]",
  );
  buttons.forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.dataset.decisionAccept ?? button.dataset.decisionSupersede ?? "";
      const isAccept = button.dataset.decisionAccept !== undefined;
      const label = isAccept ? "Accepter" : "Remplacer";

      buttons.forEach((b) => (b.disabled = true));
      button.textContent = `${label}…`;

      try {
        await (isAccept ? acceptDecision(ctx.client, id) : supersedeDecision(ctx.client, id));
        dsNotify(`Décision ${isAccept ? "acceptée" : "remplacée"}.`, "success");
        await refreshDecisionsAndReview(root, ctx, isAdmin);
      } catch (error) {
        dsNotify(describeError(error), "danger");
        button.textContent = label;
        buttons.forEach((b) => (b.disabled = false));
      }
    });
  });
}

async function refreshDecisionsAndReview(
  root: HTMLElement,
  ctx: DecisionsContext,
  isAdmin: boolean,
): Promise<void> {
  const [reviewQueue, decisions] = await Promise.all([
    fetchReviewQueue(ctx.client, ctx.projectId),
    fetchDecisions(ctx.client, ctx.projectId),
  ]);
  const reviewPanel = root.querySelector<HTMLElement>("#review-panel");
  if (reviewPanel !== null) {
    renderReviewInbox(root, reviewPanel, ctx, isAdmin, reviewQueue, undefined);
  }
  const decisionsPanel = root.querySelector<HTMLElement>("#decisions-panel");
  if (decisionsPanel !== null) {
    paintDecisions(root, decisionsPanel, ctx, decisions, isAdmin);
  }
}

/** Filtre et page courants de l'historique : survivent aux re-rendus. */
const decisionViews = new WeakMap<HTMLElement, DecisionsView>();
const decisionCache = new WeakMap<HTMLElement, { decisions: Decision[]; error?: string }>();

/** Peint l'historique et recâble ses actions, filtres et pagination. */
function paintDecisions(
  root: HTMLElement,
  panel: HTMLElement,
  ctx: DecisionsContext,
  decisions: Decision[],
  isAdmin: boolean,
  error?: string,
): void {
  const view = decisionViews.get(panel) ?? { filter: "all" as DecisionFilter, page: 1 };
  decisionViews.set(panel, view);
  decisionCache.set(panel, { decisions, error });
  panel.innerHTML = decisionsHtml(decisions, ctx.authed, isAdmin, ctx.projectId, error, view);
  bindDecisionTransitionButtons(root, panel, ctx, isAdmin);

  const createBtn = panel.querySelector<HTMLButtonElement>("#create-decision-btn");
  createBtn?.addEventListener("click", () => {
    openDsDialog(root, "create-decision-modal", createBtn);
  });

  const repaint = (focus: string): void => {
    const cached = decisionCache.get(panel);
    if (cached === undefined) return;
    paintDecisions(root, panel, ctx, cached.decisions, isAdmin, cached.error);
    panel.querySelector<HTMLElement>(focus)?.focus();
  };
  panel.querySelectorAll<HTMLButtonElement>("[data-decisions-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      view.filter = (button.dataset["decisionsFilter"] as DecisionFilter | undefined) ?? "all";
      view.page = 1;
      repaint(`[data-decisions-filter="${CSS.escape(view.filter)}"]`);
    });
  });
  panel.querySelectorAll<HTMLButtonElement>("[data-decisions-page]").forEach((button) => {
    button.addEventListener("click", () => {
      view.page = Number(button.dataset["decisionsPage"]) || 1;
      repaint(`[data-decisions-page="${CSS.escape(String(view.page))}"]`);
    });
  });
}

function bindDecisionForm(
  root: HTMLElement,
  ctx: DecisionsContext,
  proposerId: string,
  isAdmin: boolean,
): void {
  // Soumission du formulaire dans la modale
  const modalHost = root.querySelector<HTMLElement>("#decision-modal-host");
  const form = modalHost?.querySelector<HTMLFormElement>("[data-create-decision]");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const msg = form.querySelector("[data-create-msg]");
    const submitBtn = form.querySelector<HTMLButtonElement>('button[type="submit"]');
    const idempotencyKey = data.get("idempotency_key") as string;

    const proposedById = String(data.get("proposed_by_id") ?? "").trim();
    if (!isUuid(proposedById)) {
      if (msg !== null) {
        msg.textContent = "L'identifiant du proposant doit être un UUID.";
        if (msg instanceof HTMLElement) focusDsErrorBox(msg);
      }
      return;
    }

    if (submitBtn !== null) submitBtn.disabled = true;

    const project = ctx.projectId ?? String(data.get("project_id") ?? "").trim();
    const taskId = String(data.get("task_id") ?? "").trim();
    const title = String(data.get("title") ?? "").trim();
    const body = String(data.get("body") ?? "").trim();
    const proposedByType = String(data.get("proposed_by_type") ?? "user");

    try {
      await createDecision(ctx.client, {
        project_id: project === "" ? null : project,
        task_id: taskId === "" ? null : taskId,
        title,
        body,
        proposed_by_type: proposedByType,
        proposed_by_id: proposedById,
      }, idempotencyKey);

      dsNotify("Décision créée.", "success");
      closeDsDialog(root, "create-decision-modal");

      // Recharger les décisions
      const decisions = await fetchDecisions(ctx.client, ctx.projectId);
      const newPanel = root.querySelector<HTMLElement>("#decisions-panel");
      if (newPanel !== null) {
        paintDecisions(root, newPanel, ctx, decisions, isAdmin);
        // Le panneau est repeint : refocaliser l'action de création.
        newPanel.querySelector<HTMLElement>("#create-decision-btn")?.focus();
      }
    } catch (error) {
      // Nouvelle tentative indépendante après un échec définitif : clé neuve,
      // jamais réutilisée pour un corps potentiellement modifié.
      const keyInput = form.querySelector<HTMLInputElement>('input[name="idempotency_key"]');
      if (keyInput !== null) keyInput.value = generateIdempotencyKey();
      if (msg !== null) {
        msg.textContent = describeError(error);
        if (msg instanceof HTMLElement) focusDsErrorBox(msg);
      }
      if (submitBtn !== null) submitBtn.disabled = false;
    }
  });
}
