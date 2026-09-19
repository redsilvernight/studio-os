/**
 * Visual Polish V2 — invariants du polish strictement visuel (largeur
 * desktop, surfaces, hiérarchie, Accueil, liste Tâches). Ne rejoue pas
 * UI-13→UI-16 : vérifie ce que ce chantier a changé, sur API stubbée.
 * Aucun comportement métier n'est modifié : le changement de statut au
 * clavier reste le même PATCH versionné.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { expectClean, globalOverflow, go, login, newCaptured, P1, watchErrors } from "./support/ui16-stub";

const LONG_TITLE =
  "Réécriture complète du module de synchronisation hors ligne avec rejeu idempotent des écritures et reprise après coupure réseau prolongée";
const LONG_DESC = "Description très longue ".repeat(30);
const LONG_PROJECT = "Projet-avec-un-nom-extrêmement-long-sans-aucun-espace-pour-tester-le-retour-à-la-ligne-forcé";
const TL = "aaaaaaaa-0000-4111-8111-0000000000f1";
const P2 = "22222222-2222-4333-8444-555555555556";

function task(id: string, n: number, status: string, title: string, description: string | null, projectId = P1) {
  return {
    id,
    project_id: projectId,
    readable_id: `T-${n}`,
    title,
    description,
    status,
    claimed_by_machine_id: null,
    claimed_by_agent_id: null,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-11T10:00:00Z",
    version: n,
  };
}

const TASKS = [
  task(TL, 1, "in_progress", LONG_TITLE, LONG_DESC, P2),
  task("aaaaaaaa-0000-4111-8111-0000000000f2", 2, "created", "Corriger le doublon de tâche", null),
  task("aaaaaaaa-0000-4111-8111-0000000000f3", 3, "blocked", "Caméra Android bloquée", "La caméra reste figée au lancement."),
  task("aaaaaaaa-0000-4111-8111-0000000000f4", 4, "completed", "Publier la démo", null),
];

function project(id: string, slug: string, name: string) {
  return {
    id,
    slug,
    name,
    description: "Description du projet",
    archived: false,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-10T10:00:00Z",
    version: 1,
  };
}

interface Patch {
  url: string;
  ifMatch: string | null;
  body: unknown;
}

/** Données longues : les routes enregistrées en dernier priment sur le stub. */
async function withData(page: Page, hash: string): Promise<{ patches: Patch[] }> {
  const patches: Patch[] = [];
  await login(page, hash, newCaptured());
  const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route(/\/api\/v1\/tasks(\?.*)?$/, (route) =>
    route.request().method() === "GET" ? route.fulfill(json(TASKS)) : route.fallback(),
  );
  await page.route(/\/api\/v1\/tasks\/[^/?]+$/, async (route) => {
    const req = route.request();
    if (req.method() !== "PATCH") return route.fallback();
    const body = req.postDataJSON() as { status?: string };
    patches.push({ url: req.url(), ifMatch: req.headers()["if-match-version"] ?? null, body });
    const id = req.url().split("/").pop() ?? "";
    const current = TASKS.find((t) => t.id === id) ?? TASKS[0];
    return route.fulfill(json({ ...current, status: body.status ?? current?.status, version: (current?.version ?? 0) + 1 }));
  });
  await page.route(/\/api\/v1\/projects(\?.*)?$/, (route) =>
    route.request().method() === "GET"
      ? route.fulfill(json([project(P1, "phare", "Jeu Phare"), project(P2, "long", LONG_PROJECT)]))
      : route.fallback(),
  );
  // Recharge la vue pour prendre les données longues en compte.
  await page.evaluate(() => {
    const h = window.location.hash;
    window.location.hash = "#/agents";
    setTimeout(() => {
      window.location.hash = h;
    }, 50);
  });
  await page.waitForTimeout(500);
  return { patches };
}

async function expectNoOverflow(page: Page, where: string): Promise<void> {
  expect(await globalOverflow(page), `overflow global : ${where}`).toBe(0);
}

