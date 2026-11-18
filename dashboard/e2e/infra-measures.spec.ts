import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const point = (value: number, at: string) => ({ measured_at: at, value });
const report = {
  window_days: 7,
  generated_at: "2026-11-18T12:00:00Z",
  series: [
    { metric: "pg_table_bytes", subject: "events", project_id: null, latest: point(2048, "2026-11-18T11:45:00Z"), points: [point(1024, "2026-11-18T10:00:00Z"), point(2048, "2026-11-18T11:45:00Z")] },
    { metric: "sse_connections", subject: "", project_id: null, latest: point(3, "2026-11-18T11:45:00Z"), points: [point(3, "2026-11-18T11:45:00Z")] },
  ],
};

async function open(page: import("@playwright/test").Page, role: "admin" | "developer") {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path.endsWith("/auth/token")) return json({ access_token: "e2e-token", token_type: "bearer" });
    if (path.endsWith("/auth/me")) return json({ user_id: "user", display_name: "E2E", email: "e2e@example.test", role, machine_id: "dashboard", machine_name: "Dashboard", active: true });
    if (path.endsWith("/internal/infra-measurements")) return role === "admin" ? json(report) : json({ detail: "insufficient role" }, 403);
    return json([]);
  });
  await page.goto("/#/administration/mesures");
  await page.locator("#login-email").fill("e2e@example.test");
  await page.locator("#login-password").fill("e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
}

test("mesures : tableau, courbes et scan axe", async ({ page }) => {
  await open(page, "admin");
  await expect(page.locator("#view h1")).toHaveText("Mesures d'infrastructure");
  await expect(page.locator("#view table tbody tr")).toHaveCount(2);
  await expect(page.locator("#view")).toContainText("Table PostgreSQL · events");
  await expect(page.locator("#view svg[role=img]")).toHaveCount(2);
  const results = await new AxeBuilder({ page }).include("#view").analyze();
  expect(results.violations).toEqual([]);
});

test("mesures : un non-admin voit un refus lisible", async ({ page }) => {
  await open(page, "developer");
  await expect(page.locator("#view")).toContainText("Réservé aux administrateurs.");
});
