/**
 * UI-6 Agents IA (browser, API stubbée déterministe) : route #/agents,
 * nav sans « Bientôt », liste nominale, empty, erreur, secondaire
 * indisponible, recherche locale, travail actuel, sessions, AI work,
 * machine, runtime/model/binding déclarés, détail, deep links,
 * back/forward, responsive 1440/1280/768/375, clavier, CSP.
 * Zéro violation CSP, zéro erreur page. Captures hors dépôt (temp).
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const SHOTS = "C:/Users/redsi/AppData/Local/Temp/opencode/ui6";

const A1 = "aaaaaaaa-0000-4111-8111-000000000001";
const A2 = "aaaaaaaa-0000-4111-8111-000000000002";
const M1 = "bbbbbbbb-0000-4111-8111-000000000001";
const M2 = "bbbbbbbb-0000-4111-8111-000000000002";
const T1 = "cccccccc-0000-4111-8111-000000000001";
const T2 = "cccccccc-0000-4111-8111-000000000002";
const P1 = "11111111-2222-4333-8444-555555555555";

const AGENTS = [
  {
    id: A1,
    machine_id: M1,
    display_name: "Claude Atlas",
    agent_kind: "code",
    agent_profile: "Revue et correction",
    harness: "opencode",
    provider: "anthropic",
    model: "claude-test",
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-17T10:00:00Z",
    version: 2,
  },
  {
    id: A2,
    machine_id: M2,
    display_name: "Kimi Scribe",
    agent_kind: "docs",
    agent_profile: null,
    harness: null,
    provider: null,
    model: null,
    created_at: "2026-09-02T10:00:00Z",
    updated_at: "2026-09-10T10:00:00Z",
    version: 1,
  },
];

const PROJECTS = [
  {
    id: P1,
    slug: "phare",
    name: "Binding of Apotheosis",
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
    title: "Rédiger le guide de prise en main",
    description: null,
    status: "created",
    claimed_by_machine_id: null,
    claimed_by_agent_id: null,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-10T10:00:00Z",
    version: 1,
  },
  {
    id: T2,
    project_id: P1,
    readable_id: "T-002",
    title: "Corriger l'authentification",
    description: null,
    status: "in_progress",
    claimed_by_machine_id: M1,
    claimed_by_agent_id: A1,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-11T10:00:00Z",
    version: 3,
  },
];

function payload(opts: { agentsFail?: boolean; secondaryFail?: boolean; empty?: boolean } = {}) {
  const now = new Date().toISOString();
  return async (route: Route) => {
    const url = route.request().url();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) {
      await json(200, { access_token: "e2e-token", token_type: "bearer" });
      return;
    }
    if (url.endsWith("/api/v1/agents")) {
      if (opts.agentsFail === true) {
        await json(500, { detail: "boom" });
        return;
      }
      await json(200, opts.empty === true ? [] : AGENTS);
      return;
    }
    if (url.includes("/api/v1/sessions")) {
      if (opts.secondaryFail === true) {
        await json(500, { detail: "boom" });
        return;
      }
      await json(200, [
        { id: "s1", task_id: T2, machine_id: M1, agent_id: A1, started_at: now, ended_at: null },
        {
          id: "s2",
          task_id: T1,
          machine_id: M2,
          agent_id: A2,
          started_at: "2026-09-05T09:00:00Z",
          ended_at: "2026-09-05T10:00:00Z",
        },
      ]);
      return;
    }
    if (url.includes("/api/v1/ai-work")) {
      if (opts.secondaryFail === true) {
        await json(500, { detail: "boom" });
        return;
      }
      await json(200, [
        {
          id: "w1",
          task_id: T2,
          project_id: P1,
          agent_id: A1,
          machine_id: M1,
          summary: "Réécriture du sampler avec tests",
          status: "started",
          changed_files: [],
          tests_run: [],
          started_at: now,
          ended_at: null,
          agent_profile: null,
          harness: null,
          provider: null,
          model: null,
        },
      ]);
      return;
    }
    if (url.includes("/api/v1/tasks")) {
      if (opts.secondaryFail === true) {
        await json(500, { detail: "boom" });
        return;
      }
      await json(200, TASKS);
      return;
    }
    if (url.includes("/api/v1/projects")) {
      await json(200, PROJECTS);
      return;
    }
    if (url.includes("/api/v1/events")) {
      if (opts.secondaryFail === true) {
        await json(500, { detail: "boom" });
        return;
      }
      await json(200, []);
      return;
    }
    if (url.endsWith("/api/v1/machines")) {
      await json(404, { detail: "not found" });
      return;
    }
    await json(200, []);
  };
}

async function login(page: Page, startHash: string, opts: { agentsFail?: boolean; secondaryFail?: boolean; empty?: boolean } = {}): Promise<void> {
  await page.route("**/api/**", payload(opts));
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

async function expectClean(watched: { csp: string[]; fatal: Error[] }): Promise<void> {
  expect(watched.csp).toEqual([]);
  expect(watched.fatal).toEqual([]);
}

/**
 * Le tiroir mobile se referme avec une transition CSS de 0,2 s après un
 * redimensionnement : attendre qu'il soit réellement hors écran (rect.x),
 * pas le premier matrix intermédiaire — sinon le screenshot fige le
 * tiroir à mi-course.
 */
