// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createFixtureRoadmapDataSource } from "../roadmapData";
import { roadmapFixtureProjectIds } from "../roadmapFixtures";
import { ApiError, parseErrorBody } from "../api";
import { isRoadmapManagerRole, roadmapCurrentStepHtml, roadmapDonePhasesHtml, roadmapExecutionHtml, roadmapFullyDone, roadmapLifecycleHtml, roadmapPhaseStripHtml, roadmapPlanHtml, roadmapPrintHtml, roadmapProposalsHtml, roadmapShellHtml, roadmapStepDetailHtml, roadmapSwitcherHtml, renderRoadmapInto } from "./roadmap";
import type { Roadmap, RoadmapDataSource, RoadmapPendingProposal } from "../roadmapTypes";

describe("Roadmap workspace", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="ds-toast-region"></div><main id="root"></main>`;
  });

  async function render(projectId: string): Promise<HTMLElement> {
    const root = document.getElementById("root") as HTMLElement;
    await renderRoadmapInto(root, {
      dataSource: createFixtureRoadmapDataSource(),
      projectId,
      projectName: "Projet test",
    });
    return root;
  }

  it("présente l'absence de roadmap comme un choix normal", async () => {
    const root = await render(roadmapFixtureProjectIds.noRoadmap);
    expect(root.textContent).toContain("Ce projet fonctionne sans roadmap");
    expect(root.textContent).toContain("uniquement si un plan par étapes vous aide");
    expect(root.textContent).not.toContain("mal configuré");
  });

  it("couvre roadmap vide, draft, proposed, active, completed, large, bloquée et partielle", async () => {
    const cases: Array<[string, string]> = [
      [roadmapFixtureProjectIds.empty, "Le plan est vide"],
      [roadmapFixtureProjectIds.draft, "Brouillon"],
      [roadmapFixtureProjectIds.proposed, "Proposition à examiner"],
      [roadmapFixtureProjectIds.active, "Active"],
      [roadmapFixtureProjectIds.completed, "Terminée"],
      [roadmapFixtureProjectIds.large, "Phase 11"],
      [roadmapFixtureProjectIds.blocked, "Bloquée"],
      [roadmapFixtureProjectIds.partial, "Roadmap partielle"],
    ];
    for (const [projectId, expected] of cases) {
      const root = await render(projectId);
      expect(root.textContent, projectId).toContain(expected);
    }
  });

  it("sépare Plan et Exécution sans créer un second Kanban", async () => {
    const source = createFixtureRoadmapDataSource();
    const roadmap = await source.load(roadmapFixtureProjectIds.active);
    expect(roadmap).not.toBeNull();
    if (roadmap === null) return;
    const plan = roadmapPlanHtml(roadmap, roadmap.current_step_key ?? null);
    const execution = roadmapExecutionHtml(roadmap, roadmap.current_step_key ?? null);
    expect(plan).toContain("Plan par phases");
    expect(execution).toContain("Disponible maintenant");
    expect(execution).toContain("En attente");
    expect(`${plan}${execution}`).not.toContain("kanban");
  });

  it("rend le détail humain avant les informations techniques", async () => {
    const source = createFixtureRoadmapDataSource();
    const roadmap = await source.load(roadmapFixtureProjectIds.active);
    const step = roadmap?.phases?.flatMap((phase) => phase.steps ?? []).find((item) => item.key === "P1.2") ?? null;
    expect(roadmap).not.toBeNull();
    if (roadmap === null) return;
    const html = roadmapStepDetailHtml(step, roadmap);
    expect(html).toContain("Objectif");
    expect(html).toContain("Tâches");
    expect(html).toContain("Critères d'acceptation");
    expect(html).toContain("Dépendances");
    expect(html).toContain("Informations techniques");
    expect(html.indexOf("Objectif")).toBeLessThan(html.indexOf("Informations techniques"));
  });

  it("expose le flux de proposition complet sur une fixture clairement signalée", async () => {
    const root = await render(roadmapFixtureProjectIds.proposed);
    expect(root.textContent).toContain("Données de démonstration");
    expect(root.textContent).toContain("Modifications proposées");
    expect(root.querySelectorAll("[data-review]")).toHaveLength(3);
    expect(root.textContent).toContain("Approuver");
    expect(root.textContent).toContain("Demander des changements");
    expect(root.textContent).toContain("Rejeter");
    (root.querySelector('[data-review="approve"]') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(root.textContent).toContain("Active"));
  });

  it("présente une proposition de révision IA (auteur, base, diff) et exige un commentaire pour la refuser", async () => {
    const root = await render(roadmapFixtureProjectIds.active);
    expect(root.querySelector(".roadmap-proposal-review")).not.toBeNull();
    expect(root.textContent).toContain("Proposition à examiner");
    expect(root.textContent).toContain("Clarifier la première étape");
    expect(root.textContent).toContain("version de base");
    expect(root.textContent).toContain("Modifications proposées");
    expect(root.querySelectorAll("[data-proposal-review]")).toHaveLength(3);

    (root.querySelector('[data-proposal-review="request_changes"]') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(root.textContent).toContain("Commentaire requis"));
    expect(root.querySelector(".roadmap-proposal-review")).not.toBeNull();

    (root.querySelector("[data-proposal-comment]") as HTMLTextAreaElement).value = "À revoir";
    (root.querySelector('[data-proposal-review="request_changes"]') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(root.querySelector(".roadmap-proposal-review")).toBeNull());
  });

  it("approuve une proposition de révision et aligne la version approuvée", async () => {
    const root = await render(roadmapFixtureProjectIds.active);
    (root.querySelector('[data-proposal-review="approve"]') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(root.querySelector(".roadmap-proposal-review")).toBeNull());
  });

  it("permet la création manuelle locale depuis un projet sans roadmap", async () => {
    const root = await render(roadmapFixtureProjectIds.noRoadmap);
    (root.querySelector("[data-create-roadmap]") as HTMLButtonElement).click();
    const dialog = root.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    const title = root.querySelector<HTMLInputElement>('[name="title"]');
    expect(title).not.toBeNull();
    if (title === null) return;
    title.value = "Plan manuel";
    (root.querySelector("[data-roadmap-editor]") as HTMLFormElement).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(root.textContent).toContain("Plan manuel"));
  });

  it("déclenche l'export PDF via la vue d'impression", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    const root = await render(roadmapFixtureProjectIds.active);
    (root.querySelector("[data-export-pdf]") as HTMLButtonElement).click();
    expect(print).toHaveBeenCalledOnce();
  });

  it("prépare un PDF lisible avec phases, objectifs, tâches, dépendances, critères, statut et progression", async () => {
    const roadmap = await createFixtureRoadmapDataSource().load(roadmapFixtureProjectIds.active);
    expect(roadmap).not.toBeNull();
    if (roadmap === null) return;
    const html = roadmapPrintHtml(roadmap);
    for (const expected of ["Phase 1", "Objectif", "Tâches", "Dépendances", "Critères d'acceptation", "Statut", "Progression"]) {
      expect(html).toContain(expected);
    }
    expect(html).not.toContain(roadmap.project_id);
    expect(html).not.toContain("machine_id");
    expect(html).not.toContain("actor_id");
  });

  it("garde les identifiants et la provenance hors de l'aperçu principal", async () => {
    const source = createFixtureRoadmapDataSource();
    const roadmap = await source.load(roadmapFixtureProjectIds.active);
    expect(roadmap).not.toBeNull();
    if (roadmap === null) return;
    const html = roadmapShellHtml(roadmap, "plan", roadmap.current_step_key ?? null);
    expect(html).toContain("Informations techniques");
    expect(html).not.toContain("provider");
    expect(html).not.toContain("harness");
  });
});

describe("Roadmap switcher and targeted roadmap", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="ds-toast-region"></div><main id="root"></main>`;
  });

  it("n'affiche pas de sélecteur pour une seule roadmap", async () => {
    const source = createFixtureRoadmapDataSource();
    const roadmap = await source.load(roadmapFixtureProjectIds.proposed);
    expect(roadmap).not.toBeNull();
    expect(roadmapSwitcherHtml(roadmap!, [{ id: roadmap!.id, title: roadmap!.title, status: roadmap!.status }])).toBe("");
  });

  it("ouvre la roadmap ciblée et la relit avec son propre id", async () => {
    const fixture = createFixtureRoadmapDataSource();
    const proposed = (await fixture.load(roadmapFixtureProjectIds.proposed))!;
    const active = { ...(await fixture.load(roadmapFixtureProjectIds.active))!, project_id: proposed.project_id };
    const load = vi.fn(async (_projectId: string, roadmapId?: string) => (roadmapId === proposed.id ? proposed : active));
    const loadPendingProposal = vi.fn(async () => null);
    const source: RoadmapDataSource = {
      ...fixture,
      load,
      loadPendingProposal,
      listRoadmaps: async () => [
        { id: active.id, title: active.title, status: "active" },
        { id: proposed.id, title: proposed.title, status: "proposed" },
      ],
    };
    const root = document.getElementById("root") as HTMLElement;
    await renderRoadmapInto(root, { dataSource: source, projectId: proposed.project_id, projectName: "P", roadmapId: proposed.id });
    expect(load).toHaveBeenCalledWith(proposed.project_id, proposed.id);
    expect(loadPendingProposal).toHaveBeenCalledWith(proposed.project_id, proposed.id);
    expect(root.textContent).toContain("Modifications proposées");
    const links = [...root.querySelectorAll<HTMLAnchorElement>(".roadmap-switch-link")];
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      `#/projects/${active.project_id}/roadmap/${active.id}`,
      `#/projects/${proposed.project_id}/roadmap/${proposed.id}`,
    ]);
    expect(links[1]?.getAttribute("aria-current")).toBe("page");
  });
});