async function contentBox(
  page: Page,
  selector: string,
): Promise<{ left: number; right: number; width: number; vw: number; colLeft: number }> {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const col = document.querySelector(".app-col");
    if (!(el instanceof HTMLElement) || !(col instanceof HTMLElement)) throw new Error(`introuvable : ${sel}`);
    const b = el.getBoundingClientRect();
    return { left: b.left, right: b.right, width: b.width, vw: window.innerWidth, colLeft: col.getBoundingClientRect().left };
  }, selector);
}

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function blockingAxe(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  return results.violations
    .filter((v) => v.impact === "critical" || v.impact === "serious")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

test.describe("Visual Polish V2 — Accueil", () => {
  test("desktop 1440 : tuiles, projets et travail côte à côte, surfaces", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, "#/", newCaptured());
    const tiles = page.locator("#view .home-metrics .ds-metric");
    await expect(tiles).toHaveCount(3);
    const tops = await tiles.evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
    expect(new Set(tops).size, "3 colonnes sur une ligne").toBe(1);
    const shadow = await tiles.first().evaluate((e) => getComputedStyle(e).boxShadow);
    expect(shadow, "tuile en surface (ombre légère)").not.toBe("none");
    const p = await page.locator("#view .home-section--projects").boundingBox();
    const w = await page.locator("#view .home-section--work").boundingBox();
    expect(p !== null && w !== null && Math.abs(p.y - w.y) < 2 && w.x > p.x + p.width - 1, "Projets | Travail en cours").toBe(true);
    await expect(page.locator("#view .home .ds-list--card").first()).toBeVisible();
    await expectNoOverflow(page, "home 1440");
    expectClean(watch);
  });

  test("2560×1440 : le contenu exploite la largeur et reste centré", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 2560, height: 1440 });
    await login(page, "#/", newCaptured());
    const box = await contentBox(page, "#view");
    expect(box.colLeft, "le shell couvre la fenêtre (plus de bloc 1280 centré)").toBeLessThan(320);
    expect(box.width, "mesure large (≥ 1200 px)").toBeGreaterThanOrEqual(1200);
    expect(box.width, "pas étalé (≤ 1400 px)").toBeLessThanOrEqual(1400);
    expect(Math.abs(box.left - box.colLeft - (box.vw - box.right)), "équilibre gauche/droite").toBeLessThan(40);
    await expectNoOverflow(page, "home 2560");
    expectClean(watch);
  });

  test("mobile 375 : tuiles compactes, pas d'overflow", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await login(page, "#/", newCaptured());
    await expect(page.locator("#view .home-metrics .ds-metric")).toHaveCount(3);
    await expectNoOverflow(page, "home 375");
    expectClean(watch);
  });

  test("axe : Accueil sans violation critique/sérieuse", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, "#/", newCaptured());
    expect(await blockingAxe(page)).toEqual([]);
    expectClean(watch);
  });
});

