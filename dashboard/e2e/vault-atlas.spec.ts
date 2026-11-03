/**
 * Vault › Atlas — remplace l'ancien onglet Graph, sur le bundle de production
 * (`vite preview`), API canonique stubée comme les autres e2e.
 *
 * Propriétés vérifiées :
 *   1. la nav n'a plus d'entrée Graph et `#/graphs/*` mène à l'atlas ;
 *   2. l'atlas lit `GET /vault/tree` et dessine un canevas non vide ;
 *   3. la recherche multi-mots et les filtres réduisent les notes visibles ;
 *   4. la liste clavier sélectionne une note, ses voisins et « Ouvrir » ;
 *   5. la bascule Liste ramène à `#/vault` ;
 *   6. la liste expose titres, zone, extrait et tri ;
 *   7. l'atlas affiche zones/communautés, bascule 2D/3D persistée,
 *      navigation aux flèches et mesure de rendu.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const STAMP = "2026-10-08T10:00:00Z";
const USER = "55555555-5555-5555-5555-555555555555";
const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const TASK_ID = "77777777-7777-7777-7777-777777777777";
const DEC_OLD = "33333333-3333-3333-3333-333333333331";
const DEC_NEW = "33333333-3333-3333-3333-333333333332";
const RULE = "33333333-3333-3333-3333-333333333333";
const PROC = "33333333-3333-3333-3333-333333333334";

const note = (id: string, overrides: Record<string, unknown>): Record<string, unknown> => ({
  id,
  scope: "studio",
  project_id: null,
  slug: id.slice(-4),
  readable_id: null,
  note_type: "note",
  title: "Note",
  summary: "",
  status: "validated",
  tags: [],
  links: [],
  anchors: [],
  content_hash: "h",
  author_type: "user",
  author_id: USER,
  version: 1,
  created_at: STAMP,
  updated_at: STAMP,
  ...overrides,
});

const NOTES = [
  note(DEC_OLD, { note_type: "decision", readable_id: "DEC-0001", title: "Cache mémoire locale", status: "superseded" }),
  note(DEC_NEW, {
    note_type: "decision",
    readable_id: "DEC-0002",
    title: "Stratégie de cache Redis",
    summary: "Redis avant PostgreSQL.",
    links: [{ target_note_id: DEC_OLD, kind: "supersedes" }, { target_note_id: RULE, kind: "relates_to" }],
    anchors: [`task:${TASK_ID}`, "path:src/cache.ts"],
  }),
  note(RULE, { note_type: "rule", title: "Jamais de secret en clair" }),
  note(PROC, {
    scope: "project",
    project_id: PROJECT_ID,
    note_type: "procedure",
    title: "Checklist de release",
    status: "proposed",
  }),
];

function apiStub(calls: string[]) {
  return async (route: Route) => {
    const url = new URL(route.request().url());
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname.endsWith("/healthz")) return json(200, {});
    if (url.pathname.endsWith("/api/v1/auth/token")) {
      return json(200, { access_token: "e2e-token", token_type: "bearer", expires_in: 900 });
    }
    if (url.pathname.endsWith("/api/v1/auth/me")) {
      return json(200, { user_id: USER, display_name: "Ada", email: "ada@example.test", role: "member", machine_id: USER });
    }
    if (url.pathname.endsWith("/api/v1/projects")) {
      return json(200, [{ id: PROJECT_ID, name: "Studi'os", slug: "studios", status: "active", created_at: STAMP }]);
    }
    if (url.pathname.endsWith("/api/v1/vault/tree")) {
      calls.push(`tree ${url.search}`);
      return json(200, { items: NOTES, next_cursor: null });
    }
    if (url.pathname.endsWith("/api/v1/vault/search")) {
      calls.push("search");
      return json(200, { items: [], total: 0, truncated: false });
    }
    return json(200, []);
  };
}

async function login(page: Page, hash: string, calls: string[]): Promise<Error[]> {
  const errors: Error[] = [];
  page.on("pageerror", (error) => errors.push(error));
  await page.route("**/api/**", apiStub(calls));
  await page.goto(`/${hash}`);
  await page.fill("#login-email", "ada@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#view h1")).toHaveText("Vault");
  return errors;
}

async function goHash(page: Page, hash: string): Promise<void> {
  await page.evaluate((value) => {
    window.location.hash = value;
  }, hash);
}

/** Vrai si le canevas contient au moins un pixel différent du fond. */
async function canvasHasInk(page: Page): Promise<boolean> {
  return page.locator("#atlas-canvas").evaluate((el) => {
    const canvas = el as HTMLCanvasElement;
    const ctx = canvas.getContext("2d");
    if (ctx === null || canvas.width === 0 || canvas.height === 0) return false;
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let i = 4; i < data.length; i += 4) {
      if (data[i] !== data[0] || data[i + 1] !== data[1] || data[i + 2] !== data[2]) return true;
    }
    return false;
  });
}

