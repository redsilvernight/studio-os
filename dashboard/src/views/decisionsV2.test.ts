/**
 * UI-8 — Decisions & Review : boîte de réception « À valider » + Décisions.
 *
 * Tests DOM-free (vitest, node) : assertions sur les chaînes produites +
 * lecture statique de decisions.css pour le responsive.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  REVIEW_KIND_LABEL,
  REVIEW_KIND_COUNT_LABEL,
  REVIEW_IMPACT,
  REVIEW_CHANNEL,
  DECISION_STATUS_LABEL,
  PROPOSER_TYPE_LABEL,
  reviewQueueItemDetail,
  reviewCardKey,
  buildReviewCards,
  reviewCounts,
  reviewCardTitle,
  reviewCardActions,
  reviewCardTechRows,
  reviewCardHtml,
  reviewHeroTitle,
  reviewHeroHtml,
  reviewCountersHtml,
  reviewFiltersHtml,
  reviewQueueHtml,
  decisionHtml,
  decisionsHtml,
  createDecisionFormHtml,
  decisionsTabsHtml,
  type ReviewCard,
  type ReviewQueue,
  type Decision,
} from "./decisionsV2";

const P1 = "11111111-2222-4333-8444-555555555555";
const A1 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
const T1 = "tttttttt-uuuu-vvvv-wwww-xxxxxxxxxxxx";
const R1 = "99999999-8888-4777-8666-555555555555";
const R2 = "77777777-7777-4777-8777-777777777777";

type Kind = keyof typeof REVIEW_KIND_LABEL;

function aiWorkItem(id = "rw1", title = "Relire la sortie agent", requestedAt = "2026-09-10T10:00:00Z"): ReviewQueue {
  return {
    items: [{
      kind: "ai_work_review",
      id,
      project_id: P1,
      task_id: T1,
      title,
      agent_id: A1,
      requested_at: requestedAt,
    }],
    generated_at: requestedAt,
  };
}

function decisionProposalItem(id = "rw2"): ReviewQueue {
  return {
    items: [{
      kind: "decision_proposal",
      id,
      project_id: P1,
      task_id: null,
      readable_id: "DEC-0049",
      title: "Choisir le moteur de rendu",
      proposed_by_type: "agent",
      requested_at: "2026-09-10T10:00:00Z",
    }],
    generated_at: "2026-09-10T10:00:00Z",
  };
}

function conflictItem(id = "rw3"): ReviewQueue {
  return {
    items: [{
      kind: "resource_conflict",
      id,
      project_id: P1,
      task_id: T1,
      title: "Conflit sur scenes/level_01.tscn",
      resource_path: "scenes/level_01.tscn",
      requested_at: "2026-09-10T10:00:00Z",
    }],
    generated_at: "2026-09-10T10:00:00Z",
  };
}

function buildItem(id = "rw4"): ReviewQueue {
  return {
    items: [{
      kind: "build_failure",
      id,
      project_id: P1,
      task_id: T1,
      title: "Build CI échoué",
      workflow_name: "ci",
      branch: "main",
      commit_sha: "abcdef123456",
      conclusion: "failure",
      requested_at: "2026-09-10T10:00:00Z",
    }],
    generated_at: "2026-09-10T10:00:00Z",
  };
}

function prItem(id = "rw5"): ReviewQueue {
  return {
    items: [{
      kind: "pr_ready",
      id,
      project_id: P1,
      task_id: null,
      title: "PR #42 feat/ui-8",
      pr_number: 42,
      head_branch: "feat/ui-8",
      base_branch: "main",
      requested_at: "2026-09-10T10:00:00Z",
    }],
    generated_at: "2026-09-10T10:00:00Z",
  };
}

function roadmapItem(options: {
  id?: string;
  roadmapId?: string;
  title?: string;
  scope: "roadmap" | "revision";
  revisionNo?: number | null;
  baseRevisionNo?: number | null;
  requestedAt?: string;
}): ReviewQueue {
  const at = options.requestedAt ?? "2026-09-10T10:00:00Z";
  return {
    items: [{
      kind: "roadmap_proposal",
      id: options.id ?? "rp1",
      project_id: P1,
      task_id: null,
      roadmap_id: options.roadmapId ?? R1,
      title: options.title ?? "Plan UX Desktop V2",
      scope: options.scope,
      status: "proposed",
      revision_no: options.revisionNo ?? null,
      base_revision_no: options.baseRevisionNo ?? null,
      actor_type: "human",
      requested_at: at,
    }],
    generated_at: at,
  };
}

/** File réaliste : 2 travaux IA, 1 décision, 1 plan en révision, 3 signaux. */
function inboxQueue(): ReviewQueue {
  return {
    items: [
      aiWorkItem("rw1", "Wireframes P02 rendus", "2026-09-10T09:20:00Z").items[0]!,
      aiWorkItem("rw6", "Libellé « Reprendre » de l'accueil", "2026-09-10T08:20:00Z").items[0]!,
      decisionProposalItem().items[0]!,
      roadmapItem({ id: "rp2", scope: "revision", revisionNo: 2, baseRevisionNo: 1 }).items[0]!,
      conflictItem().items[0]!,
      buildItem().items[0]!,
      prItem().items[0]!,
    ],
    generated_at: "2026-09-10T10:00:00Z",
  };
}