test.describe("Visual Polish V2 — Tâches", () => {
  test("liste desktop : titre + statut d'abord, déplacement discret mais visible", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await withData(page, "#/tasks");
    const rows = page.locator("#view .task-row");
    await expect(rows).toHaveCount(4);
    const row = rows.nth(1);
    const title = await row.locator(".task-head .ds-list-title").boundingBox();
    const badge = await row.locator(".task-head .ds-badge").boundingBox();
    expect(title !== null && badge !== null && badge.x - (title.x + title.width) < 40, "badge proche du titre").toBe(true);
    const select = row.locator(".task-move select");
    await expect(select).toBeVisible();
    await expect(select).toBeEnabled();
    await expect(row.locator("[data-move]")).toBeVisible();
    const sizes = await row.evaluate((r) => {
      const t = getComputedStyle(r.querySelector(".ds-list-title") as Element);
      const m = getComputedStyle(r.querySelector(".task-meta") as Element);
      return { weight: Number(t.fontWeight), title: parseFloat(t.fontSize), meta: parseFloat(m.fontSize) };
    });
    expect(sizes.weight).toBeGreaterThanOrEqual(600);
    expect(sizes.title).toBeGreaterThan(sizes.meta);
    expect((await row.boundingBox())?.height ?? 999, "ligne compacte").toBeLessThan(110);
    await expectNoOverflow(page, "tasks 1440");
    expectClean(watch);
  });

  test("liste 2560×1440 : largeur exploitée, contenu centré", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 2560, height: 1440 });
    await withData(page, "#/tasks");
    const box = await contentBox(page, "#view .tasks-list");
    expect(box.width).toBeGreaterThanOrEqual(1100);
    expect(box.width).toBeLessThanOrEqual(1400);
    expect(Math.abs(box.left - box.colLeft - (box.vw - box.right)), "équilibre").toBeLessThan(40);
    await expectNoOverflow(page, "tasks 2560");
    expectClean(watch);
  });

  test("liste mobile 375 : titre long lisible, contrôle empilé, cibles tactiles", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await withData(page, "#/tasks");
    const row = page.locator("#view .task-row").first();
    await expect(row).toBeVisible();
    expect((await row.locator(".ds-list-title").boundingBox())?.width ?? 0, "titre lisible").toBeGreaterThan(150);
    expect((await row.locator(".task-move select").boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(36);
    expect((await row.locator("[data-move]").boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(36);
    await expectNoOverflow(page, "tasks 375 long");
    expectClean(watch);
  });

  test("clavier : select puis bouton, même PATCH versionné qu'avant", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    const { patches } = await withData(page, "#/tasks");
    const row = page.locator("#view .task-row").nth(1);
    const select = row.locator(".task-move select");
    await select.focus();
    await expect(select).toBeFocused();
    expect(await select.evaluate((e) => getComputedStyle(e).outlineStyle), "focus visible").not.toBe("none");
    await select.selectOption("in_progress");
    await page.keyboard.press("Tab");
    await expect(row.locator("[data-move]")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect.poll(() => patches.length, { timeout: 5000 }).toBe(1);
    expect(patches[0]?.ifMatch).toBe("2");
    expect((patches[0]?.body as { status?: string }).status).toBe("in_progress");
    expect(patches[0]?.url).toContain("aaaaaaaa-0000-4111-8111-0000000000f2");
    expectClean(watch);
  });

  test("statut jamais couleur seule ; titre et projet longs sans overflow (768)", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 768, height: 900 });
    await withData(page, "#/tasks");
    const badges = await page.locator("#view .task-row .ds-badge").allInnerTexts();
    expect(badges.length).toBe(4);
    expect(badges.every((b) => b.trim().length > 0), "libellé textuel").toBe(true);
    await expect(page.locator("#view .task-row").first().locator(".ds-list-title")).toContainText("Réécriture complète");
    await expect(page.locator("#view .task-row").first().locator(".task-project")).toContainText("Projet-avec-un-nom");
    await expectNoOverflow(page, "tasks 768 long");
    expectClean(watch);
  });

  test("tableau : clavier préservé, pas d'overflow global", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await withData(page, "#/tasks");
    await page.locator('#view [data-view="board"]').click();
    const board = page.locator("#view .tasks-board");
    await expect(board).toBeVisible();
    await expect(board.locator(".task-col")).toHaveCount(4);
    await expect(board.locator(".task-move select").first()).toBeVisible();
    await expectNoOverflow(page, "board 1440");
    await page.setViewportSize({ width: 375, height: 812 });
    await expectNoOverflow(page, "board 375");
    expectClean(watch);
  });

  test("axe : Tâches (liste) et modale Nouvelle tâche", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await withData(page, "#/tasks");
    expect(await blockingAxe(page)).toEqual([]);
    await page.locator("#task-new").click();
    await expect(page.locator("#task-create-dialog")).toBeVisible();
    expect(await blockingAxe(page)).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(page.locator("#task-create-dialog")).toBeHidden();
    await expect(page.locator("#task-new")).toBeFocused();
    expectClean(watch);
  });
});

test.describe("Visual Polish V2 — Projets", () => {
  test("cartes : grille large, noms longs sans overflow, 1440 → 375", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await withData(page, "#/projects");
    const cards = page.locator("#view .project-card");
    await expect(cards).toHaveCount(2);
    const tops = await cards.evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
    expect(new Set(tops).size, "cartes côte à côte sur desktop").toBe(1);
    for (const [w, h] of [[1280, 800], [900, 800], [768, 900], [375, 812]] as const) {
      await page.setViewportSize({ width: w, height: h });
      await expectNoOverflow(page, `projects ${w}`);
    }
    expectClean(watch);
  });

  test("navigation Accueil → Tâches → Projets à 2560 : contenu large, sans overflow", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 2560, height: 1440 });
    await login(page, "#/", newCaptured());
    for (const hash of ["#/tasks", "#/projects"]) {
      await go(page, hash);
      expect((await contentBox(page, "#view")).width).toBeGreaterThanOrEqual(1200);
      await expectNoOverflow(page, hash);
    }
    expectClean(watch);
  });
});
