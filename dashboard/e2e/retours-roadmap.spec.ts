import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { globalOverflow, go, login, newCaptured, P1, M1 } from "./support/ui16-stub";

const longToken = "https://studio.example/" + "chemin-sans-espace".repeat(28);
const longText = `Description de la phase et de ses tâches.\nDeuxième ligne : ${longToken}`;

function roadmap(id: string, status: string, done: boolean) {
  const progress = { done: done ? 2 : 1, total: 2, skipped: 0, ratio: done ? 1 : 0.5 };
  return {
    id, project_id: P1, title: `${status === "active" ? "Plan actif" : "Historique"} ${longToken}`,
    objective: longText, context: longText, status, revision_no: 1, approved_revision_no: 1,
    version: 1, progress, current_step_key: done ? null : "P2.1",
    phases: [true, done].map((finished, index) => ({
      id: `${id}-phase-${index}`, key: `P${index + 1}`, title: `Phase ${index + 1} ${longToken}`,
      objective: longText, position: index,
      progress: { done: finished ? 1 : 0, total: 1, skipped: 0, ratio: finished ? 1 : 0 },
      steps: [{
        id: `${id}-step-${index}`, key: `P${index + 1}.1`, title: `Étape ${index + 1} ${longToken}`,
        objective: longText, context: longText, state: finished ? "done" : "in_progress",
        available: !finished, waiting_on: [], depends_on: [], acceptance_criteria: [longText],
        criteria_checked: [], linked_tasks: [], tasks: [{ hydration_key: `task-${index}`, title: longToken, description: longText }],
      }],
    })),
  };
}

async function open(page: Page, done = false): Promise<void> {
  await login(page, "#/projects", newCaptured());
  const active = roadmap("retours-active", "active", done);
  const history = roadmap("retours-history", "archived", true);
  const plans = [active, history, ...Array.from({ length: 20 }, (_, i) => roadmap(`retours-${i}`, "completed", true))];
  await page.route(new RegExp(`/api/v1/projects/${P1}/roadmaps$`), (route) => route.fulfill({ json: plans }));
  await page.route(/\/api\/v1\/roadmaps\/[^/]+$/, (route) => route.fulfill({ json: plans.find((plan) => route.request().url().endsWith(`/${plan.id}`)) }));
  await page.route(/\/api\/v1\/roadmaps\/[^/]+\/revisions/, (route) => route.fulfill({ json: [] }));
  await go(page, `#/projects/${P1}/roadmap`);
  await expect(page.locator(".roadmap-view")).toBeVisible();
}

for (const done of [false, true]) {
  test(`phases ${done ? "toutes" : "partiellement"} terminées : clavier et consultation dans les deux lectures`, async ({ page }) => {
    await open(page, done);
    for (const mode of ["execution", "plan"]) {
      await page.locator(`[data-mode="${mode}"]`).click();
      const phases = page.locator("[data-done-phase]");
      await expect(phases).toHaveCount(done ? 2 : 1);
      const first = phases.first();
      await expect(first).not.toHaveAttribute("open", "");
      await first.locator("summary").focus();
      await page.keyboard.press("Enter");
      await expect(first).toHaveAttribute("open", "");
      const step = first.locator("[data-step-key]").first();
      await expect(step).toBeVisible();
      await step.click();
      await expect(page.locator(".roadmap-detail")).toContainText(longText);
      await expect(page.locator("[data-done-phase]").first()).toHaveAttribute("open", "");
      await page.locator("[data-done-phase] summary").first().focus();
      await page.keyboard.press("Space");
      await expect(page.locator("[data-done-phase]").first()).not.toHaveAttribute("open", "");
    }
  });
}

test("sélection compacte : statut et progression, historique chargé au clavier", async ({ page }) => {
  await open(page);
  const select = page.getByLabel("Roadmap à consulter");
  await expect(select.locator("option")).toHaveCount(22);
  await expect(select.locator("option").first()).toContainText("Active — 50 %");
  await expect(select.locator("option").nth(1)).toContainText("Archivée — 100 %");
  await select.focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/roadmap\/retours-history$/);
  await expect(page.locator(".roadmap-header h2")).toContainText("Historique");
  await expect(select).toHaveValue("retours-history");
});

