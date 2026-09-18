/**
 * UI-4 — Workspace projet : cadre stable, navigation locale à deep links,
 * vue d'ensemble résumée. DOM-free : chaînes pures.
 */
import { describe, expect, it } from "vitest";
import {
  OVERVIEW_PREVIEW_LIMIT,
  PROJECT_TABS,
  projectAttentionItems,
  projectOverviewHtml,
  workspaceHeaderHtml,
  workspaceTabsHtml,
} from "./projectDetail";

const ID = "11111111-2222-4333-8444-555555555555";

const project = {
  id: ID,
  slug: "phare",
  name: "Jeu Phare",
  description: "Le jeu principal du studio",
  archived: false,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-10T10:00:00Z",
  version: 7,
} as never;

const task = (id: string, status: string, title = `Tâche ${id}`) =>
  ({
    id,
    project_id: ID,
    title,
    description: null,
    status,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-10T10:00:00Z",
    version: 1,
  }) as never;

const claim = (resource_path: string, expires_at: string) =>
  ({
    id: `claim-${resource_path}`,
    project_id: ID,
    task_id: null,
    resource_path,
    resource_type: "file",
    claimed_by_machine_id: "m1",
    ttl_seconds: 3600,
    status: "active",
    created_at: "2026-09-10T10:00:00Z",
    expires_at,
  }) as never;

const NOW = new Date("2026-09-12T10:00:00Z").getTime();

describe("PROJECT_TABS", () => {
  it("cinq onglets adossés à des capacités réelles, jamais décoratifs", () => {
    expect(PROJECT_TABS.map((t) => t.id)).toEqual(["overview", "tasks", "claims", "activity", "decisions"]);
  });
});

describe("workspaceTabsHtml", () => {
  const html = workspaceTabsHtml(ID, "activity");

  it("rend les deep links de chaque section", () => {
    expect(html).toContain(`href="#/projects/${ID}"`);
    expect(html).toContain(`href="#/projects/${ID}/tasks"`);
    expect(html).toContain(`href="#/projects/${ID}/claims"`);
    expect(html).toContain(`href="#/projects/${ID}/activity"`);
    expect(html).toContain(`href="#/projects/${ID}/decisions"`);
  });

  it("onglets accessibles : tablist, sélection unique, page courante", () => {
    expect(html).toContain('role="tablist"');
    expect(html).toContain('role="tab"');
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1);
    expect(html).toContain('aria-current="page"');
    expect(html).toContain("Activité");
    expect(html).toContain("data-ws-tabs");
  });

  it("CSP : aucun handler inline", () => {
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
  });
});

describe("workspaceHeaderHtml", () => {
  const html = workspaceHeaderHtml(project);

  it("identifie clairement le projet : nom, description, état, retour", () => {
    expect(html).toContain("<h1>Jeu Phare</h1>");
    expect(html).toContain("Le jeu principal du studio");
    expect(html).toContain("Actif");
    expect(html).toContain('href="#/projects"');
    expect(html).toContain("phare");
  });

  it("technique secondaire : UUID/version/dates dans le détail replié", () => {
    expect(html).toContain("Informations techniques");
    expect(html).toContain(ID);
    const [foreground] = html.split("Informations techniques");
    expect(foreground).not.toContain(ID);
    expect(foreground).not.toContain(">7<");
  });
});

describe("projectAttentionItems", () => {
  it("remonte bloquées et expirations proches, ignore le reste", () => {
    const state = {
      active_tasks: [task("t1", "blocked"), task("t2", "in_progress")],
      active_claims: [
        claim("bientôt.tscn", "2026-09-12T20:00:00Z"),
        claim("loin.tscn", "2026-10-12T10:00:00Z"),
      ],
    } as never;
    const items = projectAttentionItems(state, NOW);
    expect(items).toHaveLength(2);
    expect(items[0]).toContain("bloquée");
    expect(items[1]).toContain("bientôt.tscn");
  });

  it("vide quand rien ne demande d'attention", () => {
    const state = {
      active_tasks: [task("t2", "in_progress")],
      active_claims: [claim("loin.tscn", "2026-10-12T10:00:00Z")],
    } as never;
    expect(projectAttentionItems(state, NOW)).toEqual([]);
  });
});

describe("projectOverviewHtml", () => {
  it("résume sans dupliquer les onglets : pas de Kanban, table, timeline ou décisions", () => {
    const state = {
      active_tasks: [task("t1", "in_progress", "Optimiser les éclairages")],
      active_claims: [claim("scenes/niveau.tscn", "2026-09-12T20:00:00Z")],
    } as never;
    const html = projectOverviewHtml(project, state, NOW);
    expect(html).toContain("Tâches actives (1)");
    expect(html).toContain("Réservations actives (1)");
    expect(html).toContain("Optimiser les éclairages");
    expect(html).toContain("scenes/niveau.tscn");
    expect(html).toContain(`href="#/projects/${ID}/tasks"`);
    expect(html).toContain(`href="#/projects/${ID}/claims"`);
    expect(html).toContain(`href="#/projects/${ID}/activity"`);
    expect(html).toContain(`href="#/projects/${ID}/decisions"`);
    expect(html).not.toContain("<table");
    expect(html).not.toContain("kanban");
    expect(html).not.toContain(`>${ID}<`);
  });

  it("limite les résumés à 5 avec reliquat et signale l'attention", () => {
    const state = {
      active_tasks: Array.from({ length: 7 }, (_, i) => task(`t${i}`, i === 0 ? "blocked" : "created")),
      active_claims: [],
    } as never;
    const html = projectOverviewHtml(project, state, NOW);
    expect(html.match(/ds-list-title/g)?.length).toBeLessThanOrEqual(OVERVIEW_PREVIEW_LIMIT + 1);
    expect(html).toContain("+ 2 autre(s)");
    expect(html).toContain("À surveiller");
    expect(OVERVIEW_PREVIEW_LIMIT).toBe(5);
  });

  it("états vides contextualisés, jamais de jargon endpoint", () => {
    const html = projectOverviewHtml(project, { active_tasks: [], active_claims: [] } as never, NOW);
    expect(html).toContain("Aucune tâche active");
    expect(html).toContain("Aucune réservation active");
    expect(html).toContain("Rien ne demande d'attention");
    expect(html).not.toMatch(/GET \//);
  });
});