describe("Roadmap lifecycle and review errors", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="ds-toast-region"></div><main id="root"></main>`;
  });

  const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));
  const click = (root: HTMLElement, selector: string): void => {
    const button = root.querySelector<HTMLButtonElement>(selector);
    expect(button, selector).not.toBeNull();
    button?.click();
  };

  async function render(source: RoadmapDataSource, projectId: string, canManageLifecycle?: boolean): Promise<HTMLElement> {
    const root = document.getElementById("root") as HTMLElement;
    await renderRoadmapInto(root, { dataSource: source, projectId, projectName: "P", canManageLifecycle });
    return root;
  }

  it("clôture une roadmap active après confirmation", async () => {
    const root = await render(createFixtureRoadmapDataSource(), roadmapFixtureProjectIds.active);
    click(root, '[data-lifecycle="complete"]');
    expect(root.textContent).toContain("Clôturer cette roadmap ?");
    click(root, "[data-lifecycle-confirm]");
    await flush();
    expect(root.querySelector(".roadmap-title-line")?.textContent).toContain("Terminée");
    expect(root.querySelector('[data-lifecycle="reopen"]')).not.toBeNull();
  });

  it("exige un motif pour rouvrir, puis rouvre", async () => {
    const source = createFixtureRoadmapDataSource();
    const transition = vi.spyOn(source, "transitionRoadmap");
    const root = await render(source, roadmapFixtureProjectIds.completed);
    click(root, '[data-lifecycle="reopen"]');
    click(root, "[data-lifecycle-confirm]");
    await flush();
    expect(root.textContent).toContain("Motif requis");
    expect(transition).not.toHaveBeenCalled();
    (root.querySelector("[data-lifecycle-comment]") as HTMLTextAreaElement).value = "Étape oubliée";
    click(root, "[data-lifecycle-confirm]");
    await flush();
    expect(transition).toHaveBeenCalledWith(expect.objectContaining({ status: "completed" }), "reopen", "Étape oubliée");
    expect(root.querySelector(".roadmap-title-line")?.textContent).toContain("Active");
  });

  it("annuler referme la confirmation sans rien envoyer", async () => {
    const source = createFixtureRoadmapDataSource();
    const transition = vi.spyOn(source, "transitionRoadmap");
    const root = await render(source, roadmapFixtureProjectIds.active);
    click(root, '[data-lifecycle="archive"]');
    click(root, "[data-lifecycle-cancel]");
    expect(root.querySelector(".roadmap-lifecycle-confirm")).toBeNull();
    expect(transition).not.toHaveBeenCalled();
  });

  it("affiche un 409 de transition et relit la roadmap sur version_conflict", async () => {
    const fixture = createFixtureRoadmapDataSource();
    const load = vi.fn(fixture.load);
    const source: RoadmapDataSource = {
      ...fixture,
      load,
      transitionRoadmap: async () => {
        throw new ApiError(parseErrorBody(409, { detail: { error_code: "version_conflict", server_version: 9 } }));
      },
    };
    const root = await render(source, roadmapFixtureProjectIds.active);
    load.mockClear();
    click(root, '[data-lifecycle="complete"]');
    click(root, "[data-lifecycle-confirm]");
    await flush();
    expect(root.querySelector("[data-lifecycle-error] [role=alert]")?.textContent).toContain("version_conflict");
    expect(load).toHaveBeenCalledTimes(1);
    expect(root.querySelector(".roadmap-title-line")?.textContent).toContain("Active");
  });

  it("masque les actions de cycle de vie sans rôle admin/developer", async () => {
    const root = await render(createFixtureRoadmapDataSource(), roadmapFixtureProjectIds.active, false);
    expect(root.querySelector("[data-lifecycle]")).toBeNull();
    expect(isRoadmapManagerRole("developer")).toBe(true);
    expect(isRoadmapManagerRole("agent")).toBe(false);
    expect(isRoadmapManagerRole(null)).toBe(false);
  });

  it("signale une roadmap active à 100 % et propose de la clôturer", async () => {
    const roadmap = (await createFixtureRoadmapDataSource().load(roadmapFixtureProjectIds.active))!;
    const done = { ...roadmap, progress: { done: 3, total: 4, skipped: 1, ratio: 1 } };
    expect(roadmapFullyDone(done)).toBe(true);
    expect(roadmapFullyDone(roadmap)).toBe(false);
    const html = roadmapLifecycleHtml(done, { allowed: true });
    expect(html).toContain("Toutes les étapes sont terminées");
    expect(html).toContain('data-lifecycle="complete"');
    expect(roadmapLifecycleHtml(done, { allowed: false })).not.toContain("data-lifecycle=");
  });

  it("affiche active_roadmap_exists à l'approbation sans changer le statut", async () => {
    const fixture = createFixtureRoadmapDataSource();
    const proposed = (await fixture.load(roadmapFixtureProjectIds.proposed))!;
    const source: RoadmapDataSource = {
      ...fixture,
      listRoadmaps: async () => [
        { id: "r-old", title: "Ancien plan", status: "active" },
        { id: proposed.id, title: proposed.title, status: "proposed" },
      ],
      reviewProposal: async () => {
        throw new ApiError(parseErrorBody(409, { detail: { error_code: "active_roadmap_exists" } }));
      },
    };
    const root = await render(source, roadmapFixtureProjectIds.proposed);
    click(root, '[data-review="approve"]');
    await flush();
    const alert = root.querySelector("[data-review-error] [role=alert]");
    expect(alert?.textContent).toContain("déjà active");
    expect(alert?.querySelector("a")?.getAttribute("href")).toBe(`#/projects/${roadmapFixtureProjectIds.proposed}/roadmap/r-old`);
    expect(root.querySelector(".roadmap-title-line")?.textContent).toContain("À examiner");
    expect(root.querySelector<HTMLButtonElement>('[data-review="approve"]')?.disabled).toBe(false);
  });

  it("affiche une erreur réseau à l'approbation", async () => {
    const source: RoadmapDataSource = {
      ...createFixtureRoadmapDataSource(),
      reviewProposal: async () => {
        throw new TypeError("Failed to fetch");
      },
    };
    const root = await render(source, roadmapFixtureProjectIds.proposed);
    click(root, '[data-review="approve"]');
    await flush();
    expect(root.querySelector("[data-review-error] [role=alert]")?.textContent).toContain("Impossible de joindre le serveur");
    expect(root.querySelector(".roadmap-title-line")?.textContent).toContain("À examiner");
  });
});