test("textes longs et multilignes sans débordement à 360, 768 et 1440 px", async ({ page }, testInfo) => {
  await open(page);
  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const mode of ["execution", "plan"]) {
      await page.locator(`[data-mode="${mode}"]`).click();
      await page.locator("[data-done-phase] summary").first().click();
      await page.locator('[data-done-phase] [data-step-key="P1.1"]').click();
      expect(await globalOverflow(page), `${mode} à ${width}px`).toBeLessThanOrEqual(1);
      const overflow = await page.locator(".roadmap-view").evaluate((root) => [...root.querySelectorAll<HTMLElement>("h2, h3, p, li, button, summary")].filter((node) => node.checkVisibility()).filter((node) => node.scrollWidth - node.clientWidth > 1).map((node) => ({ tag: node.tagName, className: node.className, text: node.textContent?.slice(0, 80), overflow: node.scrollWidth - node.clientWidth })));
      expect(overflow, `${mode} à ${width}px`).toEqual([]);
      await page.locator("[data-done-phase] summary").first().click();
    }
  }
  const report = await new AxeBuilder({ page }).include(".roadmap-view").analyze();
  expect(report.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""))).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("retours-roadmap-wide.png"), fullPage: true });
});

test("exécutions : statut, tâche, poste-agent et résultat visibles, diagnostics au clavier", async ({ page }, testInfo) => {
  await login(page, "#/projects", newCaptured());
  await page.route(new RegExp(`/api/v1/projects/${P1}/mission`), (route) => route.fulfill({ json: {
    project_id: P1, generated_at: "2026-10-20T12:00:00Z", window_hours: 168,
    counts: { by_verdict: { running: 1, waiting_human: 1, done: 1, failed: 1 }, total: 4 },
    next_cursor: null, truncated: false,
    runs: ["running", "waiting_human", "done", "failed"].map((verdict, i) => ({
      run_id: `run-${i}`, source: "launch", task_id: `task-${i}`, task_title: `Exécution ${i} ${longToken}`,
      machine_id: M1, machine_status: "online", verdict,
      reasons: [verdict === "waiting_human" ? "review_requested" : verdict === "failed" ? "launch_failed" : verdict === "done" ? "handed_off" : "process_running"],
      active_claims: 0, data_gaps: [], protocol_state: verdict === "done" ? "handed_off" : "open",
      launch: { id: `launch-${i}`, status: "running", reason_code: "none", harness_id: "codex", created_at: "2026-10-20T10:00:00Z" },
      session: null, handoff: verdict === "done" ? { ai_work_id: "work-1", status: "completed", summary: longText } : null,
      updated_at: "2026-10-20T12:00:00Z",
    })),
  } }));
  await go(page, `#/projects/${P1}/mission`);
  await expect(page.locator("[data-mission-run]")).toHaveCount(4);
  for (const item of await page.locator("[data-mission-run]").all()) {
    await expect(item).not.toHaveAttribute("open", "");
    await expect(item.locator("summary .mission-run-context")).toContainText("Poste");
    await expect(item.locator("summary .mission-run-context")).toContainText("Codex");
    await expect(item.locator("[data-mission-result]")).toBeVisible();
    await expect(item.locator(".mission-steps")).not.toBeVisible();
  }
  const completed = page.locator('[data-verdict="done"]');
  await expect(completed.locator("[data-mission-result]")).toContainText(longText);
  await completed.locator("summary").first().focus();
  await page.keyboard.press("Enter");
  await expect(completed.locator(".mission-steps")).toBeVisible();
  await expect(completed.locator(".ds-tech")).not.toHaveAttribute("open", "");
  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await globalOverflow(page)).toBeLessThanOrEqual(1);
  }
  await page.screenshot({ path: testInfo.outputPath("retours-mission-wide.png"), fullPage: true });
});
