/**
 * Roadmaps P10 - release gate for the Dashboard surface that the P7/P8/P9
 * specs do not cover: the Review Queue entry that leads to the Roadmap tab, the
 * degraded (API error) states, a refused review decision, desktop layout and the
 * A4 print layout of the client-side PDF export (`window.print()`).
 * Deterministic `page.route` mocks only, same convention as the other specs.
 */
import { expect, test, type Page } from "@playwright/test";
import { tmpdir } from "node:os";
import path from "node:path";
import { globalOverflow, go, login, newCaptured, P1 } from "./support/ui16-stub";

const ROADMAP_ID = "r-p10";
const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const step = (key: string, title: string, extra: Record<string, unknown> = {}) => ({
  id: `st-${key}`,
  roadmap_id: ROADMAP_ID,
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

const roadmap = (phaseCount = 1) => ({
  id: ROADMAP_ID,
  project_id: P1,
  title: "Plan P10",
  objective: "Valider la clôture",
  status: "active",
  revision_no: 2,
  approved_revision_no: 2,
  version: 4,
  progress: { done: 0, total: phaseCount, skipped: 0, ratio: 0 },
  current_step_key: "S1",
  phases: Array.from({ length: phaseCount }, (_, index) => ({
    id: `ph${index + 1}`,
    roadmap_id: ROADMAP_ID,
    key: `P${index + 1}`,
    position: index,
    title: `Phase ${index + 1}`,
    progress: { done: 0, total: 1, skipped: 0, ratio: 0 },
    steps: [step(index === 0 ? "S1" : `S${index + 1}`, `Étape ${index + 1}`)],
  })),
});

const pendingRevision = {
  id: "rev-p10",
  roadmap_id: ROADMAP_ID,
  revision_no: 3,
  kind: "proposal",
  status: "pending",
  base_revision_no: 2,
  summary: "Renommer l'étape 1",
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

interface Mocks {
  roadmapsStatus?: number;
  reviewStatus?: number;
  phases?: number;
  withProposal?: boolean;
}

async function mockRoadmapApi(page: Page, mocks: Mocks = {}): Promise<void> {
  const summary = { ...roadmap(mocks.phases), phases: undefined };
  await page.route(new RegExp(`/api/v1/projects/${P1}/roadmaps`), (route) =>
    mocks.roadmapsStatus !== undefined && mocks.roadmapsStatus >= 400
      ? route.fulfill(json({ detail: "boom" }, mocks.roadmapsStatus))
      : route.fulfill(json([summary])),
  );
  await page.route(new RegExp(`/api/v1/roadmaps/${ROADMAP_ID}$`), (route) => route.fulfill(json(roadmap(mocks.phases))));
  await page.route(new RegExp(`/api/v1/roadmaps/${ROADMAP_ID}/revisions`), (route) =>
    route.fulfill(json(mocks.withProposal === true ? [pendingRevision] : [])),
  );
  await page.route(new RegExp(`/api/v1/roadmaps/${ROADMAP_ID}/proposals/[^/]+/diff`), (route) =>
    route.fulfill(
      json({
        base_revision_no: 2,
        proposal_revision_no: 3,
        entries: [{ scope: "step", key: "S1", change: "changed", fields: ["title"] }],
      }),
    ),
  );
  await page.route(new RegExp(`/api/v1/roadmaps/${ROADMAP_ID}/proposals/[^/]+/review`), (route) =>
    route.fulfill(
      json(
        { detail: { error_code: "base_revision_stale", server_revision_no: 4 } },
        mocks.reviewStatus ?? 409,
      ),
    ),
  );
}

async function openRoadmap(page: Page, mocks: Mocks = {}): Promise<void> {
  await login(page, "#/projects", newCaptured());
  await mockRoadmapApi(page, mocks);
  await go(page, `#/projects/${P1}/roadmap`);
  await expect(page.locator("#workspace-panel")).toBeVisible();
}

test.describe("Roadmaps P10 - Dashboard release gate", () => {
  test("la file de review mène de la proposition de roadmap à l'onglet Roadmap", async ({ page }) => {
    await login(page, "#/projects", newCaptured());
    await mockRoadmapApi(page, { withProposal: true });
    await page.route("**/api/v1/review-queue**", (route) =>
      route.fulfill(
        json({
          generated_at: "2026-09-20T12:00:00Z",
          items: [
            {
              kind: "roadmap_proposal",
              id: "rq-rev-3",
              project_id: P1,
              task_id: null,
              title: "Plan P10",
              scope: "revision",
              roadmap_id: ROADMAP_ID,
              revision_no: 3,
              base_revision_no: 2,
              requested_at: "2026-09-20T11:00:00Z",
            },
          ],
        }),
      ),
    );
    await go(page, "#/decisions");
    await expect(page.getByText("Proposition de roadmap").first()).toBeVisible();
    await expect(page.getByText("révision 3 de « Plan P10 »")).toBeVisible();
    const link = page.getByRole("link", { name: "Examiner dans Roadmap" });
    await expect(link).toHaveAttribute("href", `#/projects/${P1}/roadmap/${ROADMAP_ID}`);
    await link.click();
    // ...and the reviewer lands on the pending proposal with its diff and the decision actions
    await expect(page.locator(".roadmap-proposal-review")).toBeVisible();
    await expect(page.getByText("Renommer l'étape 1")).toBeVisible();
    await expect(page.getByRole("button", { name: "Approuver" })).toBeVisible();
  });

  test("API Roadmap en erreur : alerte claire, le reste du projet reste utilisable", async ({ page }) => {
    await openRoadmap(page, { roadmapsStatus: 500 });
    await expect(page.locator("#workspace-panel [role=alert]")).toContainText("Roadmap indisponible");
    await page.locator('[data-ws-tab="tasks"]').click();
    await expect(page.locator('[data-ws-tab="tasks"]')).toHaveAttribute("aria-selected", "true");
    // the Roadmap failure stays confined to the Roadmap tab
    await expect(page.locator("#workspace-panel")).not.toContainText("Roadmap indisponible");
  });

  test("décision refusée par le serveur (base périmée) : erreur visible, proposition intacte", async ({ page }) => {
    await openRoadmap(page, { withProposal: true });
    await expect(page.locator(".roadmap-proposal-review")).toBeVisible();
    await page.getByRole("button", { name: "Approuver" }).click();
    await expect(page.getByText("Décision refusée")).toBeVisible();
    await expect(page.locator(".roadmap-proposal-review")).toBeVisible();
    await expect(page.getByText("Décision enregistrée.")).toHaveCount(0);
  });

  test("bureau 1440 : grande roadmap sans débordement horizontal", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openRoadmap(page, { phases: 12 });
    await expect(page.locator(".roadmap-timeline h3", { hasText: "Phase 12" })).toBeVisible();
    expect(await globalOverflow(page)).toBe(0);
  });

  test("export PDF client : mise en page A4 imprimable, chrome masqué", async ({ page }) => {
    await openRoadmap(page, { phases: 4 });
    // the button only opens the browser print view; no server PDF is requested
    let serverPdf = 0;
    await page.route(/format=pdf/, (route) => {
      serverPdf += 1;
      return route.fulfill(json({ detail: { error_code: "not_implemented" } }, 501));
    });
    await page.evaluate(() => {
      (window as unknown as { __printed: number }).__printed = 0;
      window.print = () => {
        (window as unknown as { __printed: number }).__printed += 1;
      };
    });
    await page.getByRole("button", { name: "Exporter PDF" }).click();
    expect(await page.evaluate(() => (window as unknown as { __printed: number }).__printed)).toBe(1);
    expect(serverPdf).toBe(0);

    await page.emulateMedia({ media: "print" });
    await expect(page.locator(".app-sidebar")).toBeHidden();
    await expect(page.locator(".roadmap-print-document")).toBeVisible();
    await expect(page.locator(".roadmap-print-document h1")).toHaveText("Plan P10");
    await expect(page.locator(".roadmap-print-phase")).toHaveCount(4);
    const pdf = await page.pdf({
      path: path.join(tmpdir(), "studio-roadmap-p10-a4.pdf"),
      format: "A4",
      printBackground: true,
      margin: { top: "14mm", right: "12mm", bottom: "14mm", left: "12mm" },
    });
    const head = pdf.subarray(0, 8).toString("latin1");
    expect(head.startsWith("%PDF")).toBe(true);
    // A4 = 595 x 842 pt
    expect(pdf.toString("latin1")).toMatch(/\/MediaBox\s*\[\s*0\s+0\s+595(\.\d+)?\s+84[12](\.\d+)?\s*\]/);
    const overflow = await page.evaluate(() => {
      const el = document.querySelector<HTMLElement>(".roadmap-print-document");
      return el === null ? -1 : Math.max(0, el.scrollWidth - el.clientWidth);
    });
    expect(overflow).toBe(0);
  });
});