describe("Roadmap recentrée sur l'étape courante (P05-roadmaps)", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="ds-toast-region"></div><main id="root"></main>`;
  });

  async function renderDefault(projectId: string): Promise<HTMLElement> {
    const root = document.getElementById("root") as HTMLElement;
    await renderRoadmapInto(root, {
      dataSource: createFixtureRoadmapDataSource(),
      projectId,
      projectName: "Projet test",
    });
    return root;
  }

  function doneRoadmap(): Roadmap {
    const step = (key: string, state: "done" | "in_progress" | "not_started", available = false) => ({
      key,
      title: `Étape ${key}`,
      objective: `Objectif ${key}`,
      context: null,
      instructions: null,
      acceptance_criteria: [`Critère ${key}`],
      notes: null,
      metadata: {},
      depends_on: [],
      tasks: [],
      state,
      available,
      waiting_on: [],
      linked_tasks: [],
      criteria_checked: [],
    });
    return {
      id: "r-focus",
      project_id: "p-focus",
      title: "Plan focus",
      objective: "Recentrer",
      status: "active",
      revision_no: 2,
      approved_revision_no: 1,
      context: null,
      metadata: {},
      progress: { done: 2, total: 3, skipped: 0, ratio: 2 / 3 },
      current_step_key: "P2.1",
      phases: [
        { key: "P1", title: "Phase terminée", objective: null, steps: [step("P1.1", "done"), step("P1.2", "done")] },
        { key: "P2", title: "Phase courante", objective: null, steps: [step("P2.1", "in_progress", true)] },
      ],
    };
  }

  it("s'ouvre en Exécution avec l'étape courante et ses critères visibles", async () => {
    const root = await renderDefault(roadmapFixtureProjectIds.active);
    const executionTab = root.querySelector('[data-mode="execution"]');
    expect(executionTab?.getAttribute("aria-selected")).toBe("true");
    const current = root.querySelector("[data-current-step]");
    expect(current).not.toBeNull();
    expect(root.querySelector(".roadmap-phase-strip")).not.toBeNull();
    expect(root.querySelector(".roadmap-current-criteria")?.textContent).toContain("Critères d'acceptation");
    expect(root.textContent).toContain("Disponible maintenant");
    expect(root.textContent).toContain("En attente");
  });

  it("affiche le bandeau des phases avec la position courante", async () => {
    const roadmap = (await createFixtureRoadmapDataSource().load(roadmapFixtureProjectIds.active))!;
    const html = roadmapPhaseStripHtml(roadmap);
    expect(html).toContain("roadmap-phase-strip");
    expect(html).toContain("Phase");
    expect(roadmapCurrentStepHtml(roadmap, roadmap.current_step_key ?? null)).toContain("data-current-step");
  });

  it("replit les phases terminées en un seul élément tout en les gardant dans le DOM", () => {
    const roadmap = doneRoadmap();
    const plan = roadmapPlanHtml(roadmap, "P2.1");
    expect(plan).toContain("1 phase terminée");
    expect(plan).toContain("Phase terminée");
    expect(plan).toContain("<details");
    const execution = roadmapExecutionHtml(roadmap, "P2.1");
    expect(execution).toContain("roadmap-done-phases");
    expect(execution).toContain("Phase terminée");
    expect(roadmapDonePhasesHtml(roadmap, "P2.1")).toContain("masquée");
  });

  it("regroupe proposition et révision en un seul bloc sans perdre de carte", async () => {
    const source = createFixtureRoadmapDataSource();
    const proposed = (await source.load(roadmapFixtureProjectIds.proposed))!;
    const pending: RoadmapPendingProposal = {
      roadmapId: proposed.id,
      roadmapVersion: 1,
      revision: {
        id: "rev-group",
        roadmap_id: proposed.id,
        revision_no: 2,
        kind: "proposal",
        status: "pending",
        base_revision_no: 1,
        summary: "Révision groupée",
        provenance: { origin: "ai_proposal", actor_type: "agent", actor_id: "a", agent_id: "a", machine_id: null, at: "2026-09-20T11:00:00Z" },
        reviewed_by_user_id: null,
        reviewed_at: null,
        review_comment: null,
      },
      diff: { base_revision_no: 1, proposal_revision_no: 2, entries: [] },
    };
    const grouped = roadmapProposalsHtml(proposed, pending);
    expect(grouped).toContain("roadmap-proposals");
    expect(grouped).toContain("Propositions (2)");
    expect(grouped).toContain("roadmap-proposal-review");
    const single = roadmapProposalsHtml(proposed, null);
    expect(single).toContain("roadmap-proposals");
    expect(roadmapProposalsHtml({ ...proposed, status: "active" }, null)).toBe("");
  });

  it("garde l'onglet Plan complet après recentrage", async () => {
    const root = await renderDefault(roadmapFixtureProjectIds.active);
    (root.querySelector('[data-mode="plan"]') as HTMLButtonElement).click();
    expect(root.querySelector('[data-mode="plan"]')?.getAttribute("aria-selected")).toBe("true");
    expect(root.querySelector(".roadmap-timeline")).not.toBeNull();
  });
});
