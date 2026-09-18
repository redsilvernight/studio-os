/**
 * UI-3 — Accueil : densité limite haute, sections résumées, 0 perte
 * fonctionnelle (actions ai_work_review conservées, discrètes).
 *
 * DOM-free (suite vitest en environnement node) : assertions sur les
 * chaînes produites + lecture statique de overview.css pour le responsive.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  HOME_PROJECT_LIMIT,
  HOME_REVIEW_LIMIT,
  HOME_WORK_LIMIT,
  homeHealthHtml,
  homeLoadingHtml,
  homeMetricsHtml,
  homePageHtml,
  homeProjectsHtml,
  homeReviewHtml,
  homeTasksHtml,
  homeTransferSignalHtml,
  pickHomeProjects,
  reviewActionsHtml,
  reviewQueueItemDetail,
  type HomeData,
} from "./overview";

const project = (id: string, name: string, archived = false, updated_at = "2026-09-10T10:00:00Z") =>
  ({ id, name, slug: `slug-${id}`, description: null, archived, created_at: updated_at, updated_at, version: 3 }) as never;

const task = (id: string, status: string, project_id = "p1", title = `Tâche ${id}`) =>
  ({ id, project_id, title, description: null, status, created_at: "2026-09-10T10:00:00Z", updated_at: "2026-09-10T10:00:00Z", version: 1 }) as never;

const aiItem = (id: string, title = "Relire la sortie agent") =>
  ({
    kind: "ai_work_review",
    id,
    project_id: "p1",
    task_id: "t1",
    title,
    agent_id: "11111111-2222-4333-8444-555555555555",
    requested_at: "2026-09-10T10:00:00Z",
  }) as never;

const decisionItem = (id: string) =>
  ({
    kind: "decision_proposal",
    id,
    project_id: null,
    task_id: null,
    readable_id: "DEC-0049",
    title: "Choisir le moteur de rendu",
    proposed_by_type: "agent",
    requested_at: "2026-09-10T10:00:00Z",
  }) as never;

const transfer = (id: string, status: string) =>
  ({
    id,
    transfer_code: `code-${id}`,
    sender_user_id: "u1",
    category: "temporary",
    filename: "f.bin",
    object_key: "k",
    content_type: "application/octet-stream",
    size_bytes: 10,
    status,
    created_at: "2026-09-10T10:00:00Z",
  }) as never;

function fullData(): HomeData {
  return {
    health: { reachable: true },
    projects: { ok: true, value: [project("p1", "Phare"), project("p2", "Digue")] },
    tasks: { ok: true, value: [task("t1", "in_progress", "p1", "Optimiser les éclairages")] },
    reviewQueue: { ok: true, value: { items: [aiItem("a1")], generated_at: "2026-09-10T10:00:00Z" } as never },
    transfers: { ok: true, value: [] },
    authed: true,
  };
}

describe("homeLoadingHtml", () => {
  it("montre un squelette DS en français, jamais un texte brut", () => {
    const html = homeLoadingHtml();
    expect(html).toContain("ds-skeleton");
    expect(html).toContain("Accueil");
    expect(html).not.toContain("Loading");
  });
});

describe("homePageHtml nominal", () => {
  it("rend l'en-tête, le résumé et les quatre sections avec leurs liens Voir tout", () => {
    const html = homePageHtml(fullData());
    expect(html).toContain("<h1>Accueil</h1>");
    expect(html).toContain("Projets actifs");
    expect(html).toContain("Tâches en cours");
    expect(html).toContain("À examiner");
    expect(html).toContain("Projets");
    expect(html).toContain("Travail en cours");
    expect(html).toContain("href=\"#/projects\"");
    expect(html).toContain("href=\"#/tasks\"");
    expect(html).toContain("href=\"#/decisions\"");
    expect(html).toContain("Système opérationnel");
  });

  it("ne rend aucun tableau : ni Kanban complet, ni table transferts", () => {
    const html = homePageHtml(fullData());
    expect(html).not.toContain("<table");
    expect(html).not.toContain("kanban");
    expect(html).not.toMatch(/TODO|IN PROGRESS|BLOCKED/);
  });

  it("ne fuit aucune information technique (endpoints, UUID, versions, horodatages)", () => {
    const html = homePageHtml(fullData());
    expect(html).not.toMatch(/GET \/healthz|GET \/projects|GET \/tasks|GET \/review-queue|GET \/transfers/);
    expect(html).not.toContain("11111111-2222-4333-8444-555555555555");
    expect(html).not.toMatch(/slug-p1|v3|version/i);
    expect(html).not.toContain("Derived");
  });

  it("ne produit aucun style inline ni handler inline (CSP DEC-0061)", () => {
    const html = homePageHtml(fullData());
    expect(html).not.toMatch(/\sstyle\s*=/i);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toContain("javascript:");
  });
});

describe("homeMetricsHtml", () => {
  it("affiche les trois compteurs, tiret quand l'examen est inconnu", () => {
    expect(homeMetricsHtml(2, 4, 5)).toContain("5");
    expect(homeMetricsHtml(2, 4, null)).toContain("—");
  });
});

describe("homeProjectsHtml", () => {
  it("limite à 3 projets, non archivés d'abord", () => {
    const projects = [
      project("old", "Vieux", true, "2026-09-12T10:00:00Z"),
      project("a", "A", false, "2026-09-08T10:00:00Z"),
      project("b", "B", false, "2026-09-11T10:00:00Z"),
      project("c", "C", false, "2026-09-09T10:00:00Z"),
    ];
    const html = homeProjectsHtml({ ok: true, value: projects as never });
    expect(html).toContain("#/projects");
    expect(html).toContain("B");
    expect(html).toContain("C");
    expect(html).toContain("A");
    expect(html).not.toContain(">Vieux<");
    expect(html.match(/ds-list-item/g)).toHaveLength(HOME_PROJECT_LIMIT);
  });

  it("affiche la description utile et le badge Archivé, jamais de slug/UUID", () => {
    const withDesc = { ...(project("p1", "Phare") as unknown as Record<string, unknown>), description: "Jeu phare" } as never;
    const html = homeProjectsHtml({
      ok: true,
      value: [withDesc],
    });
    expect(html).toContain("Jeu phare");
    expect(html).not.toContain("slug-p1");
  });

  it("état vide contextualisé et erreur humaine discrète", () => {
    expect(homeProjectsHtml({ ok: true, value: [] })).toContain("Aucun projet");
    const err = homeProjectsHtml({ ok: false, message: "HTTP 500 · boom" });
    expect(err).toContain("Projets indisponibles");
    expect(err).not.toContain("Error 500");
  });
});

describe("pickHomeProjects", () => {
  it("3 max, non archivés d'abord puis updated_at décroissant", () => {
    const picked = pickHomeProjects([
      project("z", "Z", true, "2026-09-12T10:00:00Z"),
      project("a", "A", false, "2026-09-08T10:00:00Z"),
      project("b", "B", false, "2026-09-11T10:00:00Z"),
    ] as never);
    expect(picked.map((p) => p.id)).toEqual(["b", "a", "z"]);
    expect(HOME_PROJECT_LIMIT).toBe(3);
  });
});

describe("homeTasksHtml", () => {
  it("limite à 5, exclut les terminées, montre projet et statut en français", () => {
    const tasks = [
      task("t1", "in_progress", "p1", "Optimiser les éclairages"),
      task("t2", "completed", "p1", "Finie"),
      task("t3", "blocked", "p2", "Caméra Android"),
      task("t4", "created", "p1", "T4"),
      task("t5", "created", "p1", "T5"),
      task("t6", "created", "p1", "T6"),
      task("t7", "created", "p1", "T7"),
    ];
    const html = homeTasksHtml(
      { ok: true, value: tasks as never },
      [project("p1", "Apotheosis"), project("p2", "BLFinder")] as never,
    );
    expect(html.match(/ds-list-item/g)).toHaveLength(HOME_WORK_LIMIT);
    expect(html).not.toContain("Finie");
    expect(html).not.toContain("T7");
    expect(html).toContain("Apotheosis");
    expect(html).toContain("En cours");
    expect(html).toContain("Bloquée");
    expect(html).toContain("href=\"#/tasks/t1\"");
    expect(html).toContain("Voir toutes les tâches");
  });

  it("état vide contextualisé et erreur humaine", () => {
    expect(homeTasksHtml({ ok: true, value: [] }, []).toString()).toContain("Rien en cours");
    expect(homeTasksHtml({ ok: false, message: "coupure" }, [])).toContain("Tâches indisponibles");
  });
});

describe("reviewQueueItemDetail", () => {
  it("décrit honnêtement chaque kind sans inventer d'action", () => {
    expect(reviewQueueItemDetail(aiItem("a1"))).toContain("agent");
    expect(reviewQueueItemDetail(decisionItem("d1"))).toBe("DEC-0049");
    expect(
      reviewQueueItemDetail({ kind: "resource_conflict", resource_path: "scenes/level_01.tscn" } as never),
    ).toBe("scenes/level_01.tscn");
    expect(
      reviewQueueItemDetail({ kind: "build_failure", workflow_name: "ci", branch: "main" } as never),
    ).toBe("ci on main");
    expect(
      reviewQueueItemDetail({ kind: "pr_ready", pr_number: 7, head_branch: "feat", base_branch: "main" } as never),
    ).toBe("PR #7 feat → main");
  });
});

describe("reviewActionsHtml (0 perte fonctionnelle)", () => {
  it("conserve Approuver / Demander des modifications pour ai_work_review", () => {
    const html = reviewActionsHtml(aiItem("a1"), true);
    expect(html).toContain("data-review-approve");
    expect(html).toContain("data-review-changes");
    expect(html).not.toContain("disabled");
  });

  it("désactive sans jeton et ne propose rien pour les autres kinds", () => {
    expect(reviewActionsHtml(aiItem("a1"), false)).toContain("disabled");
    expect(reviewActionsHtml(decisionItem("d1"), true)).toBe("");
  });
});

describe("homeReviewHtml", () => {
  it("affiche le total, 3 éléments max et le reliquat", () => {
    const items = [aiItem("a1"), decisionItem("d1"), aiItem("a2"), decisionItem("d2")];
    const html = homeReviewHtml({ ok: true, value: { items, generated_at: "" } as never }, true);
    expect(html).toContain("4 élément(s) à examiner");
    expect(html.match(/ds-list-item/g)).toHaveLength(HOME_REVIEW_LIMIT);
    expect(html).toContain("+ 1 autre(s)");
    expect(html).toContain("Voir les décisions");
  });

  it("état vide et erreur discrète", () => {
    expect(homeReviewHtml({ ok: true, value: { items: [], generated_at: "" } as never }, true)).toContain(
      "Rien à examiner",
    );
    expect(homeReviewHtml({ ok: false, message: "coupure" }, true)).toContain("File d'examen indisponible");
  });
});

describe("homeHealthHtml", () => {
  it("compacte : opérationnel ou indisponible, sans détail technique", () => {
    expect(homeHealthHtml({ reachable: true })).toContain("Système opérationnel");
    const down = homeHealthHtml({ reachable: false });
    expect(down).toContain("Système indisponible");
    expect(down).not.toContain("/healthz");
    expect(down).not.toMatch(/HTTP|unreachable/i);
  });
});

describe("homeTransferSignalHtml", () => {
  it("signale uniquement les envois réellement en cours, avec lien", () => {
    const html = homeTransferSignalHtml({
      ok: true,
      value: [transfer("a", "created"), transfer("b", "ready")] as never,
    });
    expect(html).toContain("Transfert en cours");
    expect(html).toContain("href=\"#/transfers\"");
    expect(html).not.toContain("code-a");
    expect(html).not.toContain("<table");
  });

  it("silencieux quand rien n'est en cours ou en erreur", () => {
    expect(homeTransferSignalHtml({ ok: true, value: [transfer("b", "ready")] as never })).toBe("");
    expect(homeTransferSignalHtml({ ok: true, value: [] })).toBe("");
    expect(homeTransferSignalHtml({ ok: false, message: "coupure" })).toBe("");
  });
});

describe("homePageHtml non authentifié", () => {
  it("garde l'en-tête et la santé, propose la connexion sans jargon", () => {
    const html = homePageHtml({ ...fullData(), authed: false });
    expect(html).toContain("<h1>Accueil</h1>");
    expect(html).toContain("Connectez-vous");
    expect(html).not.toContain("machine token");
  });
});

describe("overview.css responsive", () => {
  const css = readFileSync(join(__dirname, "overview.css"), "utf-8");

  it("empile en une colonne sur mobile, sans grille 2x2 forcée", () => {
    expect(css).toMatch(/@media[^{]*max-width:\s*640px/);
    expect(css).not.toMatch(/repeat\s*\(\s*2/);
  });

  it("aucun style inline attendu : classes seules", () => {
    expect(css).not.toContain("<style");
  });
});
