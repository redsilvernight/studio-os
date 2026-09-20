/**
 * UI-14 — Accessibilité approfondie (transversal, WCAG 2.2 AA visée).
 *
 * Audit réel des parcours, pas seulement inspection statique : landmarks,
 * titres, noms accessibles, clavier complet, ordre de tabulation, focus
 * visible, skip-link, focus après navigation, modales (trap, Shift+Tab,
 * Échap, retour focus), drawer, onglets clavier, erreurs de formulaire,
 * régions live, reduced motion, zoom/reflow, et balayage axe automatisé
 * (critique/sérieux = échec, sans exclusion globale).
 *
 * API stubbée déterministe. Limite assumée : pas de lecteur d'écran réel
 * (NVDA/JAWS/VoiceOver) — on vérifie l'arbre d'accessibilité (rôles, noms,
 * ordre DOM, live regions) via Playwright. Zéro violation CSP, zéro pageerror.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const SHOTS = "C:/Users/redsi/AppData/Local/Temp/opencode/ui14";

const P1 = "11111111-2222-4333-8444-555555555555";
const T1 = "aaaaaaaa-0000-4111-8111-000000000001";
const M1 = "aaaaaaaa-0000-4111-8111-000000000001";

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
    id: T1,
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
];

const AGENTS = [
  {
    id: "ag-claude",
    machine_id: M1,
    display_name: "Claude",
    agent_kind: "dev",
    agent_profile: null,
    harness: "opencode",
    provider: null,
    model: null,
    created_at: "2026-09-14T10:00:00Z",
    updated_at: "2026-09-14T10:00:00Z",
    version: 1,
  },
];

const SESSIONS = [
  {
    id: "sess-active",
    task_id: T1,
    machine_id: M1,
    agent_id: "ag-claude",
    started_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    ended_at: null,
  },
];

const EVENTS = [
  {
    event_id: "e1",
    event_type: "session.started",
    project_id: P1,
    task_id: T1,
    machine_id: M1,
    actor_type: "agent",
    actor_id: "ag-claude",
    client_timestamp: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
    server_timestamp: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
    payload: {},
    schema_version: 1,
  },
];

const RUNTIMES = [
  {
    id: "rt1",
    owner_user_id: "u1",
    machine_id: M1,
    harness_ref: "opencode",
    provider_ref: "anthropic",
    model_ref: null,
    capabilities: { coding: true, tools: [], local: true },
    capability_source: "declared",
    runtime_metadata: {},
    status: "active",
    version: 1,
    created_at: "2026-09-14T10:00:00Z",
    updated_at: null,
  },
];

const CLAIMS = [
  {
    id: "cl1",
    project_id: P1,
    resource_path: "godot/scenes/niveau.tscn",
    resource_type: "file",
    claimed_by_machine_id: M1,
    task_id: null,
    status: "active",
    ttl_seconds: 3600,
    expires_at: new Date(Date.now() + 3600 * 1000).toISOString(),
  },
];

interface StubOptions {
  /** POST /tasks répond 500 (erreur de création focalisée). */
  failCreateTask?: boolean;
}

function apiStub(opts: StubOptions = {}) {
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
      if (opts.failCreateTask === true) {
        await json(500, { detail: { error_code: "boom", message: "Service indisponible" } });
        return;
      }
      await json(201, { ...TASKS[0], id: "aaaaaaaa-0000-4111-8111-000000000009", title: "Nouvelle tâche ui14" });
      return;
    }
    if (method === "GET" && /\/api\/v1\/machines\/?$/.test(url)) {
      await json(404, { detail: "not found" });
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
    if (/\/api\/v1\/tasks\/[^/]+$/.test(url)) {
      await json(200, TASKS[0]);
      return;
    }
    if (url.includes("/api/v1/tasks")) {
      await json(200, TASKS);
      return;
    }
    if (url.includes("/api/v1/timeline")) {
      await json(200, { project_id: P1, days: [] });
      return;
    }
    if (url.includes("/api/v1/claims")) {
      await json(200, CLAIMS);
      return;
    }
    if (url.includes("/api/v1/agents")) {
      await json(200, AGENTS);
      return;
    }
    if (url.includes("/api/v1/sessions")) {
      await json(200, SESSIONS);
      return;
    }
    if (url.includes("/api/v1/events")) {
      await json(200, EVENTS);
      return;
    }
    if (url.includes("/api/v1/runtimes")) {
      await json(200, RUNTIMES);
      return;
    }
    if (url.includes("/api/v1/review-queue")) {
      await json(200, { items: [] });
      return;
    }
    await json(200, []);
  };
}

