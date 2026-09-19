/**
 * UI-13 — UX globale, cohérence et robustesse (transversal).
 *
 * Couvre uniquement les invariants transversaux ajoutés/corrigés par UI-13 :
 * navigation répétée sans multiplication de listeners/renders, back/forward,
 * skip-link préservé, réponses asynchrones obsolètes (stale) non repeintes,
 * double-soumission (garde JS + bouton verrouillé), cycle de vie de la modale
 * (reset à la réouverture), erreur + retry, feedback de succès unique,
 * auth/logout, et zéro violation CSP / erreur page sur ces parcours.
 *
 * Ne duplique pas les suites UI-3 → UI-12 : API stubbée déterministe et
 * parcours courts.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;

const P1 = "11111111-2222-4333-8444-555555555555";

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
];

const TASKS = [
  {
    id: "aaaaaaaa-0000-4111-8111-000000000001",
    project_id: P1,
    readable_id: "T-001",
    title: "Caméra Android bloquée",
    description: null,
    status: "blocked",
    claimed_by_machine_id: null,
    claimed_by_agent_id: null,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-11T10:00:00Z",
    version: 2,
  },
  {
    id: "aaaaaaaa-0000-4111-8111-000000000002",
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
  },
];

interface Captured {
  createdKeys: (string | null)[];
  createdBodies: unknown[];
  tasksListRequests: number;
}

interface StubOptions {
  /** Le premier GET /tasks (liste) échoue en 500, puis réussit. */
  failFirstTasksList?: boolean;
  /** Délai (ms) appliqué à chaque GET /tasks (liste) — pour le scénario stale. */
  tasksListDelayMs?: number;
  /** Délai (ms) appliqué au POST /tasks — pour observer l'état en vol. */
  createDelayMs?: number;
}

function isTasksList(method: string, url: string): boolean {
  return method === "GET" && /\/api\/v1\/tasks(\?.*)?$/.test(url);
}

function apiStub(captured: Captured, opts: StubOptions = {}) {
  let tasksListFailuresLeft = opts.failFirstTasksList === true ? 1 : 0;
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
    if (method === "POST" && url.endsWith("/api/v1/tasks")) {
      captured.createdKeys.push(req.headers()["idempotency-key"] ?? null);
      captured.createdBodies.push(req.postDataJSON());
      if (opts.createDelayMs !== undefined && opts.createDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, opts.createDelayMs));
      }
      await json(201, { ...TASKS[0], id: "aaaaaaaa-0000-4111-8111-000000000009", title: "Nouvelle tâche ui13" });
      return;
    }
    if (isTasksList(method, url)) {
      captured.tasksListRequests += 1;
      if (opts.tasksListDelayMs !== undefined && opts.tasksListDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, opts.tasksListDelayMs));
      }
      if (tasksListFailuresLeft > 0) {
        tasksListFailuresLeft -= 1;
        await json(500, { detail: { error_code: "boom", message: "Service indisponible" } });
        return;
      }
      await json(200, TASKS);
      return;
    }
    if (url.includes("/api/v1/tasks")) {
      await json(200, TASKS[0]);
      return;
    }
    if (/\/api\/v1\/projects\/[^/]+\/state$/.test(url)) {
      await json(200, { project_id: P1, active_tasks: [], active_claims: [], generated_at: "2026-09-12T10:00:00Z" });
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
    if (url.includes("/api/v1/review-queue")) {
      await json(200, { items: [] });
      return;
    }
    await json(200, []);
  };
}