/** Première carte d'une file (helper de lecture). */
function firstCard(queue: ReviewQueue): ReviewCard {
  const card = buildReviewCards(queue)[0];
  if (card === undefined) throw new Error("file vide");
  return card;
}

/** Nombre d'actions rendues dans le groupe d'actions d'une carte ou d'un héros. */
function renderedActionCount(html: string, className = "review-card-actions"): number {
  const block = new RegExp(`<div class="${className}"[^>]*>([\\s\\S]*?)</div>`).exec(html);
  return ((block?.[1] ?? "").match(/<(?:button|a)\s/g) ?? []).length;
}

/** Texte visible par défaut : hors « Détails techniques », hors attributs. */
function visibleText(html: string): string {
  return html.replace(/<details[\s\S]*?<\/details>/g, "").replace(/<[^>]*>/g, "");
}

function decision(
  id = "d1",
  status: "proposed" | "accepted" | "superseded" = "proposed",
  projectId: string | null = P1,
  taskId: string | null = T1,
): Decision {
  return {
    id,
    readable_id: "DEC-0049",
    project_id: projectId,
    task_id: taskId,
    title: "Choisir le moteur de rendu",
    body: "Après analyse, nous choisissons Godot 4.3 pour sa stabilité.",
    status,
    proposed_by_type: "agent",
    proposed_by_id: A1,
    created_at: "2026-09-10T10:00:00Z",
  };
}

const KIND_CASES: Array<{ kind: Kind; queue: ReviewQueue }> = [
  { kind: "ai_work_review", queue: aiWorkItem() },
  { kind: "decision_proposal", queue: decisionProposalItem() },
  { kind: "roadmap_proposal", queue: roadmapItem({ scope: "revision", revisionNo: 2, baseRevisionNo: 1 }) },
  { kind: "resource_conflict", queue: conflictItem() },
  { kind: "build_failure", queue: buildItem() },
  { kind: "pr_ready", queue: prItem() },
];

describe("Labels FR (source unique)", () => {
  it("REVIEW_KIND_LABEL : tous les kinds ont un libellé FR", () => {
    expect(REVIEW_KIND_LABEL.ai_work_review).toBe("Travail IA");
    expect(REVIEW_KIND_LABEL.decision_proposal).toBe("Proposition de décision");
    expect(REVIEW_KIND_LABEL.resource_conflict).toBe("Conflit de réservation");
    expect(REVIEW_KIND_LABEL.build_failure).toBe("Échec de build");
    expect(REVIEW_KIND_LABEL.pr_ready).toBe("PR ouverte");
    expect(REVIEW_KIND_LABEL.roadmap_proposal).toBe("Proposition de roadmap");
  });

  it("les six types partagent libellé, compteur et impact", () => {
    const kinds = Object.keys(REVIEW_KIND_LABEL) as Kind[];
    expect(kinds).toHaveLength(6);
    for (const kind of kinds) {
      expect(REVIEW_KIND_COUNT_LABEL[kind]).not.toBe("");
      expect(REVIEW_IMPACT[kind]).toMatch(/^Impact : /);
      expect(["decide", "signal"]).toContain(REVIEW_CHANNEL[kind]);
    }
  });

  it("trois canaux « À décider », trois signaux informatifs", () => {
    const decide = (Object.keys(REVIEW_CHANNEL) as Kind[]).filter((kind) => REVIEW_CHANNEL[kind] === "decide");
    expect(decide.sort()).toEqual(["ai_work_review", "decision_proposal", "roadmap_proposal"]);
  });

  it("DECISION_STATUS_LABEL : statuts traduits", () => {
    expect(DECISION_STATUS_LABEL.proposed).toBe("Proposée");
    expect(DECISION_STATUS_LABEL.accepted).toBe("Acceptée");
    expect(DECISION_STATUS_LABEL.superseded).toBe("Remplacée");
  });

  it("PROPOSER_TYPE_LABEL : types proposants traduits", () => {
    expect(PROPOSER_TYPE_LABEL.user).toBe("Utilisateur");
    expect(PROPOSER_TYPE_LABEL.agent).toBe("Agent");
    expect(PROPOSER_TYPE_LABEL.system).toBe("Système");
  });
});