test("atlas: graph tab merged into vault, search, filters, selection", async ({ page }) => {
  const calls: string[] = [];
  const errors = await login(page, "#/graphs/old-view", calls);

  /* 1. Ancienne URL réécrite, nav sans Graph. */
  await expect(page).toHaveURL(/#\/vault\/atlas$/);
  await expect(page.locator('a[href^="#/graphs"]')).toHaveCount(0);
  await expect(page.locator('.vault-modes a[aria-current="page"]')).toHaveText("Atlas");

  /* 2. Données réelles du tree, canevas dessiné. */
  await expect(page.locator("#atlas-canvas")).toBeVisible();
  expect(calls.some((c) => c.startsWith("tree"))).toBe(true);
  expect(calls).not.toContain("search");
  await expect.poll(() => canvasHasInk(page)).toBe(true);

  /* Superseded masquée par défaut, satellites d'ancres absents de la liste notes. */
  const list = page.locator("#atlas-list");
  await expect(list).toContainText("Stratégie de cache Redis");
  await expect(list).toContainText("Checklist de release");
  await expect(list).not.toContainText("Cache mémoire locale");

  /* Zones et communautés étiquetées/colorées. */
  await expect(page.locator("#atlas-status")).toContainText(/zone\(s\)/);
  await expect(page.locator("#atlas-status")).toContainText(/communauté\(s\)/);
  const regions = page.locator("#atlas-regions");
  await expect(regions).toContainText("Studio ·");
  await expect(regions).toContainText("Communauté 1");
  await expect(regions.locator("[data-zone-color]").first()).toBeVisible();
  await expect(page.locator(".vault-atlas-legend")).toContainText("Communauté de liens");
  await expect(page.locator("#atlas-perf")).toBeHidden();

  /* 6. Bascule 2D/3D persistée au remontage de la vue. */
  const projection = page.locator("#atlas-projection");
  await expect(projection).toHaveText("Vue 3D");
  await projection.click();
  await expect(projection).toHaveText("Vue 2D");
  await expect(projection).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#atlas-hint")).not.toContainText("pivoter");
  expect(await page.evaluate(() => localStorage.getItem("studio.vault.atlas.mode"))).toBe("2d");
  await goHash(page, "#/vault");
  await expect(page.locator(".vault-modes a[aria-current=\"page\"]")).toHaveText("Liste");
  await goHash(page, "#/vault/atlas");
  await expect(page.locator("#atlas-projection")).toHaveText("Vue 2D");
  await page.locator("#atlas-projection").click();
  await expect(page.locator("#atlas-projection")).toHaveText("Vue 3D");

  /* 3. Recherche multi-mots : chaque mot doit apparaître (accents ignorés). */
  await page.fill("#atlas-query", "strategie redis");
  await expect(page.locator("#atlas-status")).toContainText("1 correspondance");
  await expect(list.locator("[data-atlas-pick]").first()).toHaveText("Stratégie de cache Redis");
  await page.fill("#atlas-query", "");

  /* Filtre de portée : décocher Projet masque la procédure projet. */
  await page.locator('[data-atlas-scope="project"]').uncheck();
  await expect(list).not.toContainText("Checklist de release");
  await page.locator('[data-atlas-scope="project"]').check();

  /* Afficher les remplacées. */
  await page.locator('[data-atlas-toggle="superseded"]').check();
  await expect(list).toContainText("Cache mémoire locale");

  /* 4. Sélection clavier : détail, voisins, lien vers la liste. */
  const pick = list.getByRole("button", { name: "Stratégie de cache Redis" });
  await pick.focus();
  await page.keyboard.press("Enter");
  const detail = page.locator("#atlas-detail");
  await expect(detail).toContainText("DEC-0002");
  await expect(detail).toContainText("Jamais de secret en clair");
  await expect(detail).toContainText("remplace");
  await expect(detail.getByRole("link", { name: "Ouvrir dans la liste" })).toHaveAttribute("href", `#/vault/${DEC_NEW}`);

  /* Échap sur le canevas efface la sélection. */
  await page.locator("#atlas-canvas").focus();
  await page.keyboard.press("Escape");
  await expect(detail).not.toContainText("DEC-0002");

  /* Flèches = navigation entre notes ; Entrée = confirmation. */
  await page.mouse.move(0, 0);
  const current = page.locator('#atlas-list [aria-current="true"]');
  await page.keyboard.press("ArrowRight");
  await expect(current).toHaveCount(1);
  const first = (await current.textContent()) ?? "";
  await page.keyboard.press("ArrowRight");
  await expect(current).not.toHaveText(first);
  for (let step = 0; step < 5 && !((await current.textContent()) ?? "").includes("Stratégie de cache Redis"); step += 1) {
    const before = (await current.textContent()) ?? "";
    await page.keyboard.press("ArrowRight");
    await expect(current).not.toHaveText(before);
  }
  await expect(current).toContainText("Stratégie de cache Redis");
  await expect(detail).toContainText("DEC-0002");
  await expect(page.locator("#atlas-status")).toContainText("voisin(s) surligné(s)");
  await expect(page.locator("#atlas-list .is-neighbor").first()).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(detail).toContainText("DEC-0002");
  await page.keyboard.press("Escape");
  await expect(detail).not.toContainText("DEC-0002");

  /* 5. Bascule Liste. */
  await page.locator(".vault-modes").getByRole("link", { name: "Liste" }).click();
  await expect(page).toHaveURL(/#\/vault$/);
  await expect(page.locator(".vault-modes a[aria-current=\"page\"]")).toHaveText("Liste");
  await goHash(page, "#/vault/atlas");
  await expect(page.locator("#atlas-canvas")).toBeVisible();

  expect(errors).toEqual([]);
});

test("vault list: titles, zone, excerpt and sort", async ({ page }) => {
  const calls: string[] = [];
  const errors = await login(page, "#/vault", calls);

  const list = page.locator("#view .vault-list");
  await expect(list.locator(".vault-item")).toHaveCount(4);
  await expect(list).toContainText("Stratégie de cache Redis");
  /* Extrait du résumé serveur, zone lisible, identifiant et version. */
  await expect(list).toContainText("Redis avant PostgreSQL.");
  await expect(list.locator(".vault-zone").first()).toHaveText("Studio");
  await expect(list).toContainText("Projet · Studi'os");
  await expect(list).toContainText("DEC-0002");

  /* Tri alphabétique côté client, sans nouvelle requête serveur. */
  const before = calls.length;
  await page.selectOption("#vault-sort", "title_asc");
  await expect(list.locator(".ds-list-title a").first()).toHaveText("Cache mémoire locale");
  expect(calls.length).toBe(before);
  await page.selectOption("#vault-sort", "title_desc");
  await expect(list.locator(".ds-list-title a").first()).toHaveText("Stratégie de cache Redis");

  expect(errors).toEqual([]);
});

test("atlas: reduced motion and no external requests", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const external: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.hostname !== "127.0.0.1" && url.hostname !== "localhost") external.push(request.url());
  });
  const errors = await login(page, "#/vault/atlas", []);
  await expect(page.locator("#atlas-canvas")).toBeVisible();
  await expect.poll(() => canvasHasInk(page)).toBe(true);
  await page.locator("#atlas-list").getByRole("button", { name: "Jamais de secret en clair" }).click();
  await expect(page.locator("#atlas-detail")).toContainText("Jamais de secret en clair");
  expect(external).toEqual([]);
  expect(errors).toEqual([]);
});
