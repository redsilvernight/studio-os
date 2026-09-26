import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { globalOverflow, go, login, newCaptured } from "./support/ui16-stub";

const roadmapFixtureProjectIds = {
  noRoadmap: "fixture-no-roadmap",
  proposed: "fixture-proposed-roadmap",
  active: "fixture-active-roadmap",
  large: "fixture-large-roadmap",
} as const;

function project(id: string) {
  return {
    id,
    slug: "roadmap-fixture",
    name: "Studi'OS Roadmaps",
    description: "Projet de validation de la vue Roadmap.",
    archived: false,
    created_at: "2026-09-20T10:00:00Z",
    updated_at: "2026-09-20T12:00:00Z",
    version: 1,
  };
}

interface OpenOptions {
  /** transition -> error_code answered with 409 by the stubbed transitions endpoint. */
  transitionFailure?: Record<string, string>;
  /** Identity role answered by /auth/me (lifecycle actions need admin/developer). */
  role?: string;
}

async function openRoadmap(page: Page, projectId: string, options: OpenOptions = {}): Promise<void> {
  await login(page, "#/projects", newCaptured(), options.role === undefined ? {} : { role: options.role });
  await page.route(new RegExp(`/api/v1/projects/${projectId}/state$`), (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ project_id: projectId, active_tasks: [], active_claims: [], generated_at: "2026-09-20T12:00:00Z" }),
    }),
  );
  await page.route(new RegExp(`/api/v1/projects/${projectId}$`), (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project(projectId)) }),
  );
  // Authenticated sessions read the canonical API: mock it with compact
  // API-shaped payloads so the suite exercises the real API datasource path.
  type ApiRoadmap = Record<string, unknown>;
  const makeStep = (key: string, title: string, extra: Record<string, unknown> = {}): ApiRoadmap => ({
    id: `st-${key}`,
    roadmap_id: "r",
    phase_id: "ph",
    key,
    position: 0,
    title,
    state: "not_started",
    available: true,
    waiting_on: [],
    acceptance_criteria: ["Critère OK"],
    depends_on: [],
    tasks: [],
    linked_tasks: [],
    criteria_checked: [],
    ...extra,
  });
  const makeRoadmap = (projectId: string, id: string, status: string, extra: Record<string, unknown> = {}): ApiRoadmap => ({
    id,
    project_id: projectId,
    title: "Sprint de démo",
    objective: "Valider la vue",
    status,
    revision_no: 2,
    approved_revision_no: status === "active" ? 1 : null,
    version: 7,
    progress: { done: 1, total: 3, skipped: 0, ratio: 0.33 },
    current_step_key: "P1.2",
    phases: [
      {
        id: "ph1",
        roadmap_id: id,
        key: "P1",
        position: 0,
        title: "Prototype",
        progress: { done: 1, total: 3, skipped: 0, ratio: 0.33 },
        steps: [
          makeStep("P1.1", "Boucle de jeu", { state: "done", available: false }),
          makeStep("P1.2", "Sons"),
          makeStep("P1.3", "Finition", { available: false, waiting_on: ["P1.2"] }),
        ],
      },
    ],
    ...extra,
  });
  const phases11 = Array.from({ length: 11 }, (_, index) => ({
    id: `ph${index + 1}`,
    roadmap_id: "r-large",
    key: `P${index + 1}`,
    position: index,
    title: `Phase ${index + 1}`,
    progress: { done: 0, total: 1, skipped: 0, ratio: 0 },
    steps: [makeStep(`P${index + 1}.1`, `Étape ${index + 1}`)],
  }));
  const served = new Map<string, ApiRoadmap>([
    [
      roadmapFixtureProjectIds.active,
      makeRoadmap(roadmapFixtureProjectIds.active, "r-active", "active"),
    ],
    [
      roadmapFixtureProjectIds.proposed,
      {
        ...makeRoadmap(roadmapFixtureProjectIds.proposed, "r-proposed", "proposed", { title: "Plan proposé" }),
        phases: [
          {
            id: "ph1",
            roadmap_id: "r-proposed",
            key: "P1",
            position: 0,
            title: "Prototype",
            progress: { done: 0, total: 1, skipped: 0, ratio: 0 },
            steps: [{ ...makeStep("P1.1", "Boucle de jeu"), tasks: [{ hydration_key: "k1", title: "Tâche prévue" }] }],
          },
        ],
      },
    ],
    [
      roadmapFixtureProjectIds.large,
      {
        ...makeRoadmap(roadmapFixtureProjectIds.large, "r-large", "active", { title: "Grand plan" }),
        phases: phases11,
      },
    ],
  ]);
  const summaryOf = (roadmap: ApiRoadmap): Record<string, unknown> => ({
    id: roadmap.id,
    project_id: roadmap.project_id,
    title: roadmap.title,
    status: roadmap.status,
    revision_no: roadmap.revision_no,
    approved_revision_no: roadmap.approved_revision_no,
    progress: roadmap.progress,
    current_step_key: roadmap.current_step_key,
  });
  await page.route(new RegExp(`/api/v1/projects/${projectId}/roadmaps`), (route) => {
    const roadmap = served.get(projectId);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(roadmap === undefined ? [] : [summaryOf(roadmap)]),
    });
  });
  await page.route(new RegExp("/api/v1/roadmaps/[^/]+$"), (route) => {
    const roadmapId = route.request().url().split("/").pop() ?? "";
    const found = [...served.values()].find((roadmap) => roadmap.id === roadmapId) ?? null;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(found) });
  });
  await page.route(new RegExp("/api/v1/roadmaps/import"), async (route) => {
    const body = (route.request().postDataJSON() ?? {}) as { document?: { title?: string } };
    const imported: ApiRoadmap = {
      ...makeRoadmap(projectId, "roadmap-imported", "draft", { title: body.document?.title ?? "Plan importé" }),
      phases: [],
    };
    served.set(projectId, imported);
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(imported) });
  });
  await page.route(new RegExp("/api/v1/roadmaps/[^/]+/transitions"), async (route) => {
    const roadmapId = route.request().url().split("/").slice(-2, -1)[0] ?? "";
    const body = (route.request().postDataJSON() ?? {}) as { transition?: string };
    const entry = [...served.entries()].find(([, roadmap]) => roadmap.id === roadmapId);
    const current = entry?.[1];
    const failure = options.transitionFailure?.[body.transition ?? ""];
    if (failure !== undefined) {
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: { error_code: failure } }) });
      return;
    }
    const targets: Record<string, string> = { approve: "active", reject: "archived", complete: "completed", reopen: "active", archive: "archived", activate: "active" };
    const transitioned: ApiRoadmap = {
      ...makeRoadmap(projectId, roadmapId, "draft", { title: typeof current?.title === "string" ? current.title : "Plan" }),
      status: targets[body.transition ?? ""] ?? "draft",
      phases: (current?.phases as unknown[]) ?? [],
    };
    if (entry !== undefined) served.set(entry[0], transitioned);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(transitioned) });
  });
  // P8: pending revision proposal on the active roadmap, with its diff.
  let pendingRevision = projectId === roadmapFixtureProjectIds.active;
  const revision = {
    id: "rev-1",
    roadmap_id: "r-active",
    revision_no: 3,
    kind: "proposal",
    status: "pending",
    base_revision_no: 1,
    summary: "Clarifier les sons",
    provenance: {
      origin: "ai_proposal",
      actor_type: "agent",
      actor_id: "agent-1",
      agent_id: "agent-1",
      machine_id: null,
      at: "2026-09-20T11:00:00Z",
    },
    reviewed_by_user_id: null,
    reviewed_at: null,
    review_comment: null,
  };
  const diff = {
    base_revision_no: 1,
    proposal_revision_no: 3,
    entries: [{ scope: "step", key: "P1.2", change: "changed", fields: ["title"] }],
  };
  await page.route(new RegExp("/api/v1/roadmaps/[^/]+/revisions"), (route) => {
    const roadmapId = route.request().url().split("/").slice(-2, -1)[0] ?? "";
    const body = pendingRevision && roadmapId === "r-active" ? [revision] : [];
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route(new RegExp("/api/v1/roadmaps/[^/]+/proposals/[^/]+/diff"), (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(diff) }),
  );
  await page.route(new RegExp("/api/v1/roadmaps/[^/]+/proposals/[^/]+/review"), async (route) => {
    pendingRevision = false;
    const current = served.get(projectId);
    const updated: ApiRoadmap = {
      ...(current ?? makeRoadmap(projectId, "r-active", "active")),
      revision_no: 3,
      approved_revision_no: 3,
    };
    served.set(projectId, updated);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(updated) });
  });
  await go(page, `#/projects/${projectId}/roadmap`);
  await expect(page.locator("#workspace-panel")).toBeVisible();
}

