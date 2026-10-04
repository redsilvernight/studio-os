/**
 * UX V2 P03-shell: adaptive shell at the three target widths (icon rail under
 * 1400 px, full sidebar above), Administration separated at the foot, a single
 * connection status (C4) and the Ctrl K « Aller à… » palette.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

async function apiStub(route: Route): Promise<void> {
  const url = route.request().url();
  const json = (status: number, body: unknown): Promise<void> =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  if (url.endsWith("/api/v1/auth/token")) return json(200, { access_token: "e2e-token", token_type: "bearer" });
  if (url.includes("/api/v1/review-queue")) return json(200, { items: [] });
  if (url.includes("/api/v1/transfers/consumption")) return json(200, { used_bytes: 0, remaining_bytes: 0, quota_bytes: 0 });
  if (url.endsWith("/api/v1/machines")) return json(404, { detail: "not found" });
  return json(200, []);
}

async function login(page: Page): Promise<void> {
  await page.route("**/api/**", apiStub);
  await page.goto("/#/");
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();
}

const WIDTHS = [
  { width: 1280, rail: true },
  { width: 1600, rail: false },
  { width: 2560, rail: false },
];

for (const { width, rail } of WIDTHS) {
  test(`shell at ${width}px: ${rail ? "icon rail" : "full sidebar"}, Administration at the foot`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await login(page);
    const sidebar = page.locator(".app-sidebar");
    const box = await sidebar.boundingBox();
    expect(box?.x).toBe(0);
    if (rail) expect(box?.width).toBeLessThan(100);
    else expect(box?.width).toBeGreaterThan(200);

    // Daily entries stay visible; the short label is used in the rail.
    const daily = page.locator(".app-navgroup").first().locator("a");
    await expect(daily).toHaveCount(5);
    for (const link of await daily.all()) await expect(link).toBeVisible();
    await expect(page.locator('.app-sidebar a[href="#/decisions"] .app-lbl-short')).toBeVisible({ visible: rail });
    await expect(page.locator('.app-sidebar a[href="#/decisions"]')).toHaveAccessibleName("À valider");

    // Administration sits below the daily group, separated at the foot.
    const admin = page.locator("details.app-navgroup--secondary").first();
    const dailyBox = await page.locator(".app-navgroup").first().boundingBox();
    const adminBox = await admin.boundingBox();
    expect((adminBox?.y ?? 0) - ((dailyBox?.y ?? 0) + (dailyBox?.height ?? 0))).toBeGreaterThan(16);
    // P05-admin: one Administration entry + 6 families, experts outside it.
    await expect(page.locator('.app-sidebar a[href="#/administration"]')).toHaveCount(1);
    await expect(page.locator('.app-sidebar a[href="#/workspaces"]')).toHaveCount(1);
    await admin.evaluate((el) => {
      (el as HTMLDetailsElement).open = true;
    });
    await expect(page.locator('.app-sidebar a[href="#/workspaces"]')).toHaveAccessibleName(/Espaces de travail/);

    // Exactly one connection status, in the avatar block; no top bar on desktop.
    await expect(page.locator('[data-testid="connection-status"]')).toHaveCount(1);
    await expect(page.locator('.app-me [data-testid="connection-status"]')).toBeVisible();
    await expect(page.locator("header.app-topbar")).toBeHidden();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test("Ctrl K opens the « Aller à… » palette and navigates", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await login(page);
  await page.keyboard.press("Control+k");
  const input = page.locator("#app-palette-input");
  await expect(input).toBeFocused();
  await input.fill("configuration");
  await expect(page.locator("#app-palette-list [role=option]")).toHaveCount(1);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/configuration\/runtimes$/);
  await expect(page.locator("#app-palette")).toBeHidden();

  await page.locator("#palette-open").click();
  await expect(input).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("#app-palette")).toBeHidden();
  await expect(page.locator("#palette-open")).toBeFocused();
});

test("P05-admin overview: one entry, six families, no identifier by default", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await login(page);
  await page.goto("/#/administration");
  const view = page.locator("#view");
  await expect(view.locator("h1")).toContainText("Administration");
  for (const href of ["#/machines", "#/accounts", "#/transfers", "#/library", "#/configuration/runtimes", "#/workspaces"]) {
    await expect(view.locator(`a[href="${href}"]`).first()).toBeVisible();
  }
  await expect(view).not.toContainText("Connecté");
});
