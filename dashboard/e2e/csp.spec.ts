/**
 * Browser CSP test (DEC-0061): boot the built dashboard under the Report-Only
 * policy, stub the API (no backend in this job), walk the main hash routes
 * and fail on any CSP violation or page error.
 *
 * Enforcement stays OFF until this spec is green on the authenticated main
 * flows — that green run is the documented exit condition from Report-Only.
 */
import { expect, test } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;

const MAIN_ROUTES = [
  "#/",
  "#/projects",
  "#/tasks",
  "#/machines",
  "#/decisions",
  "#/transfers",
  "#/library",
  "#/library/rules",
  "#/configuration/runtimes",
  "#/configuration/bindings",
  "#/configuration/project",
  "#/inspector",
  "#/design-system",
];

test("main flows run with zero CSP violations and zero page errors", async ({ page }) => {
  const cspErrors: string[] = [];
  const pageErrors: Error[] = [];

  page.on("console", (msg) => {
    if (msg.type() === "error" && CSP_RE.test(msg.text())) cspErrors.push(msg.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error));

  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (url.endsWith("/api/v1/auth/token")) {
      await json(200, { access_token: "e2e-token", token_type: "bearer" });
      return;
    }
    if (url.endsWith("/api/v1/machines")) {
      // No GET /api/v1/machines exists (DEC checklist DASH-4): the view must
      // degrade to the Derived presence instead of crashing.
      await json(404, { detail: "not found" });
      return;
    }
    if (url.includes("/api/v1/review-queue")) {
      await json(200, { items: [] });
      return;
    }
    if (url.includes("/api/v1/transfers/consumption")) {
      await json(200, { used_bytes: 0, remaining_bytes: 0, quota_bytes: 0 });
      return;
    }
    await json(200, []);
  });

  const response = await page.goto("/");
  expect(response?.headers()["content-security-policy-report-only"]).toContain(
    "default-src 'self'",
  );

  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();

  for (const hash of MAIN_ROUTES) {
    await page.evaluate((h) => {
      window.location.hash = h;
    }, hash);
    await expect(page.locator("#view")).not.toBeEmpty({ timeout: 10_000 });
  }

  expect(cspErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
