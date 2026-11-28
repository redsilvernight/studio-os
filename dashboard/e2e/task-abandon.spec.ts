/**
 * Abandon de tâche (API mockée déterministe) : bouton « Abandonner » sur une
 * tâche active, dialogue DS (role=dialog, aria-modal, focus piégé et rendu,
 * Échap), motif obligatoire, PATCH versionné {status: "abandoned"}, motif
 * rappelé dans la notice, 409 invalid_transition expliqué. Zéro violation
 * axe sur le dialogue, zéro erreur page/CSP.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;

const P1 = "11111111-2222-4333-8444-555555555555";
const TASK_ID = "aaaaaaaa-0000-4111-8111-000000000002";

const PROJECT = {
  id: P1,
  slug: "phare",
  name: "Jeu Phare",
  description: "Le jeu principal du studio",
  archived: false,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-10T10:00:00Z",
  version: 7,
};

function baseTask() {
  return {
    id: TASK_ID,
    project_id: P1,
    readable_id: "T-002",
    title: "Optimiser les éclairages",
    description: null,
    status: "in_progress",
    claimed_by_machine_id: null,
    claimed_by_agent_id: null,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-11T10:00:00Z",
    version: 1,
  };
}

interface AbandonStub {
  /** La tâche servie par GET /tasks/{id} (vérité serveur, mutable). */
  current: ReturnType<typeof baseTask>;
  /** Quand vrai, PATCH répond 409 invalid_transition (terminée entre-temps). */
  refuseAbandon: boolean;
  patches: { version: string | null; body: unknown }[];
}

function apiStub(state: AbandonStub) {
  return async (route: Route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) {
      await json(200, { access_token: "e2e-token", token_type: "bearer" });
      return;
    }
    if (url.endsWith("/api/v1/auth/me")) {
      await json(200, {
        user_id: "u-e2e",
        display_name: "E2E",
        email: "e2e@example.test",
        role: "developer",
        machine_id: "m-e2e",
      });
      return;
    }
    if (method === "PATCH" && url.includes("/api/v1/tasks/")) {
      state.patches.push({
        version: req.headers()["if-match-version"] ?? null,
        body: req.postDataJSON(),
      });
      if (state.refuseAbandon) {
        state.current = { ...state.current, status: "completed", version: state.current.version + 1 };
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            detail: { error_code: "invalid_transition", message: "a completed task cannot be abandoned" },
          }),
        });
        return;
      }
      state.current = { ...state.current, status: "abandoned", version: state.current.version + 1 };
      await json(200, state.current);
      return;
    }
    if (url.includes("/api/v1/sessions") || url.includes("/api/v1/ai-work") || url.includes("/api/v1/claims")) {
      await json(200, []);
      return;
    }
    if (url.includes("/api/v1/usage/summary")) {
      await json(503, { detail: "indisponible" });
      return;
    }
    if (/\/api\/v1\/tasks\/[^/]+$/.test(url)) {
      await json(200, state.current);
      return;
    }
    if (url.includes("/api/v1/tasks")) {
      await json(200, [state.current]);
      return;
    }
    if (/\/api\/v1\/projects\/[^/]+$/.test(url)) {
      await json(200, PROJECT);
      return;
    }
    if (url.endsWith("/api/v1/projects")) {
      await json(200, [PROJECT]);
      return;
    }
    await json(200, []);
  };
}

async function login(page: Page, state: AbandonStub): Promise<void> {
  await page.route("**/api/**", apiStub(state));
  await page.goto(`/#/taches/${TASK_ID}`);
  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();
}

function watchErrors(page: Page): { csp: string[]; fatal: Error[] } {
  const csp: string[] = [];
  const fatal: Error[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && CSP_RE.test(msg.text())) csp.push(msg.text());
  });
  page.on("pageerror", (error) => fatal.push(error));
  return { csp, fatal };
}

test.describe("abandon de tâche", () => {
  test("dialogue, motif obligatoire, PATCH versionné, notice avec motif", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const state: AbandonStub = { current: baseTask(), refuseAbandon: false, patches: [] };
    await login(page, state);
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Optimiser les éclairages");

    // Section d'abandon proposée sur une tâche active.
    const open = view.locator("#task-abandon-open");
    await expect(open).toBeVisible();
    await open.click();
    const dialog = view.locator("#task-abandon-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('[role="dialog"]')).toHaveAttribute("aria-modal", "true");
    await expect(view.locator("#task-abandon-reason")).toBeFocused();

    // Accessibilité du dialogue ouvert : aucune violation.
    expect((await new AxeBuilder({ page }).include("#task-abandon-dialog").analyze()).violations).toEqual([]);

    // Échap ferme et rend le focus au déclencheur.
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(open).toBeFocused();

    // Motif obligatoire : aucun PATCH sans motif.
    await open.click();
    await expect(dialog).toBeVisible();
    await view.locator("#task-abandon-submit").click();
    await expect(view.locator("#task-abandon-error")).toContainText("Le motif est obligatoire.");
    expect(state.patches).toHaveLength(0);

    // Confirmation : PATCH {status abandoned} + If-Match-Version de lecture.
    await view.locator("#task-abandon-reason").fill("Doublon avec T-042");
    await view.locator("#task-abandon-submit").click();
    await expect.poll(() => state.patches.length).toBe(1);
    expect(state.patches[0]).toEqual({ version: "1", body: { status: "abandoned" } });

    // Notice de confirmation avec le motif, badge neutre, dialogue fermé.
    await expect(view.locator(".ds-notice--info")).toContainText("Tâche abandonnée. Motif : Doublon avec T-042");
    await expect(view.locator(".task-detail-hero .ds-status")).toContainText("Abandonnée");
    await expect(dialog).toBeHidden();
    // La tâche n'est plus abandonable : le bouton disparaît.
    await expect(view.locator("#task-abandon-open")).toHaveCount(0);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("409 invalid_transition : refus expliqué, données rechargées", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const state: AbandonStub = { current: baseTask(), refuseAbandon: true, patches: [] };
    await login(page, state);
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Optimiser les éclairages");

    await view.locator("#task-abandon-open").click();
    await view.locator("#task-abandon-reason").fill("Devenue inutile");
    await view.locator("#task-abandon-submit").click();
    await expect.poll(() => state.patches.length).toBe(1);

    // La vérité serveur (terminée) est relue et le refus est expliqué en clair.
    await expect(view.locator(".ds-notice--danger")).toContainText("terminée");
    await expect(view.locator(".task-detail-hero .ds-status")).toContainText("Terminé");
    await expect(view.locator("#task-abandon-dialog")).toBeHidden();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});
