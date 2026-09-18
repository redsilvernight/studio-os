/**
 * UI-8 — Decisions & Review : surface unifiée (Review Queue + Décisions).
 *
 * Tests DOM-free (vitest, node) : assertions sur les chaînes produites +
 * lecture statique de decisions.css pour le responsive.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  REVIEW_KIND_LABEL,
  REVIEW_KIND_TONE,
  DECISION_STATUS_LABEL,
  DECISION_STATUS_TONE,
  PROPOSER_TYPE_LABEL,
  reviewQueueItemDetail,
  reviewItemHtml,
  reviewQueueHtml,
  decisionHtml,
  decisionsHtml,
  createDecisionFormHtml,
  decisionsTabsHtml,
  type ReviewQueue,
  type Decision,
} from "./decisionsV2";

const P1 = "11111111-2222-4333-8444-555555555555";
const P2 = "22222222-3333-4444-9555-666666666666";
const A1 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
const T1 = "tttttttt-uuuu-vvvv-wwww-xxxxxxxxxxxx";

function aiWorkItem(id = "rw1", title = "Relire la sortie agent"): ReviewQueue {
  return {
    items: [{
      kind: "ai_work_review",
      id,
      project_id: P1,
      task_id: T1,
      title,
      agent_id: A1,
      requested_at: "2026-09-10T10:00:00Z",
    }],
    generated_at: "2026-09-10T10:00:00Z",
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

function mixedQueue(): ReviewQueue {
  return {
    items: [
      aiWorkItem().items[0]!,
      decisionProposalItem().items[0]!,
      conflictItem().items[0]!,
      buildItem().items[0]!,
      prItem().items[0]!,
    ],
    generated_at: "2026-09-10T10:00:00Z",
  };
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

describe("Labels FR (source unique)", () => {
  it("REVIEW_KIND_LABEL : tous les kinds ont un libellé FR", () => {
    expect(REVIEW_KIND_LABEL.ai_work_review).toBe("Travail IA");
    expect(REVIEW_KIND_LABEL.decision_proposal).toBe("Proposition de décision");
    expect(REVIEW_KIND_LABEL.resource_conflict).toBe("Conflit de réservation");
    expect(REVIEW_KIND_LABEL.build_failure).toBe("Échec de build");
    expect(REVIEW_KIND_LABEL.pr_ready).toBe("PR ouverte");
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
  it("détail selon kind sans inventer d'action", () => {
    expect(reviewQueueItemDetail(aiWorkItem().items[0]!)).toContain("agent");
    expect(reviewQueueItemDetail(decisionProposalItem().items[0]!)).toBe("DEC-0049");
    expect(reviewQueueItemDetail(conflictItem().items[0]!)).toBe("scenes/level_01.tscn");
    expect(reviewQueueItemDetail(buildItem().items[0]!)).toBe("ci sur main");
    expect(reviewQueueItemDetail(prItem().items[0]!)).toBe("PR #42 feat/ui-8 → main");
  });
});

describe("reviewItemHtml", () => {
  it("ai_work_review : badge IA, actions Approuver/Demander des modifications si authed", () => {
    const html = reviewItemHtml(aiWorkItem().items[0]!, true);
    expect(html).toContain("ds-badge--ai");
    expect(html).toContain("Travail IA");
    expect(html).toContain('data-review-approve="rw1"');
    expect(html).toContain("Approuver");
    expect(html).toContain('data-review-changes="rw1"');
    expect(html).toContain("Demander des modifications");
    expect(html).not.toContain("disabled");
  });

  it("ai_work_review : actions désactivées sans auth", () => {
    const html = reviewItemHtml(aiWorkItem().items[0]!, false);
    expect(html).toContain("disabled");
  });

  it("decision_proposal : aucun bouton d'action, message explicite", () => {
    const html = reviewItemHtml(decisionProposalItem().items[0]!, true);
    expect(html).toContain("Proposition de décision");
    expect(html).toContain("Aucune action disponible dans cette interface");
    expect(html).not.toContain("data-review-approve");
    expect(html).not.toContain("data-review-changes");
  });

  it("resource_conflict : aucun bouton, message explicite", () => {
    const html = reviewItemHtml(conflictItem().items[0]!, true);
    expect(html).toContain("Conflit de réservation");
    expect(html).toContain("Aucune action disponible dans cette interface");
  });

  it("build_failure : aucun bouton, message explicite", () => {
    const html = reviewItemHtml(buildItem().items[0]!, true);
    expect(html).toContain("Échec de build");
    expect(html).toContain("Aucune action disponible dans cette interface");
  });

  it("pr_ready : aucun bouton, message explicite", () => {
    const html = reviewItemHtml(prItem().items[0]!, true);
    expect(html).toContain("PR ouverte");
    expect(html).toContain("Aucune action disponible dans cette interface");
  });

  it("toutes les infos clés présentes : titre, projet, tâche, detail, date, infos techniques repliées", () => {
    const html = reviewItemHtml(aiWorkItem().items[0]!, true);
    expect(html).toContain("Relire la sortie agent");
    expect(html).toContain(P1.slice(0, 8));
    expect(html).toContain(T1.slice(0, 8));
    expect(html).toContain("agent");
    expect(html).toContain("2026"); // fmtTime uses fr-FR locale
    expect(html).toContain("Informations techniques");
    expect(html).toContain("<details");
    expect(html).toContain("Identifiant");
    expect(html).toContain("Kind");
    expect(html).toContain("Projet");
    expect(html).toContain("Tâche");
    expect(html).toContain("Agent");
    expect(html).not.toContain("style=");
    expect(html).not.toContain("onClick");
  });
});

describe("reviewQueueHtml", () => {
  it("vide : état positif FR avec lien vers décisions", () => {
    const html = reviewQueueHtml({ items: [], generated_at: "" }, true);
    expect(html).toContain("Rien à examiner");
    expect(html).toContain("Aucun élément n'attend une décision humaine");
    expect(html).toContain("Voir les décisions");
    expect(html).toContain('href="#/decisions"');
  });

  it("erreur : notice danger sans jargon technique", () => {
    const html = reviewQueueHtml(null, true, undefined, "HTTP 500 · coupure");
    expect(html).toContain("ds-notice--danger");
    expect(html).toContain("File d'examen indisponible");
    expect(html).not.toContain("Error 500");
  });

  it("project-scopé : scope affiché, lien vers global", () => {
    const html = reviewQueueHtml(mixedQueue(), true, P1);
    expect(html).toContain("projet 11111111…");
    expect(html).toContain('href="#/decisions"');
    expect(html).toContain("5 élément(s) à examiner");
  });

  it("global : scope affiché, lien vers projet si projectId", () => {
    const html = reviewQueueHtml(mixedQueue(), true);
    expect(html).toContain("globale");
  });

  it("CSP : aucun style ni handler inline", () => {
    const html = reviewQueueHtml(mixedQueue(), true);
    expect(html).not.toMatch(/\sstyle\s*=/i);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });
});

describe("decisionHtml", () => {
  it("statut traduit + tonalité, pas de clé backend visible", () => {
    const html = decisionHtml(decision("d1", "proposed"), true);
    expect(html).toContain("Proposée");
    expect(html).toContain("ds-badge--info");
    expect(html).not.toContain("proposed");
  });

  it("accepted : tonalité success", () => {
    const html = decisionHtml(decision("d2", "accepted"), true);
    expect(html).toContain("Acceptée");
    expect(html).toContain("ds-badge--success");
  });

  it("superseded : tonalité warning", () => {
    const html = decisionHtml(decision("d3", "superseded"), true);
    expect(html).toContain("Remplacée");
    expect(html).toContain("ds-badge--warning");
  });

  it("proposé par agent : lien vers fiche agent + badge IA", () => {
    const html = decisionHtml(decision(), true);
    expect(html).toContain('href="#/agents/');
    expect(html).toContain("ds-badge--ai");
  });

  it("proposé par user : type + ID court", () => {
    const d = decision();
    d.proposed_by_type = "user";
    const html = decisionHtml(d, true);
    expect(html).toContain("Utilisateur");
    expect(html).toContain(A1.slice(0, 8));
  });

  it("contenu décision affiché, infos techniques repliées", () => {
    const html = decisionHtml(decision(), true);
    expect(html).toContain("Après analyse, nous choisissons Godot 4.3");
    expect(html).toContain("Informations techniques");
    expect(html).toContain("Identifiant");
    expect(html).toContain("Lisible");
    expect(html).toContain("DEC-0049");
  });

  it("liens projet et tâche quand présents", () => {
    const html = decisionHtml(decision(), true);
    expect(html).toContain(`href="#/projects/${P1}"`);
    expect(html).toContain(`href="#/tasks/${T1}"`);
  });

  it("sans projet ni tâche : tirets", () => {
    const d = decision("d1", "proposed", null, null);
    const html = decisionHtml(d, true);
    expect(html).toContain("Projet: —");
    expect(html).toContain("Tâche: —");
  });
});

describe("decisionsHtml", () => {
  it("vide global : état contextualisé + bouton création si authed", () => {
    const html = decisionsHtml([], true);
    expect(html).toContain("Aucune décision");
    expect(html).toContain("globales");
    expect(html).toContain("Créer une décision");
    expect(html).toContain('href="#create-decision"');
  });

  it("vide project-scopé : message projet, pas de bouton création si pas authed", () => {
    const html = decisionsHtml([], false, P1);
    expect(html).toContain("projet 11111111…");
    expect(html).toContain("liée à ce projet");
    expect(html).not.toContain("Créer une décision");
  });

  it("erreur : notice danger", () => {
    const html = decisionsHtml([], true, undefined, "coupure");
    expect(html).toContain("ds-notice--danger");
    expect(html).toContain("Décisions indisponibles");
  });

  it("liste : toolbar avec bouton création, lignes complètes", () => {
    const html = decisionsHtml([decision("d1"), decision("d2", "accepted")], true);
    expect(html).toContain("Créer une décision");
    expect(html).toContain("Choisir le moteur de rendu");
    expect(html).toContain("DEC-0049");
    expect(html).toMatch(/Proposée|Acceptée/);
  });

  it("CSP : aucun style ni handler inline", () => {
    const html = decisionsHtml([decision()], true);
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
    expect(html).toContain("À examiner");
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
});