function watchErrors(page: Page): { csp: string[]; fatal: Error[]; errors: string[] } {
  const csp: string[] = [];
  const fatal: Error[] = [];
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      errors.push(msg.text());
      if (CSP_RE.test(msg.text())) csp.push(msg.text());
    }
  });
  page.on("pageerror", (error) => fatal.push(error));
  return { csp, fatal, errors };
}

async function login(page: Page, startHash: string, opts: StubOptions = {}): Promise<void> {
  await page.route("**/api/**", apiStub(opts));
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

async function activeId(page: Page): Promise<string> {
  return page.evaluate(() => {
    const active = document.activeElement;
    if (active === null) return "(null)";
    return active.id !== "" ? `#${active.id}` : (active.textContent ?? "").trim().slice(0, 40);
  });
}

test.describe("UI-14 landmarks et titres", () => {
  test("shell : un seul main, nav nommée, complementary sans nom trompeur", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/tasks");
    await expect(page.locator("#view .task-row")).toHaveCount(1);
    expect(await page.locator("main").count()).toBe(1);
    expect(await page.locator("main#view").count()).toBe(1);
    expect(await page.locator('nav[aria-label="Navigation principale"]').count()).toBe(1);
    expect(await page.locator("aside[aria-label]").count()).toBe(0);
    expect(await page.locator("header.app-topbar").count()).toBe(1);
    expect(await page.locator("#ds-toast-region[role=status]").count()).toBe(1);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("chaque surface principale expose un h1", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/");
    const view = page.locator("#view");
    const routes: [string, string][] = [
      ["#/", "Accueil"],
      ["#/projects", "Projets"],
      [`#/projects/${P1}`, "Jeu Phare"],
      ["#/tasks", "Tâches"],
      [`#/tasks/${T1}`, "Tâche"],
      ["#/agents", "Agents IA"],
      ["#/machines", "Machines"],
      ["#/transfers", "Transferts"],
      ["#/decisions", "Décisions"],
      ["#/library", "Bibliothèque"],
      ["#/configuration/runtimes", "Paramètres"],
      ["#/inspector", "Inspecteur de résolution"],
      ["#/route-inexistante-xyz", "Page introuvable"],
    ];
    for (const [route, title] of routes) {
      await go(page, route);
      await expect(view.locator("h1").first()).toContainText(title, { timeout: 10_000 });
    }
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("login et 404 : h1, sortie explicite, clavier", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await page.route("**/api/**", apiStub());
    await page.goto("/");
    await expect(page.locator(".login-box h1")).toContainText("Studi'OS");
    await login(page, "#/route-inexistante-xyz");
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Page introuvable");
    const back = view.getByRole("link", { name: "Retour à l'Accueil" });
    await expect(back).toBeVisible();
    await back.focus();
    await page.keyboard.press("Enter");
    await expect(view.locator("h1")).toContainText("Accueil");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-14 noms accessibles et formulaires", () => {
  test("contrôles interactifs nommés, champs labellisés", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/tasks");
    const unnamed = await page.evaluate(() => {
      const missing: string[] = [];
      const controls = [...document.querySelectorAll("button, a[href], input, select, textarea, [role=tab]")];
      for (const el of controls) {
        if (!(el instanceof HTMLElement)) continue;
        if (el.closest("[hidden]") !== null) continue;
        const rects = el.getClientRects();
        if (rects.length === 0) continue;
        const labelled = el.getAttribute("aria-label") ?? el.getAttribute("aria-labelledby") ?? "";
        const text = (el.textContent ?? "").trim();
        let name = labelled.trim() !== "" ? labelled : text;
        if (el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement) {
          const id = el.id;
          const label = id !== "" ? document.querySelector(`label[for="${id}"]`)?.textContent?.trim() ?? "" : "";
          const wrap = el.closest("label")?.textContent?.trim() ?? "";
          const placeholder = el.getAttribute("placeholder") ?? "";
          name = labelled.trim() !== "" ? labelled : (label !== "" ? label : (wrap !== "" ? wrap : placeholder));
        }
        if (name === "") missing.push(el.outerHTML.slice(0, 120));
      }
      return missing;
    });
    expect(unnamed).toEqual([]);
    await expect(page.locator("#nav-open")).toHaveAttribute("aria-label", "Ouvrir la navigation");
    await expect(page.locator("#nav-close")).toHaveAttribute("aria-label", "Fermer la navigation");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("recherche et filtres : nom, compteur annoncé, reset", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/tasks");
    const view = page.locator("#view");
    const search = view.locator("[role=search]");
    await expect(search).toHaveAttribute("aria-label", "Filtrer les tâches chargées");
    await expect(view.locator("#tasks-search")).toHaveAccessibleName(/filtrer/i);
    await view.locator("#tasks-search").fill("caméra");
    await expect(view.locator(".task-row")).toHaveCount(1);
    await expect(view.locator("[role=status]", { hasText: "affichée" })).toContainText("affichée");
    await view.locator("[data-reset]").click();
    await expect(view.locator(".task-row")).toHaveCount(1);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("claims : français, table nommée avec scope, actions contextualisées", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, `#/projects/${P1}/claims`);
    const view = page.locator("#view");
    await expect(view.locator("[data-ws-tab=claims]")).toContainText("Réservations");
    await expect(view.locator("table caption")).toContainText("Réservations du projet");
    for (const header of ["Chemin", "Type", "Machine", "Tâche", "État", "Échéance", "Actions"]) {
      await expect(view.locator("table thead th", { hasText: header })).toHaveAttribute("scope", "col");
    }
    await expect(view.locator("table tbody")).toContainText("Active");
    await expect(view.locator("table tbody")).not.toContainText("Renew");
    const renew = view.getByRole("button", { name: /renouveler la réservation/i });
    await expect(renew).toBeVisible();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-14 clavier et focus", () => {
  test("parcours clavier complet : login, navigation, modale, skip-link", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await page.route("**/api/**", apiStub());
    await page.goto("/#/tasks");
    await expect(page.locator("#login-form")).toBeVisible();
    await page.keyboard.press("Tab");
    expect(await activeId(page)).toBe("#login-email");
    await page.keyboard.type("e2e@example.test");
    await page.keyboard.press("Tab");
    expect(await activeId(page)).toBe("#login-password");
    await page.keyboard.type("e2e-secret");
    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter");
    await expect(page.locator(".app-sidebar")).toBeVisible();
    await expect(page.locator("#view .task-row")).toHaveCount(1);

    await page.locator('.app-sidebar a[href="#/projects"]').focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#view h1")).toContainText("Projets");
    expect(await activeId(page)).toBe("#view");

    await go(page, "#/tasks");
    await expect(page.locator("#view .task-row")).toHaveCount(1);
    await page.locator("#task-new").focus();
    await page.keyboard.press("Enter");
    const dialog = page.locator("#task-create-dialog");
    await expect(dialog).toBeVisible();
    await page.locator("#task-title").fill("Tâche clavier ui14");
    await page.locator("#task-project").selectOption(P1);
    await page.locator("#task-create-submit").focus();
    await page.keyboard.press("Enter");
    await expect(dialog).toBeHidden();
    await expect(page.locator("#ds-toast-region .ds-toast")).toContainText("créée");

    await page.locator(".ds-skip-link").focus();
    await page.keyboard.press("Enter");
    expect(await activeId(page)).toBe("#view");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("ordre de tabulation : skip-link puis liens nav dans l'ordre de lecture", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/tasks");
    await page.locator(".ds-skip-link").focus();
    const stops: string[] = [];
    for (let i = 0; i < 4; i += 1) {
      await page.keyboard.press("Tab");
      stops.push(await activeId(page));
    }
    expect(stops).toEqual(["Accueil", "Projets", "Tâches", "Agents IA"]);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("focus visible : le lien d'évitement apparaît au focus clavier", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/tasks");
    await expect(page.locator("#view .task-row")).toHaveCount(1);
    const skip = page.locator(".ds-skip-link");
    const before = await skip.boundingBox();
    // Le focus est en tête de contenu (#view) après navigation : remonter
    // au premier arrêt DOM au clavier (Maj+Tab), comme un utilisateur.
    for (let i = 0; i < 40; i += 1) {
      if (await skip.evaluate((node) => node === document.activeElement)) break;
      await page.keyboard.press("Shift+Tab");
    }
    await expect(skip).toBeFocused();
    const after = await skip.boundingBox();
    expect(before?.y).toBeLessThan(0);
    expect(after?.y).toBeGreaterThanOrEqual(0);
    const outline = await skip.evaluate((node) => getComputedStyle(node).outlineWidth);
    expect(outline).not.toBe("0px");
    await page.screenshot({ path: `${SHOTS}/focus-skip-link.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("focus après navigation : le repère principal reçoit le focus, sans vol temps réel", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/projects");
    await expect(page.locator("#view h1")).toContainText("Projets");
    await go(page, "#/tasks");
    await expect(page.locator("#view .task-row")).toHaveCount(1);
    expect(await activeId(page)).toBe("#view");
    await page.evaluate(() => window.history.back());
    await expect(page.locator("#view h1")).toContainText("Projets");
    expect(await activeId(page)).toBe("#view");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-14 modales, drawers, onglets", () => {
  test("modale : trap Tab, Shift+Tab cyclé, Échap, retour focus", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/tasks");
    const view = page.locator("#view");
    const openButton = view.locator("#task-new");
    await openButton.click();
    const dialog = view.locator("#task-create-dialog");
    await expect(dialog).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/modale-clavier.png` });

    const last = dialog.locator("#task-create-submit");
    await last.focus();
    await page.keyboard.press("Tab");
    expect(await activeId(page)).toContain("task-project");

    const first = dialog.locator("#task-project");
    await first.focus();
    await page.keyboard.press("Shift+Tab");
    expect(await activeId(page)).toContain("task-create-submit");

    for (let i = 0; i < 8; i += 1) {
      await page.keyboard.press("Tab");
      const id = await activeId(page);
      expect(["#task-project", "#task-title", "#task-desc", "#task-create-submit", "Annuler"].some((mark) => id.includes(mark))).toBe(true);
    }

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    expect(await activeId(page)).toContain("task-new");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("drawer machine : sémantique dialogue modal, Échap, retour focus", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/machines");
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Machines");
    const details = view.locator("[data-machine-details]").first();
    await details.click();
    const drawer = view.locator("#machine-drawer");
    await expect(drawer).not.toHaveAttribute("hidden", "");
    await expect(drawer.locator('[role="dialog"]')).toHaveAttribute("aria-modal", "true");
    await expect(drawer.locator("h2")).toContainText("Détails de la machine");
    await page.screenshot({ path: `${SHOTS}/drawer-machine.png` });
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveAttribute("hidden", "");
    await expect(details).toBeFocused();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("onglets workspace : flèches déplacent le focus, Entrée active la vue", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, `#/projects/${P1}`);
    const view = page.locator("#view");
    const tabs = view.locator('[role="tab"]');
    await expect(tabs).toHaveCount(6);
    const panel = view.locator("#workspace-panel");
    await expect(panel).toHaveAttribute("role", "tabpanel");
    await expect(panel).toHaveAttribute("aria-labelledby", "ws-tab-overview");
    for (const [index, id] of ["overview", "roadmap", "tasks", "claims", "activity", "decisions"].entries()) {
      await expect(tabs.nth(index)).toHaveAttribute("id", `ws-tab-${id}`);
      await expect(tabs.nth(index)).toHaveAttribute("aria-controls", "workspace-panel");
    }
    const first = tabs.first();
    await first.focus();
    await page.keyboard.press("ArrowRight");
    await expect(tabs.nth(1)).toBeFocused();
    await page.keyboard.press("End");
    await expect(tabs.nth(5)).toBeFocused();
    await page.keyboard.press("Home");
    await expect(tabs.nth(0)).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Enter");
    await expect(view.locator("h1")).toContainText("Jeu Phare");
    await expect(view.locator('[data-ws-tab="tasks"]')).toHaveAttribute("aria-selected", "true");
    await expect(view.locator('[data-ws-tab="tasks"]')).toHaveAttribute("aria-current", "page");
    await expect(view.locator("#workspace-panel")).toHaveAttribute("aria-labelledby", "ws-tab-tasks");
    await page.screenshot({ path: `${SHOTS}/onglets-workspace.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("onglets décisions : flèches + Début/Fin, activation persistante", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/decisions");
    const view = page.locator("#view");
    const list = view.locator('[role="tablist"][aria-label="Décisions"]');
    await expect(list).toBeVisible();
    const review = view.locator("#decisions-main-tab-review");
    const decisions = view.locator("#decisions-main-tab-decisions");
    await review.focus();
    await page.keyboard.press("ArrowRight");
    await expect(decisions).toBeFocused();
    await expect(decisions).toHaveAttribute("aria-selected", "true");
    await expect(view.locator("#decisions-main-panel-decisions")).toBeVisible();
    await page.keyboard.press("ArrowLeft");
    await expect(review).toBeFocused();
    await page.keyboard.press("End");
    await expect(decisions).toBeFocused();
    await page.keyboard.press("Home");
    await expect(review).toBeFocused();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-14 erreurs, annonces, mouvement, zoom", () => {
  test("erreur de création : annoncée et focalisée dans la modale", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/tasks", { failCreateTask: true });
    const view = page.locator("#view");
    await view.locator("#task-new").click();
    const dialog = view.locator("#task-create-dialog");
    await expect(dialog).toBeVisible();
    await dialog.locator("#task-title").fill("Tâche en échec");
    await dialog.locator("#task-project").selectOption(P1);
    await dialog.locator("#task-create-submit").click();
    const error = dialog.locator("#task-create-error");
    await expect(error).toBeVisible();
    await expect(error).toHaveAttribute("role", "alert");
    await expect(error).toBeFocused();
    await page.screenshot({ path: `${SHOTS}/erreur-formulaire.png` });
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("erreur inline : message de création runtime focalisé", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/configuration/runtimes");
    const view = page.locator("#view");
    await view.locator("details.editor > summary").click();
    const form = view.locator("[data-runtime-create]");
    await form.locator('button[type="submit"]').click();
    const msg = form.locator("[data-msg]");
    await expect(msg).toContainText("ancrage");
    await expect(msg).toBeFocused();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("toast succès : annoncé via la région live, sans vol de focus", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/tasks");
    const view = page.locator("#view");
    await view.locator("#task-new").click();
    const dialog = view.locator("#task-create-dialog");
    await dialog.locator("#task-title").fill("Tâche annoncée");
    await dialog.locator("#task-project").selectOption(P1);
    await dialog.locator("#task-create-submit").click();
    const toast = page.locator("#ds-toast-region .ds-toast");
    await expect(toast).toContainText("créée");
    await expect.poll(() => activeId(page)).toBe("#task-new");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("reduced motion : transitions neutralisées", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await page.setViewportSize({ width: 640, height: 900 });
    await login(page, "#/tasks");
    await page.emulateMedia({ reducedMotion: "reduce" });
    const matches = await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    expect(matches).toBe(true);
    const duration = await page.locator(".app-sidebar").evaluate((node) => getComputedStyle(node).transitionDuration);
    expect(duration).not.toBe("0.2s");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("zoom 200 % : contenu utilisable, contrôles atteignables", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await page.setViewportSize({ width: 640, height: 900 });
    await login(page, "#/tasks");
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Tâches");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await expect(view.locator("#task-new")).toBeVisible();
    await view.locator("#task-new").focus();
    await expect(view.locator("#task-new")).toBeFocused();
    await expect(view.locator("#tasks-search")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/zoom-200-tasks.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("espacement du texte augmenté : contenu essentiel intact", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/tasks");
    await page.addStyleTag({
      content: "* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; } p { margin-bottom: 2em !important; }",
    });
    const view = page.locator("#view");
    await expect(view.locator("h1")).toBeVisible();
    await expect(view.locator("#task-new")).toBeVisible();
    await expect(view.locator(".task-row")).toHaveCount(1);
    // Le <style> injecté par le test lui-même déclenche la politique
    // report-only (attendu) ; aucun autre signal CSP.
    expect(csp.every((message) => /inline style/i.test(message))).toBe(true);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-14 balayage automatisé axe", () => {
  test("aucune violation critique/sérieuse sur les surfaces et overlays", async ({ page }) => {
    const { csp, fatal, errors } = watchErrors(page);
    const blocking: string[] = [];
    const collectSerious = (scope: string, violations: { id: string; help: string; impact?: string | null; nodes: unknown[] }[]): void => {
      for (const violation of violations.filter((v) => v.impact === "critical" || v.impact === "serious")) {
        blocking.push(`${scope} :: ${violation.id} :: ${violation.help} :: ${violation.nodes.length} nœud(s)`);
      }
    };
    await page.route("**/api/**", apiStub());
    await page.goto("/");
    await expect(page.locator("#login-form")).toBeVisible();
    collectSerious("login", (await new AxeBuilder({ page }).analyze()).violations);
    await login(page, "#/");
    const view = page.locator("#view");
    const surfaces: [string, string][] = [
      ["#/", "Accueil"],
      ["#/projects", "Projets"],
      ["#/tasks", "Tâches"],
      [`#/tasks/${T1}`, "Tâche"],
      ["#/agents", "Agents IA"],
      ["#/library", "Bibliothèque"],
      ["#/decisions", "Décisions"],
      ["#/machines", "Machines"],
      ["#/transfers", "Transferts"],
      ["#/inspector", "Inspecteur"],
      ["#/configuration/runtimes", "Paramètres"],
      ["#/route-inexistante-xyz", "Page introuvable"],
    ];
    for (const [route, title] of surfaces) {
      await go(page, route);
      await expect(view.locator("h1").first()).toContainText(title, { timeout: 10_000 });
      collectSerious(route, (await new AxeBuilder({ page }).analyze()).violations);
    }
    await go(page, "#/tasks");
    await expect(view.locator(".task-row")).toHaveCount(1);
    await view.locator("#task-new").click();
    const dialog = view.locator("#task-create-dialog");
    await expect(dialog).toBeVisible();
    collectSerious("modale", (await new AxeBuilder({ page }).include("#task-create-dialog").analyze()).violations);
    await page.keyboard.press("Escape");
    expect(blocking).toEqual([]);
    expect(fatal).toEqual([]);
    // Signaux attendus uniquement : injection <script> d'axe lui-même
    // (report-only, preuve que la politique est active) et bruit réseau
    // "Failed to load resource" (backend absent en E2E : /healthz 401,
    // /machines 404 volontaire pour la présence déduite UI-9).
    const networkNoise = /inline script|failed to load resource/i;
    const unexpectedCsp = csp.filter((message) => !networkNoise.test(message));
    expect(unexpectedCsp).toEqual([]);
    const unexpectedErrors = errors.filter((message) => !networkNoise.test(message));
    expect(unexpectedErrors).toEqual([]);
  });
});