describe("reviewQueueItemDetail", () => {
  it("détail selon kind, sans identifiant brut", () => {
    expect(reviewQueueItemDetail(aiWorkItem().items[0]!)).toContain("Relire le travail de");
    expect(reviewQueueItemDetail(decisionProposalItem().items[0]!)).toBe("DEC-0049 · Agent");
    expect(reviewQueueItemDetail(conflictItem().items[0]!)).toBe("sur scenes/level_01.tscn");
    expect(reviewQueueItemDetail(buildItem().items[0]!)).toBe("ci sur main");
    expect(reviewQueueItemDetail(prItem().items[0]!)).toBe("PR #42 · feat/ui-8 → main");
    expect(
      reviewQueueItemDetail(roadmapItem({ scope: "revision", revisionNo: 3, baseRevisionNo: 2 }).items[0]!),
    ).toBe("révision 3 sur base 2 · par human");
  });
});

describe("buildReviewCards — un objet, une carte", () => {
  it("file vide ou absente : aucune carte", () => {
    expect(buildReviewCards(null)).toEqual([]);
    expect(buildReviewCards({ items: [], generated_at: "" })).toEqual([]);
  });

  it("proposition + révisions d'un même plan : une seule carte « Révision N du plan »", () => {
    const queue: ReviewQueue = {
      items: [
        roadmapItem({ id: "rp-roadmap", scope: "roadmap", requestedAt: "2026-09-09T10:00:00Z" }).items[0]!,
        roadmapItem({ id: "rp-rev1", scope: "revision", revisionNo: 1, requestedAt: "2026-09-10T09:00:00Z" }).items[0]!,
        roadmapItem({ id: "rp-rev2", scope: "revision", revisionNo: 2, baseRevisionNo: 1, requestedAt: "2026-09-10T10:00:00Z" }).items[0]!,
      ],
      generated_at: "2026-09-10T10:00:00Z",
    };
    const cards = buildReviewCards(queue);
    expect(cards).toHaveLength(1);
    const card = cards[0]!;
    expect(card.grouped).toBe(3);
    expect(card.item.id).toBe("rp-rev2");
    expect(reviewCardTitle(card)).toBe("Révision 2 du plan « Plan UX Desktop V2 »");
  });

  it("deux plans distincts : deux cartes", () => {
    const queue: ReviewQueue = {
      items: [
        roadmapItem({ id: "rp-a", roadmapId: R1, scope: "revision", revisionNo: 2 }).items[0]!,
        roadmapItem({ id: "rp-b", roadmapId: R2, scope: "revision", revisionNo: 4 }).items[0]!,
      ],
      generated_at: "2026-09-10T10:00:00Z",
    };
    expect(buildReviewCards(queue).map((card) => reviewCardKey(card.item))).toEqual([
      `roadmap:${P1}:${R1}`,
      `roadmap:${P1}:${R2}`,
    ]);
  });

  it("entrée répétée : regroupée, jamais dupliquée", () => {
    const item = aiWorkItem().items[0]!;
    const cards = buildReviewCards({ items: [item, { ...item }], generated_at: "" });
    expect(cards).toHaveLength(1);
    expect(cards[0]!.grouped).toBe(2);
  });

  it("tri requested_at décroissant, indépendant de l'ordre du serveur", () => {
    const queue = inboxQueue();
    const cards = buildReviewCards({ ...queue, items: [...queue.items].reverse() });
    // 10:00 d'abord (tie-break stable par identifiant), puis 09:20 et 08:20.
    expect(cards.map((card) => card.item.id)).toEqual(["rp2", "rw2", "rw3", "rw4", "rw5", "rw1", "rw6"]);
    expect(new Set(cards.map((card) => card.key)).size).toBe(cards.length);
  });

  it("portée « plan » sans numéro : aucune révision inventée", () => {
    const card = firstCard(roadmapItem({ scope: "roadmap" }));
    expect(reviewCardTitle(card)).toBe("Proposition de plan « Plan UX Desktop V2 »");
    expect(reviewCardActions(card, true, true)[0]!.label).toBe("Examiner le plan");
  });
});

