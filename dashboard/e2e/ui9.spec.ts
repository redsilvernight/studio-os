/**
 * UI-9 Machines (browser, API stubbée déterministe) : liste de cartes FR
 * sans table SQL, présence DÉDUITE honnête (activité, jamais "En ligne"),
 * recherche locale + filtre activité, tiroir de détail DS (Échap, retour
 * focus), empty state sans CTA fictif, responsive 1280/375, deep link +
 * back/forward. Zéro violation CSP, zéro erreur page. Captures hors dépôt.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const SHOTS = "C:/Users/redsi/AppData/Local/Temp/opencode/ui9";

const M1 = "aaaaaaaa-0000-4111-8111-000000000001";
const M2 = "bbbbbbbb-0000-4111-8111-000000000002";
const M3 = "cccccccc-0000-4111-8111-000000000003";

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
  {
    id: "ag-veilleur",
    machine_id: M3,
    display_name: "Veilleur",
    agent_kind: "",
    agent_profile: null,
    harness: null,
    provider: null,
    model: null,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-10T10:00:00Z",
    version: 1,
  },
];

const SESSIONS = [
  {
    id: "sess-active",
    task_id: "t1111111-0000-4111-8111-000000000001",
    machine_id: M1,
    agent_id: "ag-claude",
    started_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    ended_at: null,
  },
  {
    id: "sess-past",
    task_id: "t2222222-0000-4111-8111-000000000002",
    machine_id: M2,
    agent_id: null,
    started_at: new Date(Date.now() - 20 * 60 * 1000).toISOString(),
    ended_at: new Date(Date.now() - 18 * 60 * 1000).toISOString(),
  },
];

const EVENTS = [
  {
    event_id: "e1",
    event_type: "session.started",
    project_id: "11111111-2222-4333-8444-555555555555",
    task_id: "t1111111-0000-4111-8111-000000000001",
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

function apiStub(opts: { empty?: boolean } = {}) {
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
    // Pas de GET /machines sur l'API : la page doit dégrader en déduit.
    if (method === "GET" && /\/api\/v1\/machines\/?$/.test(url)) {
      await json(404, { detail: "not found" });
      return;
    }
    if (url.includes("/api/v1/agents")) {
      await json(200, opts.empty === true ? [] : AGENTS);
      return;
    }
    if (url.includes("/api/v1/sessions")) {
      await json(200, opts.empty === true ? [] : SESSIONS);
      return;
    }
    if (url.includes("/api/v1/events")) {
      await json(200, opts.empty === true ? [] : EVENTS);
      return;
    }
    if (url.includes("/api/v1/runtimes")) {
      await json(200, opts.empty === true ? [] : RUNTIMES);
      return;
    }
    await json(200, []);
  };
}

async function login(page: Page, startHash: string, opts: { empty?: boolean } = {}): Promise<void> {
  await page.route("**/api/**", apiStub(opts));
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

test.describe("UI-9 page Machines", () => {
  test("liste de cartes en français, présence déduite honnête", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/machines");
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Machines");
    await expect(view.locator(".machines-list")).toBeVisible();
    await expect(view.locator(".machine-row")).toHaveCount(3);
    await expect(view.locator(".machines-list table")).toHaveCount(0);
    // Honneteté : activité déduite, jamais d'état de connexion garanti.
    await expect(view).toContainText("Activité récente");
    await expect(view).toContainText("Aucune activité récente connue");
    await expect(view).toContainText("Déduit");
    await expect(view).toContainText("pas un état de connexion garanti");
    await expect(view).not.toContainText("En ligne");
    await expect(view).not.toContainText("Hors ligne");
    // Identité : nom quand disponible, jamais d'UUID en titre.
    await expect(view).toContainText("Machine sans nom enregistré");
    await expect(view.locator(".machines-list")).not.toContainText(M1);
    await expect(view.locator(`.machines-list h3[title="${M1}"]`)).toHaveCount(1);
    // Contexte utile, pas de monitoring fictif (le disclaimer d'honnêteté
    // cite CPU/RAM pour dire qu'ils ne sont PAS collectés).
    await expect(view).toContainText("Session en cours");
    await expect(view).toContainText("Aucune mesure CPU, RAM ou disponibilité n'est collectée");
    await expect(view).not.toContainText("uptime");
    await expect(view).not.toContainText("healthy");
    await page.screenshot({ path: `${SHOTS}/machines-liste-1280.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("recherche locale + filtre activité + réinitialisation au clavier", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/machines");
    const view = page.locator("#view");
    await expect(view.locator(".machine-row")).toHaveCount(3);

    // Recherche locale sur identifiant (pas de noms canoniques en déduit).
    await view.locator("#machines-search").fill(M2.slice(0, 8));
    await expect(view.locator(".machine-row")).toHaveCount(1);
    await expect(view).toContainText("1 machine(s) affichée(s) sur 3 chargée(s)");
    await expect(view).toContainText("recherche et filtre locaux");

    // Aucun résultat : état dédié, pas d'écran d'erreur.
    await view.locator("#machines-search").fill("zzz-sans-match");
    await expect(view).toContainText("Aucune machine ne correspond");
    await expect(view.locator(".machine-row")).toHaveCount(0);

    // Réinitialisation puis filtre d'activité honnête.
    await view.locator("[data-reset]").click();
    await expect(view.locator(".machine-row")).toHaveCount(3);
    await view.locator("#machines-activity").selectOption("offline");
    await expect(view.locator(".machine-row")).toHaveCount(1);
    await expect(view).toContainText("Aucune activité récente connue");
    await view.locator("#machines-activity").selectOption("all");
    await expect(view.locator(".machine-row")).toHaveCount(3);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("tiroir détail : hiérarchie, technique replié, Échap + retour focus", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/machines");
    const view = page.locator("#view");
    await expect(view.locator(".machine-row")).toHaveCount(3);

    const details = view.locator('[data-machine-details]').first();
    await details.click();
    const drawer = view.locator("#machine-drawer");
    await expect(drawer).not.toHaveAttribute("hidden", "");
    await expect(drawer).toContainText("Utilisation récente");
    await expect(drawer).toContainText("Environnement");
    await expect(drawer).toContainText("Informations techniques");
    await expect(drawer).toContainText("Claude");
    await expect(drawer).toContainText("opencode · anthropic");
    await expect(drawer.locator('a[href^="#/tasks/"]')).toHaveCount(1);
    await expect(drawer.locator(".machine-technical")).toContainText(M1);
    await expect(drawer).toContainText("Révocation");
    await expect(drawer).not.toContainText("Supprimer");
    await page.screenshot({ path: `${SHOTS}/machines-drawer-1280.png` });

    // Échap ferme et rend le focus au bouton d'ouverture.
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveAttribute("hidden", "");
    await expect(details).toBeFocused();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("état vide honnête sans CTA fictif", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/machines", { empty: true });
    const view = page.locator("#view");
    await expect(view).toContainText("Aucune machine observée");
    await expect(view).toContainText("provisionnées par un administrateur");
    await expect(view.locator("#machines-list a")).toHaveCount(0);
    await expect(view.locator("#machines-list button")).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/machines-vide-1280.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("mobile 375 : une colonne, pas d'overflow, deep link + back/forward", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/machines");
    const view = page.locator("#view");
    await expect(view.locator(".machine-row")).toHaveCount(3);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await expect(view.locator("#machines-search")).toBeVisible();
    await view.locator('[data-machine-details]').first().click();
    await expect(view.locator("#machine-drawer")).not.toHaveAttribute("hidden", "");
    await page.screenshot({ path: `${SHOTS}/machines-mobile-375.png` });
    await page.keyboard.press("Escape");

    // Back/forward : quitter puis revenir, la liste survit.
    await page.goto("/#/tasks");
    await expect(page.locator("#view")).toContainText("Tâches");
    await page.goBack();
    await expect(page.locator("#view").locator("h1")).toContainText("Machines");
    await expect(page.locator("#view").locator(".machine-row")).toHaveCount(3);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});
