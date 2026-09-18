/**
 * UI-4 Projets & Workspace projet (browser, API stubbée déterministe) :
 * page Projets (cartes, filtre local clavier, ouverture), workspace
 * (header stable, 5 onglets, deep links, back/forward), overview résumée,
 * activité lisible, claims soft-lock, décisions liées au projet.
 * Zéro violation CSP, zéro erreur page. Captures dans le dossier temp
 * (hors dépôt) pour la validation visuelle du rapport UI-4.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const SHOTS = "C:/Users/redsi/AppData/Local/Temp/opencode/ui4";

const P1 = "11111111-2222-4333-8444-555555555555";
const P2 = "22222222-3333-4444-9555-666666666666";
const NOW = new Date("2026-09-12T10:00:00Z");
const iso = (ms: number): string => new Date(ms).toISOString();
const T0 = NOW.getTime();

const PROJECTS = [
  {
    id: P1,
    slug: "phare",
    name: "Jeu Phare",
    description: "Le jeu principal du studio",
    archived: false,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-10T10:00:00Z",
    version: 7,
  },
  {
    id: P2,
    slug: "digue",
    name: "Digue",
    description: null,
    archived: true,
    created_at: "2026-08-01T10:00:00Z",
    updated_at: "2026-08-02T10:00:00Z",
    version: 1,
  },
];

const TASKS = [
  {
    id: "t-blocked",
    project_id: P1,
    readable_id: "T-001",
    title: "Caméra Android bloquée",
    description: null,
    status: "blocked",
    claimed_by_machine_id: null,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-11T10:00:00Z",
    version: 2,
  },
  {
    id: "t-progress",
    project_id: P1,
    readable_id: "T-002",
    title: "Optimiser les éclairages",
    description: null,
    status: "in_progress",
    claimed_by_machine_id: null,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-11T10:00:00Z",
    version: 1,
  },
];

const CLAIMS = [
  {
    id: "c-soon",
    project_id: P1,
    task_id: null,
    resource_path: "godot/scenes/niveau.tscn",
    resource_type: "file",
    claimed_by_machine_id: "m1",
    ttl_seconds: 3600,
    status: "active",
    created_at: "2026-09-10T10:00:00Z",
    expires_at: iso(T0 + 2 * 3600 * 1000),
  },
  {
    id: "c-far",
    project_id: P1,
    task_id: null,
    resource_path: "godot/assets",
    resource_type: "folder",
    claimed_by_machine_id: "m1",
    ttl_seconds: 3600,
    status: "active",
    created_at: "2026-09-10T10:00:00Z",
    expires_at: iso(T0 + 30 * 24 * 3600 * 1000),
  },
];

function stubEvent(overrides: Record<string, unknown>): Record<string, unknown> {
  return {
    event_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    project_id: P1,
    task_id: null,
    machine_id: null,
    actor_type: "user",
    actor_id: "99999999-0000-1111-2222-333333333333",
    client_timestamp: "2026-09-12T09:00:00Z",
    server_timestamp: "2026-09-12T09:00:01Z",
    payload: {},
    schema_version: 1,
    ...overrides,
  };
}

const TIMELINE = {
  project_id: P1,
  days: [
    {
      date: "2026-09-12",
      events: [
        stubEvent({ event_type: "task.created", payload: { title: "Caméra Android bloquée" }, task_id: "t-blocked" }),
        stubEvent({ event_type: "resource.conflict", payload: { resource_path: "godot/scenes/niveau.tscn" } }),
        stubEvent({ event_type: "future.unknown_thing", payload: { anything: "kept-hidden" } }),
      ],
    },
    { date: "2026-09-11", events: [stubEvent({ event_type: "build.failed", server_timestamp: "2026-09-11T16:00:01Z" })] },
  ],
};

const DECISIONS = [
  {
    id: "d1",
    readable_id: "DEC-0049",
    project_id: P1,
    task_id: null,
    title: "Choisir le moteur de rendu",
    body: "Godot 4.",
    status: "proposed",
    proposed_by_type: "user",
    proposed_by_id: "99999999-0000-1111-2222-333333333333",
    created_at: "2026-09-10T10:00:00Z",
  },
];

function apiStub() {
  return async (route: Route) => {
    const url = route.request().url();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) {
      await json(200, { access_token: "e2e-token", token_type: "bearer" });
      return;
    }
    if (url.includes("/state")) {
      await json(200, { project_id: P1, active_tasks: TASKS, active_claims: CLAIMS, generated_at: iso(T0) });
      return;
    }
    if (/\/api\/v1\/projects\/[^/]+$/.test(url)) {
      await json(200, PROJECTS[0]);
      return;
    }
    if (url.endsWith("/api/v1/projects")) {
      await json(200, PROJECTS);
      return;
    }
    if (url.includes("/api/v1/timeline")) {
      await json(200, TIMELINE);
      return;
    }
    if (url.includes("/api/v1/claims")) {
      await json(200, CLAIMS);
      return;
    }
    if (url.includes("/api/v1/tasks")) {
      await json(200, TASKS);
      return;
    }
    if (url.includes("/api/v1/decisions")) {
      await json(200, DECISIONS);
      return;
    }
    if (url.includes("/api/v1/review-queue")) {
      await json(200, { items: [] });
      return;
    }
    await json(200, []);
  };
}

async function login(page: Page, startHash: string): Promise<void> {
  await page.route("**/api/**", apiStub());
  await page.goto(`/${startHash}`);
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

test.describe("UI-4 projets et workspace", () => {
  test("page Projets : cartes, filtre local au clavier, ouverture", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/projects");
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Projets");
    await expect(view).toContainText("Jeu Phare");
    await expect(view).toContainText("Digue");
    await expect(view.locator(".projects-grid .project-card")).toHaveCount(2);

    // Filtre client au clavier : ne quitte jamais la page, annonce le compte.
    await view.locator("#projects-filter").click();
    await page.keyboard.type("phare");
    await expect(view.locator(".projects-grid .project-card")).toHaveCount(1);
    await expect(view).toContainText("1 projet(s) affiché(s) sur 2 chargé(s)");
    await page.keyboard.press("Escape");
    await view.locator("#projects-filter").fill("");
    await expect(view.locator(".projects-grid .project-card")).toHaveCount(2);

    // Filtre d'état.
    await view.locator("#projects-state").selectOption("archived");
    await expect(view.locator(".projects-grid .project-card")).toHaveCount(1);
    await expect(view).toContainText("Digue");
    await view.locator("#projects-state").selectOption("all");

    await page.setViewportSize({ width: 1440, height: 900 });
    await expect(view.locator("h1")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/projets-desktop.png` });

    // Ouverture : deep link + contexte conservé.
    await view.locator('.project-card-title a[href$="t-blocked"], .project-card-title a').first().click();
    await expect(page).toHaveURL(new RegExp(`#/projects/${P1}$`));
    await expect(view.locator("h1")).toContainText("Jeu Phare");

    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("workspace : header stable, 5 onglets, deep links, back/forward", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, `#/projects/${P1}`);
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Jeu Phare");

    const tabs = view.locator('[role="tab"]');
    await expect(tabs).toHaveCount(5);
    await expect(view.locator('[data-ws-tab="overview"]')).toHaveAttribute("aria-selected", "true");

    // Overview résumée : pas de tableau complet.
    await expect(view).toContainText("Tâches actives (2)");
    await expect(view).toContainText("Réservations actives (2)");
    await expect(view).toContainText("À surveiller");
    await expect(view.locator(".workspace-overview table")).toHaveCount(0);

    // Flèches clavier entre onglets.
    await view.locator('[data-ws-tab="overview"]').focus();
    await page.keyboard.press("ArrowRight");
    await expect(view.locator('[data-ws-tab="tasks"]')).toBeFocused();

    // Deep links directs.
    await page.goto(`/#/projects/${P1}/tasks`);
    await expect(view.locator('[data-ws-tab="tasks"]')).toHaveAttribute("aria-selected", "true");
    await expect(view.locator("h1")).toContainText("Jeu Phare");
    await page.goto(`/#/projects/${P1}/claims`);
    await expect(view.locator('[data-ws-tab="claims"]')).toHaveAttribute("aria-selected", "true");

    // Back/forward navigateur.
    await page.goBack();
    await expect(view.locator('[data-ws-tab="tasks"]')).toHaveAttribute("aria-selected", "true");
    await page.goForward();
    await expect(view.locator('[data-ws-tab="claims"]')).toHaveAttribute("aria-selected", "true");

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/projects/${P1}`);
    await expect(view.locator("h1")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/workspace-overview-desktop.png` });

    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("activité : timeline lisible, type futur toléré, sans dump JSON", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, `#/projects/${P1}/activity`);
    const view = page.locator("#view");
    await expect(view).toContainText("Chevauchement de réservation");
    await expect(view).toContainText("godot/scenes/niveau.tscn");
    await expect(view).toContainText("Événement");
    await expect(view.locator('.tl-task[href="#/tasks/t-blocked"]')).toBeVisible();
    await expect(view).not.toContainText("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
    await expect(view).not.toContainText("anything");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: `${SHOTS}/workspace-activity-desktop.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("claims : explication soft-lock, Create/Renew/Release préservés", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, `#/projects/${P1}/claims`);
    const view = page.locator("#view");
    await expect(view).toContainText("verrou souple");
    await expect(view).toContainText("godot/scenes/niveau.tscn");
    await expect(view.locator("[data-renew]")).toHaveCount(2);
    await expect(view.locator("[data-release]")).toHaveCount(2);
    await expect(view.locator("[data-create]")).toBeVisible();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: `${SHOTS}/workspace-claims-desktop.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("décisions : liées au projet, note d'honnêteté, sans transition inventée", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, `#/projects/${P1}/decisions`);
    const view = page.locator("#view");
    await expect(view.locator('[data-ws-tab="decisions"]')).toHaveAttribute("aria-selected", "true");
    await expect(view).toContainText("Choisir le moteur de rendu");
    await expect(view).toContainText("DEC-0049");
    await expect(view).toContainText("décisions globales");
    await expect(view).not.toContainText("Accept");
    await expect(view).not.toContainText("Supersede");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("création projet : modale accessible, focus, Escape, retour focus", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/projects");
    const view = page.locator("#view");
    await view.locator("#project-new").click();
    const dialog = view.locator("#project-create-dialog");
    await expect(dialog).toBeVisible();
    await expect(view.locator("#project-slug")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(view.locator("#project-new")).toBeFocused();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-4 viewports 1280 et tablette 768", () => {
  for (const [name, size] of [["1280", { width: 1280, height: 800 }], ["tablette", { width: 768, height: 900 }]] as const) {
    test(`aucun débordement horizontal à ${name}`, async ({ page }) => {
      const { csp, fatal } = watchErrors(page);
      await login(page, "#/projects");
      await page.setViewportSize(size);
      const view = page.locator("#view");
      await expect(view.locator(".project-card").first()).toBeVisible();
      for (const hash of ["#/projects", `#/projects/${P1}`, `#/projects/${P1}/activity`, `#/projects/${P1}/claims`]) {
        await page.goto(`/${hash}`);
        await expect(view).not.toBeEmpty();
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow).toBeLessThanOrEqual(1);
      }
      if (name === "1280") {
        await page.goto(`/#/projects/${P1}/tasks`);
        // UI-5 : la Liste est la vue par défaut, le Tableau reste disponible.
        await expect(view.locator(".tasks-list").first()).toBeVisible();
        await view.locator('[data-view="board"]').click();
        await expect(view.locator(".kanban").first()).toBeVisible();
        await page.screenshot({ path: `${SHOTS}/workspace-tasks-1280.png` });
      }
      expect(csp).toEqual([]);
      expect(fatal).toEqual([]);
    });
  }
});

test.describe("UI-4 mobile 375", () => {
  test.use({ viewport: { width: 375, height: 800 } });

  test("projets + workspace utilisables sans débordement", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/projects");
    const view = page.locator("#view");
    await expect(view.locator(".project-card").first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/projets-mobile.png` });

    await page.goto(`/#/projects/${P1}`);
    await expect(view.locator("h1")).toContainText("Jeu Phare");
    await expect(view.locator('[role="tab"]')).toHaveCount(5);
    await page.screenshot({ path: `${SHOTS}/workspace-overview-mobile.png` });

    await page.goto(`/#/projects/${P1}/activity`);
    await expect(view).toContainText("Chevauchement de réservation");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});