describe("reviewCounts — compteurs par type réel", () => {
  it("totaux, canaux et détail par type", () => {
    const counts = reviewCounts(buildReviewCards(inboxQueue()));
    expect(counts.total).toBe(7);
    expect(counts.decide).toBe(4);
    expect(counts.signal).toBe(3);
    expect(counts.byKind).toEqual({
      ai_work_review: 2,
      decision_proposal: 1,
      roadmap_proposal: 1,
      resource_conflict: 1,
      build_failure: 1,
      pr_ready: 1,
    });
  });

  it("les compteurs suivent le dédoublonnage (2 révisions = 1 plan)", () => {
    const queue: ReviewQueue = {
      items: [
        roadmapItem({ id: "rp-rev1", scope: "revision", revisionNo: 1 }).items[0]!,
        roadmapItem({ id: "rp-rev2", scope: "revision", revisionNo: 2 }).items[0]!,
      ],
      generated_at: "",
    };
    const counts = reviewCounts(buildReviewCards(queue));
    expect(counts.total).toBe(1);
    expect(counts.byKind.roadmap_proposal).toBe(1);
  });

  it("reviewCountersHtml : un compteur par type présent, aucun type fantôme", () => {
    const html = reviewCountersHtml(buildReviewCards(inboxQueue()));
    expect(html).toContain("À valider par type");
    expect(html).toContain("2</b><span>travaux IA à relire");
    expect(html).toContain("1</b><span>décisions à trancher");
    expect(html).toContain("1</b><span>plans à examiner");
    expect(html).toContain("1</b><span>PR à relire");
    expect(html).toContain("3</b><span>signaux informatifs");
    const withoutRoadmap = reviewCountersHtml(buildReviewCards(prItem()));
    expect(withoutRoadmap).not.toContain("plans à examiner");
    expect(withoutRoadmap).not.toContain("travaux IA à relire");
    expect(withoutRoadmap).toContain("1</b><span>PR à relire");
    expect(withoutRoadmap).toContain("1</b><span>signaux informatifs");
  });

  it("reviewFiltersHtml : Tous / À décider / Signaux avec le compte réel", () => {
    const html = reviewFiltersHtml(buildReviewCards(inboxQueue()), "all");
    expect(html).toContain('data-review-filter="all" aria-pressed="true"');
    expect(html).toContain('data-review-filter="decide" aria-pressed="false"');
    expect(html).toContain('data-review-filter="signal" aria-pressed="false"');
    expect(html).toContain("Tous <span class=\"review-filter-count\">7</span>");
    expect(html).toContain("À décider <span class=\"review-filter-count\">4</span>");
    expect(html).toContain("Signaux <span class=\"review-filter-count\">3</span>");
  });
});