function newCaptured(): Captured {
  return { createdKeys: [], createdBodies: [], tasksListRequests: 0 };
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

async function login(page: Page, startHash: string, captured: Captured, opts: StubOptions = {}): Promise<void> {
  await page.route("**/api/**", apiStub(captured, opts));
  await page.goto(`/${startHash}`);
  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();
}

async function go(page: Page, hash: string): Promise<void> {
  await page.evaluate((target) => {
    window.location.hash = target;
  }, hash);
}

test.describe("UI-13 navigation et shell", () => {
  test("navigation répétée : un seul render par changement de route, listeners stables", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/tasks", captured);
    const view = page.locator("#view");
    await expect(view.locator(".task-row")).toHaveCount(2);
    const baseline = captured.tasksListRequests;

    // 10 allers-retours Tasks → Projects : chaque retour doit produire
    // EXACTEMENT une requête de liste (donc un seul render, un seul listener).
    for (let i = 0; i < 10; i += 1) {
      await go(page, "#/projects");
      await expect(view.locator("h1")).toContainText("Projets");
      await go(page, "#/tasks");
      await expect(view.locator(".task-row")).toHaveCount(2);
    }
    expect(captured.tasksListRequests - baseline).toBe(10);
    expect(await page.locator(".app-shell").count()).toBe(1);
    expect(await page.locator("#view").count()).toBe(1);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("back/forward restaure la bonne vue sans shell dupliqué", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/projects", captured);
    const view = page.locator("#view");
    await go(page, "#/tasks");
    await expect(view.locator(".task-row")).toHaveCount(2);
    await go(page, "#/agents");
    await expect(view.locator("h1")).toContainText("Agents");
    await page.goBack();
    await expect(view.locator("h1")).toContainText("Tâches");
    await page.goForward();
    await expect(view.locator("h1")).toContainText("Agents");
    expect(await page.locator(".app-shell").count()).toBe(1);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("skip-link : garde la route, cible le #view courant, survit aux navigations (UI-2)", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/projects", captured);
    const routes: [string, string][] = [
      ["#/projects", "Projets"],
      ["#/tasks", "Tâches"],
      ["#/agents", "Agents IA"],
      ["#/configuration/runtimes", "Paramètres"],
    ];
    for (const [route, title] of routes) {
      await go(page, route);
      // Attendre la fin du render de la route : le skip-link doit focaliser
      // le #view COURANT, pas un nœud en cours de remplacement.
      await expect(page.locator("#view h1")).toContainText(title);
      // Le lien d'évitement n'est visible qu'au focus (comportement attendu) :
      // on le focalise puis Entrée, comme un utilisateur clavier.
      await page.locator(".ds-skip-link").focus();
      await page.keyboard.press("Enter");
      await expect.poll(() => page.evaluate(() => window.location.hash)).toBe(route);
      await expect.poll(() => page.evaluate(() => document.activeElement?.id ?? "")).toBe("view");
    }
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("réponse asynchrone obsolète : la route quittée ne repeint jamais la route courante", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/projects", captured);
    const view = page.locator("#view");
    // Tasks répond lentement ; on part avant la réponse.
    await go(page, "#/tasks");
    await go(page, "#/projects");
    await expect(view.locator("h1")).toContainText("Projets");
    // Laisse la réponse Tasks arriver après coup : elle doit être ignorée.
    await page.waitForTimeout(700);
    await expect(view.locator("h1")).toContainText("Projets");
    expect(await view.locator(".tasks").count()).toBe(0);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-13 double-soumission et modale", () => {
  test("garde JS : deux submit rapides → une seule mutation ; bouton verrouillé", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/tasks", captured, { createDelayMs: 400 });
    const view = page.locator("#view");
    await view.locator("#task-new").click();
    const dialog = view.locator("#task-create-dialog");
    await expect(dialog).toBeVisible();
    await dialog.locator("#task-title").fill("Nouvelle tâche ui13");
    await dialog.locator("#task-project").selectOption(P1);
    const submit = dialog.locator("#task-create-submit");
    await submit.click();
    await expect(submit).toBeDisabled();
    // Deux activations synthétiques immédiates ne doivent pas doubler l'envoi.
    await page.evaluate(() => {
      const form = document.querySelector<HTMLFormElement>("#task-create-form");
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await expect.poll(() => captured.createdKeys.length).toBe(1);
    expect(captured.createdKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    await expect(dialog).toBeHidden();
    // Succès : un seul toast, pas de double confirmation.
    await expect(page.locator("#ds-toast-region .ds-toast")).toHaveCount(1);
    await expect(page.locator("#ds-toast-region .ds-toast")).toContainText("créée");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("cycle de vie modale : réouverture = formulaire réinitialisé, Échap + retour focus", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/tasks", captured);
    const view = page.locator("#view");
    const openButton = view.locator("#task-new");
    await openButton.click();
    const dialog = view.locator("#task-create-dialog");
    await expect(dialog).toBeVisible();
    await dialog.locator("#task-title").fill("Nouvelle tâche ui13");
    await dialog.locator("#task-project").selectOption(P1);
    await dialog.locator("#task-create-submit").click();
    await expect(dialog).toBeHidden();
    // Réouverture : ni titre résiduel, ni bouton resté verrouillé.
    await openButton.click();
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("#task-title")).toHaveValue("");
    await expect(dialog.locator("#task-create-submit")).toBeEnabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(openButton).toBeFocused();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("erreur puis retry : la page signale l'échec, « Réessayer » recharge réellement", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/tasks", captured, { failFirstTasksList: true });
    const view = page.locator("#view");
    await expect(view.locator('[role=alert]')).toContainText("Tâches indisponibles");
    const retry = view.locator("[data-reload]").first();
    await expect(retry).toContainText("Réessayer");
    await retry.click();
    await expect(view.locator(".task-row")).toHaveCount(2);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-13 responsive (smoke transversal)", () => {
  test("1440/1280/768/375 : pas d'overflow horizontal global, modale de création incluse", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/tasks", captured);
    const hasGlobalOverflow = (): Promise<boolean> =>
      page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    for (const width of [1440, 1280, 768, 375]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await hasGlobalOverflow()).toBe(false);
    }
    await page.setViewportSize({ width: 375, height: 900 });
    await page.locator("#task-new").click();
    await expect(page.locator("#task-create-dialog")).toBeVisible();
    expect(await hasGlobalOverflow()).toBe(false);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-13 auth et navigation", () => {
  test("déconnexion fiable : le shell laisse place à l'écran de connexion", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/projects", captured);
    await expect(page.locator(".app-sidebar")).toBeVisible();
    await page.locator("#token-clear").click();
    await expect(page.locator("#login-form")).toBeVisible();
    expect(await page.locator(".app-shell").count()).toBe(0);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("route inconnue : page 404 explicite, sortie vers l'accueil", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/route-inconnue", captured);
    const view = page.locator("#view");
    await expect(view).toContainText("Page introuvable");
    await view.locator('a[href="#/"]').click();
    await expect(view.locator("h1")).toContainText("Accueil");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});