async function awaitDrawerSettled(page: Page): Promise<void> {
  await expect
    .poll(
      () => page.evaluate(() => document.getElementById("app-sidebar")?.getBoundingClientRect().x),
      { timeout: 5000 },
    )
    .toBeLessThanOrEqual(-300);
}

test.describe("UI-6 page Agents", () => {
  test("liste nominale : nav réelle, cartes calmes, travail actuel honnête", async ({ page }) => {
    const watched = watchErrors(page);
    await login(page, "#/agents");
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Agents IA");
    await expect(view.locator(".agents-list .agent-card")).toHaveCount(2);
    // Nav : vraie route, sans « Bientôt », active ici.
    await expect(page.locator('.app-sidebar a[href="#/agents"]')).toHaveAttribute("aria-current", "page");
    await expect(page.locator(".app-sidebar")).toContainText("Agents IA");
    await expect(page.locator(".app-sidebar")).not.toContainText("Bientôt");
    // Agent actif : session ouverte + tâche + projet, vocabulaire DERIVED.
    const first = view.locator(".agent-card", { hasText: "Claude Atlas" });
    await expect(first).toContainText("Session de travail ouverte");
    await expect(first).toContainText("pas une preuve de connexion");
    await expect(first).toContainText("Travaille sur");
    await expect(first).toContainText("Corriger l'authentification");
    await expect(first).toContainText("Binding of Apotheosis");
    await expect(first).not.toContainText("En ligne");
    // Agent sans activité récente : dernière activité, machine courte, modèle déclaré.
    const second = view.locator(".agent-card", { hasText: "Kimi Scribe" });
    await expect(second).toContainText("Dernière activité");
    await expect(second).toContainText("Exécuté sur la machine");
    await expect(first).toContainText("Modèle déclaré : claude-test");
    // Deep links présents.
    await expect(first.locator(`a[href="#/agents/${A1}"]`).first()).toBeVisible();
    await expect(first.locator(`a[href="#/tasks/${T2}"]`).first()).toBeVisible();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: `${SHOTS}/agents-desktop.png` });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await expectClean(watched);
  });

  test("recherche locale + clavier : filtre sans réseau, focus conservé", async ({ page }) => {
    const watched = watchErrors(page);
    await login(page, "#/agents");
    const view = page.locator("#view");
    const search = view.locator("#agents-search");
    await expect(view.locator(".agent-card")).toHaveCount(2);
    await search.click();
    await search.pressSequentially("atlas", { delay: 10 });
    await expect(view.locator(".agent-card")).toHaveCount(1);
    await expect(view).toContainText("Claude Atlas");
    await expect(search).toBeFocused();
    await search.fill("");
    await expect(view.locator(".agent-card")).toHaveCount(2);
    // Navigation clavier : la fiche est atteignable au clavier.
    await view.locator('.agent-card a[href="#/agents/aaaaaaaa-0000-4111-8111-000000000001"]').first().focus();
    await page.keyboard.press("Enter");
    await expect(view.locator("h1")).toContainText("Claude Atlas");
    await expectClean(watched);
  });

  test("détail : sections utiles, technique repliée, back/forward", async ({ page }) => {
    const watched = watchErrors(page);
    await login(page, `#/agents/${A1}`);
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Claude Atlas");
    for (const section of ["Activité", "Travail actuel", "Résumé", "Travail produit", "Sessions", "Environnement"]) {
      await expect(view.locator("h2", { hasText: section })).toBeVisible();
    }
    await expect(view).toContainText("Réécriture du sampler");
    await expect(view).toContainText("Commencé");
    await expect(view).toContainText("Informations techniques");
    await expect(view.locator("details summary", { hasText: "Informations techniques" })).toBeVisible();
    // Technique repliée par défaut.
    await expect(view.locator("details")).not.toHaveAttribute("open", "");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: `${SHOTS}/agent-detail-desktop.png` });
    // Retour liste puis avant : deep links + historique intacts.
    await view.locator('a[href="#/agents"]').first().click();
    await expect(view.locator("h1")).toContainText("Agents IA");
    await page.goBack();
    await expect(view.locator("h1")).toContainText("Claude Atlas");
    await page.goForward();
    await expect(view.locator("h1")).toContainText("Agents IA");
    await expectClean(watched);
  });

  test("agent introuvable : état explicite, pas de fiche vide", async ({ page }) => {
    const watched = watchErrors(page);
    await login(page, "#/agents/00000000-0000-4000-8000-000000000000");
    const view = page.locator("#view");
    await expect(view).toContainText("Agent introuvable");
    await expect(view.locator('a[href="#/agents"]').first()).toBeVisible();
    await expectClean(watched);
  });

  test("empty : explique l'agent, sans bouton de création fictif", async ({ page }) => {
    const watched = watchErrors(page);
    await login(page, "#/agents", { empty: true });
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Agents IA");
    await expect(view).toContainText("Aucun agent enregistré");
    await expect(view).toContainText("identité de travail");
    await expect(view).not.toContainText("Créer un agent");
    await page.screenshot({ path: `${SHOTS}/agents-empty.png` });
    await expectClean(watched);
  });

  test("erreur liste : état danger, sans contenu inventé", async ({ page }) => {
    const watched = watchErrors(page);
    await login(page, "#/agents", { agentsFail: true });
    const view = page.locator("#view");
    await expect(view).toContainText("Agents indisponibles");
    await expect(view.locator(".agent-card")).toHaveCount(0);
    await expectClean(watched);
  });

  test("secondaire indisponible : liste sans activité affirmée", async ({ page }) => {
    const watched = watchErrors(page);
    await login(page, "#/agents", { secondaryFail: true });
    const view = page.locator("#view");
    await expect(view.locator(".agent-card")).toHaveCount(2);
    await expect(view).toContainText("Activité inconnue");
    await expect(view).toContainText("n'affirme aucune activité");
    await expect(view).not.toContainText("Actif récemment");
    await expect(view).not.toContainText("Session de travail ouverte");
    await expectClean(watched);
  });

  test("responsive 1280/768/375 : lisible, aucun overflow global", async ({ page }) => {
    const watched = watchErrors(page);
    await login(page, "#/agents");
    const view = page.locator("#view");
    await expect(view.locator(".agent-card")).toHaveCount(2);
    for (const size of [
      { width: 1280, height: 800 },
      { width: 768, height: 1024 },
      { width: 375, height: 812 },
    ]) {
      await page.setViewportSize(size);
      await expect(view.locator(".agent-card").first()).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(1);
    }
    await page.setViewportSize({ width: 375, height: 812 });
    await awaitDrawerSettled(page);
    await page.screenshot({ path: `${SHOTS}/agents-mobile.png` });
    // Jeton déjà en mémoire : simple navigation, pas de second login.
    await page.goto(`/#/agents/${A1}`);
    await expect(view.locator("h1")).toContainText("Claude Atlas");
    await awaitDrawerSettled(page);
    await page.screenshot({ path: `${SHOTS}/agent-detail-mobile.png` });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await expectClean(watched);
  });
});