describe("reviewCardActions — au plus deux actions par carte", () => {
  it.each(KIND_CASES)("$kind : deux actions au maximum, quel que soit le rôle", ({ queue }) => {
    for (const [authed, isAdmin] of [[true, true], [true, false], [false, false]] as const) {
      const actions = reviewCardActions(firstCard(queue), authed, isAdmin);
      expect(actions.length).toBeLessThanOrEqual(2);
      expect(actions).toHaveLength(renderedActionCount(reviewCardHtml(firstCard(queue), authed, isAdmin)));
    }
  });

  it("travail IA : Approuver / Demander des modifications", () => {
    const actions = reviewCardActions(firstCard(aiWorkItem()), true, true);
    expect(actions.map((action) => action.label)).toEqual(["Approuver", "Demander des modifications"]);
    expect(actions[0]!.attribute).toBe('data-review-approve="rw1"');
    expect(actions[1]!.attribute).toBe('data-review-changes="rw1"');
    expect(actions.every((action) => action.disabled === false)).toBe(true);
  });

  it("travail IA sans auth : les deux boutons désactivés, rien perdu", () => {
    const html = reviewCardHtml(firstCard(aiWorkItem()), false, false);
    expect(html).toContain('data-review-approve="rw1"');
    expect(html).toContain('data-review-changes="rw1"');
    expect(html.match(/<button[^>]*disabled/g) ?? []).toHaveLength(2);
  });

  it("décision : Accepter / Remplacer, réservé au rôle admin (DEC-0098)", () => {
    const card = firstCard(decisionProposalItem());
    expect(reviewCardActions(card, true, true).map((action) => action.label)).toEqual(["Accepter", "Remplacer"]);
    expect(reviewCardActions(card, true, true)[0]!.attribute).toBe('data-decision-accept="rw2"');
    expect(reviewCardActions(card, true, false).every((action) => action.disabled === true)).toBe(true);
    expect(reviewCardHtml(card, true, false)).toContain("Réservé au rôle admin");
  });

  it("plan : Examiner la révision N + Ouvrir la roadmap", () => {
    const actions = reviewCardActions(firstCard(roadmapItem({ scope: "revision", revisionNo: 2 })), true, true);
    expect(actions).toHaveLength(2);
    expect(actions[0]).toMatchObject({ label: "Examiner la révision 2", element: "link" });
    expect(actions[0]!.attribute).toBe(`href="#/projects/${P1}/roadmap/${R1}"`);
    expect(actions[1]!.attribute).toBe(`href="#/projects/${P1}/roadmap"`);
  });

  it.each([
    { kind: "resource_conflict" as Kind, queue: conflictItem() },
    { kind: "build_failure" as Kind, queue: buildItem() },
    { kind: "pr_ready" as Kind, queue: prItem() },
  ])("$kind : navigation seulement, et la carte dit « non résoluble ici »", ({ queue }) => {
    const card = firstCard(queue);
    const actions = reviewCardActions(card, true, false);
    expect(actions.length).toBeGreaterThan(0);
    expect(actions.every((action) => action.element === "link")).toBe(true);
    expect(actions.map((action) => action.label)).toContain("Ouvrir le projet");
    const html = reviewCardHtml(card, true, false);
    expect(html).toContain("Non résoluble ici");
    expect(html).not.toContain("Aucune action disponible");
  });

  it("signal sans tâche liée : un seul lien, pas de lien mort", () => {
    const card = firstCard({ items: [{ ...prItem().items[0]!, task_id: null }], generated_at: "" });
    const actions = reviewCardActions(card, true, false);
    expect(actions).toHaveLength(1);
    expect(actions[0]!.label).toBe("Ouvrir le projet");
  });
});

describe("reviewCardHtml — une structure pour les six types", () => {
  it.each(KIND_CASES)("$kind : libellé, point de couleur, contexte, impact, détails repliés", ({ kind, queue }) => {
    const html = reviewCardHtml(firstCard(queue), true, true);
    expect(html).toContain('class="ds-card review-card"');
    expect(html).toContain(`data-kind="${kind}"`);
    expect(html).toContain(REVIEW_KIND_LABEL[kind]);
    expect(html).toMatch(/<span class="review-card-dot" data-tone="[a-z]+"/);
    expect(html).toContain('<p class="review-card-context">');
    expect(html).toContain("Impact : ");
    expect(html).toContain("<summary>Détails techniques</summary>");
    expect(html).not.toMatch(/\sstyle\s*=/i);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });

  it("C2 : aucun UUID ni type brut visible par défaut", () => {
    for (const { kind, queue } of KIND_CASES) {
      const text = visibleText(reviewCardHtml(firstCard(queue), true, true));
      expect(text, kind).not.toContain(P1);
      expect(text, kind).not.toContain(A1);
      expect(text, kind).not.toContain(kind);
    }
  });

  it("C2 : commit, branches et identifiants vivent dans « Détails techniques »", () => {
    const build = reviewCardHtml(firstCard(buildItem()), true, true);
    expect(build).toContain("abcdef123456");
    expect(build).toContain("Commit");
    const rows = reviewCardTechRows(firstCard(buildItem()));
    expect(rows.map((row) => row.label)).toContain("Branche");
    expect(rows.find((row) => row.label === "Commit")?.mono).toBe(true);
  });

  it("portée, révision, base et statut du plan dans les détails", () => {
    const labels = reviewCardTechRows(firstCard(roadmapItem({ scope: "revision", revisionNo: 2, baseRevisionNo: 1 })))
      .map((row) => row.label);
    expect(labels).toEqual(expect.arrayContaining(["Portée", "Révision", "Version de base", "Statut", "Résolution"]));
  });

  it("travail IA : nom d'agent humain, liens projet et tâche, pas d'identifiant", () => {
    const html = reviewCardHtml(firstCard(aiWorkItem()), true, true);
    expect(html).toContain("Relire la sortie agent");
    expect(html).toContain(`href="#/tasks/${T1}"`);
    expect(html).toContain('href="#/projects/');
    expect(visibleText(html)).not.toContain(A1);
  });
});

