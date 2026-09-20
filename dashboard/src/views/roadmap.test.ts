// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createFixtureRoadmapDataSource } from "../roadmapData";
import { roadmapFixtureProjectIds } from "../roadmapFixtures";
import { roadmapExecutionHtml, roadmapPlanHtml, roadmapPrintHtml, roadmapShellHtml, roadmapStepDetailHtml, renderRoadmapInto } from "./roadmap";

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
