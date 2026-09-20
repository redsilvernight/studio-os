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

async function openRoadmap(page: Page, projectId: string): Promise<void> {
  await login(page, "#/projects", newCaptured());
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
  await go(page, `#/projects/${projectId}/roadmap`);
  await expect(page.locator("#workspace-panel")).toBeVisible();
}

test.describe("Roadmap workspace", () => {
  test("Plan, Exécution et détail d'étape restent simples et accessibles", async ({ page }) => {
    await openRoadmap(page, roadmapFixtureProjectIds.active);
    await expect(page.getByRole("tab", { name: "Roadmap" })).toHaveAttribute("aria-current", "page");
    await expect(page.getByText("Données de démonstration")).toBeVisible();
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
    await expect(page.getByText("Active", { exact: true })).toBeVisible();
    await expect(page.getByText(/fixture de cette session/)).toBeVisible();
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
    await expect(page.getByText("Phase 11", { exact: true })).toBeVisible();
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