describe("héros de la file", () => {
  it("titre d'action par type, jamais le type technique", () => {
    expect(reviewHeroTitle(firstCard(aiWorkItem()))).toBe("Relire « Relire la sortie agent »");
    expect(reviewHeroTitle(firstCard(decisionProposalItem()))).toBe("Trancher DEC-0049");
    expect(reviewHeroTitle(firstCard(roadmapItem({ scope: "revision", revisionNo: 2 })))).toBe(
      "Approuver la révision 2 du plan",
    );
  });

  it("une seule action primaire : décider sans changer de page (C1)", () => {
    const html = reviewHeroHtml(firstCard(aiWorkItem()), true, true);
    expect(html).toContain("ds-hero");
    expect(renderedActionCount(html, "ds-hero-actions")).toBe(1);
    expect(html.match(/<button/g) ?? []).toHaveLength(1);
  });
});

describe("reviewQueueHtml — boîte de réception", () => {
  it("en-tête, résumé chiffré, filtres et compteurs par type", () => {
    const html = reviewQueueHtml(inboxQueue(), { authed: true, isAdmin: true });
    expect(html).toContain("À valider");
    expect(html).toContain("7 à valider · 4 à décider · 3 signaux · du plus récent au plus ancien");
    expect(html).toContain('data-review-filter="all"');
    expect(html).toContain("À valider par type");
    expect(html).toContain("travaux IA à relire");
    expect(html).not.toContain('href="#/decisions"');
  });

  it("chaque objet apparaît une seule fois : héros + cartes", () => {
    const html = reviewQueueHtml(inboxQueue(), { authed: true, isAdmin: true });
    const rendered = (html.match(/data-id="[^"]+"/g) ?? []).map((match) => match.slice(9, -1));
    // Le héros promeut un objet : il ne doit plus figurer dans la liste.
    expect(html).toContain('class="ds-hero review-hero"');
    expect(rendered).toHaveLength(buildReviewCards(inboxQueue()).length - 1);
    expect(new Set(rendered).size).toBe(rendered.length);
  });

  it("filtre À décider : seuls les objets résolubles ici", () => {
    const html = reviewQueueHtml(inboxQueue(), { authed: true, isAdmin: true, filter: "decide" });
    const kinds = (html.match(/data-kind="[^"]+"/g) ?? []).map((match) => match.slice(11, -1));
    expect(new Set(kinds)).toEqual(new Set(["ai_work_review", "decision_proposal"]));
    // Le plan le plus récent est promu en héros, jamais dupliqué dans la liste.
    expect(html).toContain("Approuver la révision 2 du plan");
    expect(kinds).not.toContain("roadmap_proposal");
    expect(html).toContain("4 à décider");
  });

  it("filtre Signaux : aucun héros, navigation et mention « non résoluble ici »", () => {
    const html = reviewQueueHtml(inboxQueue(), { authed: true, isAdmin: false, filter: "signal" });
    expect(html).not.toContain("ds-hero review-hero");
    expect(html).not.toContain('data-kind="ai_work_review"');
    expect(html).toContain('data-kind="pr_ready"');
    expect(html).toContain("Non résoluble ici");
  });

  it("filtre sans résultat : état vide honnête, filtres toujours présents", () => {
    const html = reviewQueueHtml(prItem(), { authed: true, isAdmin: false, filter: "decide" });
    expect(html).toContain("Rien à décider");
    expect(html).toContain("data-review-filter=");
    expect(html).not.toContain("<li");
  });

  it("file vide : état positif, sans lien vers la page courante", () => {
    const html = reviewQueueHtml({ items: [], generated_at: "" }, { authed: true, isAdmin: true });
    expect(html).toContain("Rien à valider");
    expect(html).toContain("Aucun élément n'attend une décision humaine");
    expect(html).not.toContain('href="#/decisions"');
  });

  it("espace projet : propose la file globale", () => {
    const html = reviewQueueHtml({ items: [], generated_at: "" }, { authed: true, isAdmin: true, projectId: P1 });
    expect(html).toContain("Voir la file globale");
    expect(html).toContain('href="#/decisions"');
  });

  it("erreur : notice danger sans jargon technique", () => {
    const html = reviewQueueHtml(null, { authed: true, isAdmin: true, error: "HTTP 500 · coupure" });
    expect(html).toContain("ds-notice--danger");
    expect(html).toContain("File « À valider » indisponible");
    expect(html).not.toContain("Error 500");
  });

  it("CSP : aucun style ni handler inline", () => {
    const html = reviewQueueHtml(inboxQueue(), { authed: true, isAdmin: true });
    expect(html).not.toMatch(/\sstyle\s*=/i);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });
});

describe("decisionHtml", () => {
  it("statut traduit + tonalité, pas de clé backend visible", () => {
    const html = decisionHtml(decision("d1", "proposed"), true, true);
    expect(html).toContain("Proposée");
    expect(html).toContain("ds-badge--info");
    expect(html).not.toContain("proposed");
  });

  it("accepted : tonalité success", () => {
    const html = decisionHtml(decision("d2", "accepted"), true, true);
    expect(html).toContain("Acceptée");
    expect(html).toContain("ds-badge--success");
  });

  it("superseded : tonalité warning", () => {
    const html = decisionHtml(decision("d3", "superseded"), true, true);
    expect(html).toContain("Remplacée");
    expect(html).toContain("ds-badge--warning");
  });

  it("proposé par agent : lien vers fiche agent + badge IA", () => {
    const html = decisionHtml(decision(), true, true);
    expect(html).toContain('href="#/agents/');
    expect(html).toContain("ds-badge--ai");
  });

  it("proposé par user : libellé humain, sans identifiant", () => {
    const d = decision();
    d.proposed_by_type = "user";
    const html = decisionHtml(d, true, true);
    expect(html).toContain("Un membre de l'équipe");
    // Hors bloc « Informations techniques » (exception C2 : déplié à la demande).
    expect(html.replace(/<details class="decision-tech">[\s\S]*?<\/details>/, "")).not.toContain(A1.slice(0, 8));
  });

  it("contenu décision affiché, infos techniques repliées", () => {
    const html = decisionHtml(decision(), true, true);
    expect(html).toContain("Après analyse, nous choisissons Godot 4.3");
    expect(html).toContain("Informations techniques");
    expect(html).toContain("Identifiant");
    expect(html).toContain("Lisible");
    expect(html).toContain("DEC-0049");
  });

  it("liens projet et tâche quand présents", () => {
    const html = decisionHtml(decision(), true, true);
    expect(html).toContain(`href="#/projects/${P1}"`);
    expect(html).toContain(`href="#/tasks/${T1}"`);
  });

  it("sans projet ni tâche : tirets", () => {
    const d = decision("d1", "proposed", null, null);
    const html = decisionHtml(d, true, true);
    expect(html).toContain("Projet: —");
    expect(html).toContain("Tâche: —");
  });

  it("proposed, admin : Accepter et Remplacer disponibles (DEC-0098)", () => {
    const html = decisionHtml(decision("d1", "proposed"), true, true);
    expect(html).toContain('data-decision-accept="d1"');
    expect(html).toContain("Accepter");
    expect(html).toContain('data-decision-supersede="d1"');
    expect(html).toContain("Remplacer");
    expect(html).not.toContain("disabled");
  });

  it("proposed, non-admin : boutons présents mais désactivés", () => {
    const html = decisionHtml(decision("d1", "proposed"), true, false);
    expect(html).toContain('data-decision-accept="d1"');
    expect(html).toContain("disabled");
    expect(html).toContain("Réservé au rôle admin");
  });

  it("accepted, admin : seul Remplacer est disponible, pas Accepter", () => {
    const html = decisionHtml(decision("d2", "accepted"), true, true);
    expect(html).not.toContain("data-decision-accept");
    expect(html).toContain('data-decision-supersede="d2"');
  });

  it("superseded : terminal, aucune action de transition", () => {
    const html = decisionHtml(decision("d3", "superseded"), true, true);
    expect(html).not.toContain("data-decision-accept");
    expect(html).not.toContain("data-decision-supersede");
  });

  it("non authed : aucune action de transition affichée", () => {
    const html = decisionHtml(decision("d1", "proposed"), false, false);
    expect(html).not.toContain("data-decision-accept");
    expect(html).not.toContain("data-decision-supersede");
  });
});

describe("decisionsHtml", () => {
  it("vide global : état contextualisé + bouton création si authed", () => {
    const html = decisionsHtml([], true, true);
    expect(html).toContain("Aucune décision globale");
    expect(html).toContain("Créer une décision");
    expect(html).not.toContain("undefined");
    expect(html).toContain('id="create-decision-btn"');
    expect(html).not.toContain('href="#create-decision"');
  });

  it("vide project-scopé : message projet, pas de bouton création si pas authed", () => {
    const html = decisionsHtml([], false, false, P1);
    expect(html).toContain("Voir les décisions globales");
    expect(html).toContain("liée à ce projet");
    expect(html).not.toContain("Créer une décision");
  });

  it("erreur : notice danger", () => {
    const html = decisionsHtml([], true, true, undefined, "coupure");
    expect(html).toContain("ds-notice--danger");
    expect(html).toContain("Décisions indisponibles");
  });

  it("liste : toolbar avec bouton création, lignes complètes", () => {
    const html = decisionsHtml([decision("d1"), decision("d2", "accepted")], true, true);
    expect(html).toContain("Créer une décision");
    expect(html).toContain("Choisir le moteur de rendu");
    expect(html).toContain("DEC-0049");
    expect(html).toMatch(/Proposée|Acceptée/);
  });

  it("CSP : aucun style ni handler inline", () => {
    const html = decisionsHtml([decision()], true, true);
    expect(html).not.toMatch(/\sstyle\s*=/i);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });
});

describe("createDecisionFormHtml", () => {
  it("champs FR obligatoires + projet optionnel en global", () => {
    const html = createDecisionFormHtml(true, undefined, "user-uuid");
    expect(html).toContain("Projet (optionnel)");
    expect(html).toContain("Tâche (optionnel)");
    expect(html).toContain("Titre");
    expect(html).toContain("Contenu");
    expect(html).toContain("Proposé par");
    expect(html).toContain("ID du proposant");
    expect(html).toContain("Créer la décision");
    expect(html).toContain("Annuler");
    expect(html).toContain("idempotency_key");
  });

  it("projectId fixé : affiché, pas de champ input", () => {
    const html = createDecisionFormHtml(true, P1, "user-uuid");
    expect(html).toContain("Projet:");
    expect(html).toContain(P1);
    expect(html).not.toContain('name="project_id"');
  });

  it("lecture seule : bouton submit disabled", () => {
    const html = createDecisionFormHtml(false, undefined, "user-uuid");
    expect(html).toContain("disabled");
  });
});

describe("decisionsTabsHtml", () => {
  it("deux onglets avec rôles ARIA, un seul sélectionné", () => {
    const html = decisionsTabsHtml("review");
    expect(html).toContain('role="tablist"');
    expect(html).toContain('role="tabpanel"');
    expect(html).toContain('id="decisions-main-tab-review"');
    expect(html).toContain('id="decisions-main-tab-decisions"');
    expect(html).toContain("À valider");
    expect(html).toContain("Décisions");
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1);
    expect(html).toContain("hidden");
  });
});

describe("decisions.css responsive", () => {
  const css = readFileSync(join(__dirname, "decisions.css"), "utf-8");

  it("mobile 640px : pas de grille forcée, empilement naturel", () => {
    expect(css).toMatch(/@media[^{]*max-width:\s*640px/);
    expect(css).not.toMatch(/repeat\s*\(\s*2/);
  });

  it("900px : meta en colonne, actions pleine largeur", () => {
    expect(css).toMatch(/@media[^{]*max-width:\s*900px/);
    expect(css).toContain("flex-direction: column");
    expect(css).toContain("flex: 1");
  });

  it("aucun style inline ni handler dans le CSS", () => {
    expect(css).not.toContain("<style");
    expect(css).not.toContain("onClick");
  });

  it("informations techniques : grid 2 colonnes lisible", () => {
    expect(css).toContain("grid-template-columns: max-content 1fr");
  });

  it("boîte de réception : cartes, point de couleur, filtres et compteurs stylés", () => {
    expect(css).toContain(".review-card {");
    expect(css).toContain(".review-card-dot");
    expect(css).toContain(".review-card-context");
    expect(css).toContain(".review-card-impact");
    expect(css).toContain(".review-filters {");
    expect(css).toContain(".review-counters {");
    expect(css).toContain(".review-hero {");
  });

  it("aucune animation ni transition sur les cartes (mouvement réduit)", () => {
    const cardBlock = /\.review-card \{[^}]*\}/.exec(css)?.[0] ?? "";
    expect(cardBlock).not.toContain("transition");
    expect(cardBlock).not.toContain("animation");
  });
});