/**
 * Découpage du bundle (task d5c1183f) : l'accueil ne télécharge aucun chunk de
 * vue lourde ; une vue est chargée seulement à la navigation (deep link inclus) ;
 * un chunk injoignable donne une erreur annoncée avec « Réessayer ».
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const jsRequests = (page: Page): string[] => {
  const seen: string[] = [];
  page.on("request", (req) => {
    const m = /\/assets\/([A-Za-z0-9_]+)-[\w-]+\.js$/.exec(req.url());
    if (m?.[1]) seen.push(m[1]);
  });
  return seen;
};

async function login(page: Page, hash: string): Promise<void> {
  await page.route("**/api/**", async (route: Route) => {
    const url = route.request().url();
    const body = url.endsWith("/api/v1/auth/token") ? { access_token: "e2e-token", token_type: "bearer" } : url.includes("/api/v1/review-queue") ? { items: [] } : [];
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto(`/${hash}`);
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();
}

test("home loads no heavy view chunk, a heavy view loads on navigation", async ({ page }) => {
  const seen = jsRequests(page);
  await login(page, "#/");
  await expect(page.locator("#view h1").first()).toBeVisible();
  for (const heavy of ["projectDetail", "configuration", "library", "vaultAtlas", "taskDetail", "transfers", "decisionsV2", "view"]) {
    expect(seen, `chunk ${heavy} must not load on the home page`).not.toContain(heavy);
  }
  await page.goto("/#/vault/atlas");
  await expect.poll(() => seen.includes("vaultAtlas")).toBe(true);
});

test("a chunk that fails to load shows an alert with a reload action", async ({ page }) => {
  await login(page, "#/");
  let blocked = true;
  await page.route(/\/assets\/transfers-[\w-]+\.js$/, (route) => (blocked ? route.abort() : route.continue()));
  await page.goto("/#/transfers");
  await expect(page.locator("#view [role=alert]")).toContainText("Chargement impossible");
  blocked = false;
  // Rechargement : le hash est conservé, la session mémoire-seule est rouverte.
  await page.locator("#view-load-retry").click();
  await expect(page.locator("#login-form")).toBeVisible();
  expect(page.url()).toContain("#/transfers");
});