test.describe("Roadmap workspace", () => {
  test("Plan, Exécution et détail d'étape restent simples et accessibles", async ({ page }) => {
    await openRoadmap(page, roadmapFixtureProjectIds.active);
    await expect(page.getByRole("tab", { name: "Roadmap" })).toHaveAttribute("aria-current", "page");
    await expect(page.locator(".roadmap-fixture-note")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Prototype" })).toBeVisible();
    await page.getByRole("tab", { name: "Exécution" }).click();
    await expect(page.getByRole("heading", { name: /Disponible maintenant/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /En attente/ })).toBeVisible();
    await page.getByRole("button", { name: /Sons/ }).first().click();
    await expect(page.getByRole("heading", { name: "Critères d'acceptation" })).toBeVisible();
    const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(axe.violations.filter((violation) => violation.impact === "critical" || violation.impact === "serious")).toEqual([]);
  });

  test("projet sans roadmap reste complet et non alarmant", async ({ page }) => {
    await openRoadmap(page, roadmapFixtureProjectIds.noRoadmap);
    await expect(page.getByText("Ce projet fonctionne sans roadmap")).toBeVisible();
    await expect(page.getByRole("button", { name: "Créer une roadmap" })).toBeVisible();
    await expect(page.locator("#workspace-panel [role=alert]")).toHaveCount(0);
  });

  test("proposition : résumé puis approbation locale explicite", async ({ page }) => {
    await openRoadmap(page, roadmapFixtureProjectIds.proposed);
    await expect(page.getByText("Modifications proposées")).toBeVisible();
    await expect(page.getByText("Tâches prévues")).toBeVisible();
    await page.getByRole("button", { name: "Approuver" }).click();
    await expect(page.locator("span.ds-badge", { hasText: "Active" })).toBeVisible();
    await expect(page.getByText("Décision enregistrée.")).toBeVisible();
  });

  test("approbation bloquée par une autre roadmap active : erreur visible, statut inchangé", async ({ page }) => {
    await openRoadmap(page, roadmapFixtureProjectIds.proposed, { transitionFailure: { approve: "active_roadmap_exists" } });
    await page.getByRole("button", { name: "Approuver" }).click();
    await expect(page.locator("[data-review-error] [role=alert]")).toContainText("déjà active");
    await expect(page.locator("span.ds-badge", { hasText: "À examiner" })).toBeVisible();
  });

  test("cycle de vie : clôturer puis rouvrir avec motif obligatoire", async ({ page }) => {
    await openRoadmap(page, roadmapFixtureProjectIds.active, { role: "admin" });
    await page.getByRole("button", { name: "Clôturer", exact: true }).click();
    await page.getByRole("button", { name: "Confirmer : Clôturer" }).click();
    await expect(page.locator(".roadmap-title-line .ds-badge")).toHaveText("Terminée");
    await page.getByRole("button", { name: "Rouvrir", exact: true }).click();
    await page.getByRole("button", { name: "Confirmer : Rouvrir" }).click();
    await expect(page.getByText("Motif requis.")).toBeVisible();
    await page.locator("[data-lifecycle-comment]").fill("Étape oubliée");
    await page.getByRole("button", { name: "Confirmer : Rouvrir" }).click();
    await expect(page.locator(".roadmap-title-line .ds-badge")).toHaveText("Active");
  });

  test("cycle de vie : un 409 de clôture reste affiché", async ({ page }) => {
    await openRoadmap(page, roadmapFixtureProjectIds.active, { role: "developer", transitionFailure: { complete: "invalid_state" } });
    await page.getByRole("button", { name: "Clôturer", exact: true }).click();
    await page.getByRole("button", { name: "Confirmer : Clôturer" }).click();
    await expect(page.locator("[data-lifecycle-error] [role=alert]")).toContainText("pas possible dans l'état actuel");
    await expect(page.locator(".roadmap-title-line .ds-badge")).toHaveText("Active");
  });

  test("proposition de révision IA : diff, commentaire obligatoire, décision", async ({ page }) => {
    await openRoadmap(page, roadmapFixtureProjectIds.active);
    await expect(page.locator(".roadmap-proposal-review")).toBeVisible();
    await expect(page.getByText("Clarifier les sons")).toBeVisible();
    await expect(page.getByText("Modifications proposées")).toBeVisible();
    await page.getByRole("button", { name: "Demander des changements" }).click();
    await expect(page.getByText("Commentaire requis")).toBeVisible();
    await page.locator("[data-proposal-comment]").fill("Pas encore prêt");
    await page.getByRole("button", { name: "Demander des changements" }).click();
    await expect(page.locator(".roadmap-proposal-review")).toHaveCount(0);
    await expect(page.getByText("Décision enregistrée.")).toBeVisible();
  });

  test("import JSON P1 et export JSON neutre", async ({ page }) => {
    await openRoadmap(page, roadmapFixtureProjectIds.active);
    const imported = {
      format: "studio.roadmap/v1",
      title: "Plan importé",
      objective: "Valider le round-trip",
      context: null,
      metadata: {},
      phases: [],
      exported_at: null,
      revision_no: null,
    };
    await page.locator("[data-import-file]").setInputFiles({ name: "roadmap.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(imported)) });
    await expect(page.getByRole("heading", { name: "Plan importé" })).toBeVisible();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Exporter JSON" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("studio-roadmap.json");
  });

  test("mobile 375 : grande roadmap sans débordement global", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await openRoadmap(page, roadmapFixtureProjectIds.large);
    await expect(page.locator(".roadmap-timeline h3", { hasText: "Phase 11" })).toBeVisible();
    expect(await globalOverflow(page)).toBe(0);
  });

  test("génère un PDF A4 réel depuis la fixture P1", async ({ page }) => {
    await openRoadmap(page, roadmapFixtureProjectIds.active);
    await page.emulateMedia({ media: "print" });
    const outputDir = path.resolve(process.cwd(), "..", "output", "pdf");
    await mkdir(outputDir, { recursive: true });
    await page.pdf({
      path: path.join(outputDir, "roadmap-studio-os-fixture-p1.pdf"),
      format: "A4",
      printBackground: true,
      margin: { top: "14mm", right: "12mm", bottom: "14mm", left: "12mm" },
    });
  });
});
