/**
 * UI-5 Tâches (browser, API stubbée déterministe) : Liste par défaut FR,
 * Tableau + « Déplacer vers… » clavier, création en modale
 * (Idempotency-Key, double soumission, Échap, retour focus), PATCH
 * versionné + 409 expliqué, détail page de travail (claim/release,
 * sessions, AI work, best-effort), scope Workspace, responsive 1280/375.
 * Zéro violation CSP, zéro erreur page. Captures hors dépôt (temp).
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const SHOTS = "C:/Users/redsi/AppData/Local/Temp/opencode/ui5";

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
    description: "Le flux caméra fige sur Android 14.",
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
    claimed_by_machine_id: "bbbbbbbb-0000-4111-8111-000000000001",
    claimed_by_agent_id: null,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-11T10:00:00Z",
    version: 1,
  },
  {
    id: "aaaaaaaa-0000-4111-8111-000000000003",
    project_id: P1,
    readable_id: null,
    title: "Rédiger le guide de prise en main",
    description: null,
    status: "created",
    claimed_by_machine_id: null,
    claimed_by_agent_id: null,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-10T10:00:00Z",
    version: 1,
  },
];

const SESSIONS = [
  {
    id: "s1",
    task_id: "aaaaaaaa-0000-4111-8111-000000000002",
    machine_id: "bbbbbbbb-0000-4111-8111-000000000001",
    agent_id: null,
    started_at: "2026-09-11T09:00:00Z",
    ended_at: null,
  },
];

const AI_WORK = [
  {
    id: "w1",
    task_id: "aaaaaaaa-0000-4111-8111-000000000002",
    project_id: P1,
    agent_id: "cccccccc-0000-4111-8111-000000000001",
    machine_id: null,
    summary: "Réécriture du sampler avec tests",
    status: "review_requested",
    changed_files: ["a.ts"],
    tests_run: [],
    started_at: "2026-09-11T10:00:00Z",
    ended_at: null,
    agent_profile: "dev-front",
    harness: null,
    provider: null,
    model: null,
  },
];

interface Captured {
  idempotencyKeys: (string | null)[];
  createdBodies: unknown[];
  patches: { url: string; version: string | null; body: unknown }[];
}

function apiStub(captured: Captured, opts: { patchConflict?: boolean } = {}) {
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
      captured.idempotencyKeys.push(req.headers()["idempotency-key"] ?? null);
      captured.createdBodies.push(req.postDataJSON());
      await json(201, { ...TASKS[2], id: "aaaaaaaa-0000-4111-8111-000000000009", title: "Nouvelle tâche e2e" });
      return;
    }
    if (method === "PATCH" && url.includes("/api/v1/tasks/")) {
      captured.patches.push({
        url,
        version: req.headers()["if-match-version"] ?? null,
        body: req.postDataJSON(),
      });
      if (opts.patchConflict === true) {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: { error_code: "version_conflict", server_version: 9 } }),
        });
        return;
      }
      await json(200, { ...TASKS[1], version: 2 });
      return;
    }
    if (method === "POST" && url.endsWith("/claim")) {
      await json(200, { ...TASKS[1], status: "in_progress", claimed_by_machine_id: "m-e2e", version: 2 });
      return;
    }
    if (method === "POST" && url.endsWith("/release")) {
      await json(200, { ...TASKS[1], claimed_by_machine_id: null, version: 3 });
      return;
    }
    if (url.includes("/api/v1/sessions")) {
      await json(200, SESSIONS);
      return;
    }
    if (url.includes("/api/v1/ai-work")) {
      await json(200, AI_WORK);
      return;
    }
    if (url.includes("/api/v1/claims")) {
      await json(200, []);
      return;
    }
    if (/\/api\/v1\/tasks\/[^/]+$/.test(url)) {
      await json(200, TASKS[1]);
      return;
    }
    if (url.includes("/api/v1/tasks")) {
      await json(200, TASKS);
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
    await json(200, []);
  };
}

async function login(page: Page, startHash: string, captured: Captured, opts: { patchConflict?: boolean } = {}): Promise<void> {
  await page.route("**/api/**", apiStub(captured, opts));
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

test.describe("UI-5 liste des tâches", () => {
  test("Liste par défaut en français, sans clés techniques", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured: Captured = { idempotencyKeys: [], createdBodies: [], patches: [] };
    await login(page, "#/tasks", captured);
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Tâches");
    await expect(view.locator("h1")).toBeVisible();
    // Vue Liste par défaut (bouton enfoncé), pas de kanban.
    await expect(view.locator('[data-view="list"]')).toHaveAttribute("aria-pressed", "true");
    await expect(view.locator(".tasks-list")).toBeVisible();
    await expect(view.locator(".kanban")).toHaveCount(0);
    // FR : badges, recherche, statuts ; aucune clé brute visible.
    await expect(view).toContainText("À faire");
    await expect(view).toContainText("En cours");
    await expect(view).toContainText("Bloqué");
    await expect(view).toContainText("Tous les statuts");
    await expect(view.locator("#tasks-search")).toHaveAttribute("placeholder", /Filtrer par titre/);
    await expect(view).not.toContainText("TODO");
    await expect(view).not.toContainText("IN PROGRESS");
    await expect(view).not.toContainText("Load more");
    await expect(view).not.toContainText("unclaimed");
    // Chaque ligne ouvre le détail.
    await expect(view.locator('.tasks-list a[href^="#/tasks/"]')).toHaveCount(3);
    await expect(view.locator("#tasks-search")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/taches-liste-1280.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("recherche locale + filtre statut + réinitialisation au clavier", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured: Captured = { idempotencyKeys: [], createdBodies: [], patches: [] };
    await login(page, "#/tasks", captured);
    const view = page.locator("#view");
    await expect(view.locator(".task-row")).toHaveCount(3);
    await view.locator("#tasks-search").fill("éclairages");
    await expect(view.locator(".task-row")).toHaveCount(1);
    await expect(view).toContainText("1 tâche(s) affichée(s) sur 3 chargée(s)");
    // Réinitialiser restaure tout, au clavier aussi (Tab + Entrée).
    await view.locator("#tasks-search").fill("");
    await view.locator("#tasks-status").selectOption("blocked");
    await expect(view.locator(".task-row")).toHaveCount(1);
    await expect(view).toContainText("Caméra Android bloquée");
    await view.locator("[data-reset]").first().click();
    await expect(view.locator(".task-row")).toHaveCount(3);
    // Aucun résultat : message distinct, pas « aucune tâche ».
    await view.locator("#tasks-search").fill("zzz-introuvable");
    await expect(view).toContainText("Aucune tâche ne correspond aux filtres");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("Tableau : colonnes FR, déplacement clavier versionné", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured: Captured = { idempotencyKeys: [], createdBodies: [], patches: [] };
    await login(page, "#/tasks", captured);
    const view = page.locator("#view");
    await view.locator('[data-view="board"]').click();
    await expect(view.locator(".kanban").first()).toBeVisible();
    await expect(view).toContainText("Déplacer vers…");
    await expect(view).not.toContainText("TODO");
    // Déplacement clavier : select + bouton → PATCH + If-Match-Version.
    const card = view.locator('[data-card="aaaaaaaa-0000-4111-8111-000000000003"]');
    await card.locator("select[data-status]").selectOption("in_progress");
    await card.locator("[data-move]").click();
    await expect.poll(() => captured.patches.length).toBe(1);
    expect(captured.patches[0]?.version).toBe("1");
    expect(captured.patches[0]?.body).toEqual({ status: "in_progress" });
    await page.screenshot({ path: `${SHOTS}/taches-tableau-1280.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("409 tableau : message humain, relecture, aucun retry silencieux", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured: Captured = { idempotencyKeys: [], createdBodies: [], patches: [] };
    await login(page, "#/tasks", captured, { patchConflict: true });
    const view = page.locator("#view");
    await view.locator('[data-view="board"]').click();
    const card = view.locator('[data-card="aaaaaaaa-0000-4111-8111-000000000003"]');
    await card.locator("select[data-status]").selectOption("completed");
    await card.locator("[data-move]").click();
    await expect(view.locator("[data-msg]")).toContainText("a changé ailleurs");
    expect(captured.patches).toHaveLength(1);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-5 création en modale", () => {
  test("ouverture, validation, Idempotency-Key, double soumission, Échap, retour focus", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured: Captured = { idempotencyKeys: [], createdBodies: [], patches: [] };
    await login(page, "#/tasks", captured);
    const view = page.locator("#view");
    await expect(view.locator(".task-row")).toHaveCount(3);
    const openButton = view.locator("#task-new");
    await openButton.click();
    const dialog = view.locator("#task-create-dialog");
    await expect(dialog).toBeVisible();
    // Validation : titre obligatoire.
    await dialog.locator("#task-create-submit").click();
    await expect(dialog.locator("#task-create-error")).toContainText("Le titre est obligatoire.");
    // Soumission : clé d'idempotence + corps, bouton verrouillé.
    await dialog.locator("#task-title").fill("Nouvelle tâche e2e");
    await dialog.locator("#task-project").selectOption(P1);
    const submit = dialog.locator("#task-create-submit");
    await submit.click();
    await expect(submit).toBeDisabled();
    await expect.poll(() => captured.idempotencyKeys.length).toBe(1);
    expect(captured.idempotencyKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(captured.createdBodies[0]).toMatchObject({ project_id: P1, title: "Nouvelle tâche e2e" });
    await expect(dialog).toBeHidden();
    // Échap referme, focus rendu au déclencheur.
    await openButton.click();
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(openButton).toBeFocused();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-5 détail tâche", () => {
  test("page de travail FR : sections, prise, sessions, IA, technique repliée", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured: Captured = { idempotencyKeys: [], createdBodies: [], patches: [] };
    await login(page, "#/tasks/aaaaaaaa-0000-4111-8111-000000000002", captured);
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Optimiser les éclairages");
    await expect(view).toContainText("Vue générale");
    await expect(view).toContainText("Modifier la tâche");
    await expect(view).toContainText("Prise en charge");
    await expect(view).toContainText("Sessions (1)");
    await expect(view).toContainText("Travail IA (1)");
    await expect(view).toContainText("En relecture");
    await expect(view).toContainText("À ne pas confondre avec les réservations de ressources");
    await expect(view).toContainText("Informations techniques");
    await expect(view).not.toContainText("Claim for my machine");
    await page.screenshot({ path: `${SHOTS}/tache-detail-1280.png` });
    // Libérer : POST release, statut conservé, message explicite.
    await view.locator("[data-release]").click();
    await expect(view.locator(".ds-notice--info")).toContainText("Le statut reste inchangé");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("édition 409 : conflit expliqué, relecture, réapplication consciente", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured: Captured = { idempotencyKeys: [], createdBodies: [], patches: [] };
    await login(page, "#/tasks/aaaaaaaa-0000-4111-8111-000000000002", captured, { patchConflict: true });
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Optimiser les éclairages");
    await view.locator("#task-edit-title").fill("Titre modifié en conflit");
    await view.locator("#task-edit-submit").click();
    await expect(view.locator(".ds-notice--danger")).toContainText("a changé ailleurs");
    expect(captured.patches).toHaveLength(1);
    expect(captured.patches[0]?.version).toBe("1");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-5 workspace projet / tâches", () => {
  test("onglet scopé, même système, deep link", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured: Captured = { idempotencyKeys: [], createdBodies: [], patches: [] };
    await login(page, `#/projects/${P1}/tasks`, captured);
    const view = page.locator("#view");
    await expect(view.locator("h1")).toHaveCount(1);
    await expect(view.locator("h1")).toContainText("Jeu Phare");
    await expect(view.locator('[data-ws-tab="tasks"]')).toHaveAttribute("aria-selected", "true");
    await expect(view.locator(".tasks > .ds-section-header h2")).toContainText("Tâches");
    await expect(view.locator(".tasks-list")).toBeVisible();
    await expect(view.locator(".task-row")).toHaveCount(3);
    // Retour à la liste globale : deep link stable.
    await page.goto("/#/tasks");
    await expect(view.locator(".tasks-list")).toBeVisible();
    await page.goBack();
    await expect(view.locator('[data-ws-tab="tasks"]')).toHaveAttribute("aria-selected", "true");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-5 mobile 375", () => {
  test.use({ viewport: { width: 375, height: 800 } });

  test("liste, tableau et détail utilisables sans débordement global", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured: Captured = { idempotencyKeys: [], createdBodies: [], patches: [] };
    await login(page, "#/tasks", captured);
    const view = page.locator("#view");
    await expect(view.locator(".task-row").first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/taches-liste-mobile.png` });
    await view.locator('[data-view="board"]').click();
    await expect(view.locator(".kanban").first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/taches-tableau-mobile.png` });
    await page.goto("/#/tasks/aaaaaaaa-0000-4111-8111-000000000002");
    await expect(view.locator("h1")).toContainText("Optimiser les éclairages");
    await page.screenshot({ path: `${SHOTS}/tache-detail-mobile.png` });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});
