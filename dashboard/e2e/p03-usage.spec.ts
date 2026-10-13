/**
 * P03 — Consommation (vue d'ensemble projet et fiche tâche), API stubbée.
 *
 * GET /api/v1/usage/summary est stubbé avec des données conformes à
 * components["schemas"]["UsageSummary"] : coût partiel, groupe sans coût
 * connu, durée exacte. Les valeurs affichées doivent être celles du serveur,
 * jamais un total exact fabriqué, et aucun UUID visible hors détails repliés.
 */
import { expect, test, type Page, type Route } from "@playwright/test";
import type { components } from "../src/openapi-schema";
import { apiStub, expectClean, newCaptured, P1, T1, UUID_RE, watchErrors } from "./support/ui16-stub";

type UsageSummary = components["schemas"]["UsageSummary"];
type UsageAggregate = components["schemas"]["UsageAggregate"];

const cov = (m: number, e: number, u: number) => ({ measured_entries: m, estimated_entries: e, unknown_entries: u });

function aggregate(overrides: Partial<UsageAggregate>): UsageAggregate {
  return {
    key: {},
    entries: 2,
    first_period_start: "2026-10-11T10:00:00Z",
    last_period_end: "2026-10-11T10:00:05Z",
    tokens_in: { status: "partial", known_sum: 25, ...cov(1, 0, 1) },
    tokens_out: { status: "partial", known_sum: 5, ...cov(1, 0, 1) },
    tokens_cached: { status: "partial", known_sum: 300, ...cov(1, 0, 1) },
    total_tokens: { status: "partial", known_sum: 330, ...cov(1, 0, 1) },
    cost: {
      status: "partial",
      known_sum: "0.125",
      currency: "USD",
      by_currency: [{ currency: "USD", known_sum: "0.125", entries: 1 }],
      ...cov(1, 0, 1),
    },
    duration: { status: "exact", known_sum: "17", ...cov(2, 0, 0) },
    sources: [
      { collector: "studio-claude-code", entries: 1 },
      { collector: "studio-runner", entries: 1 },
    ],
    ...overrides,
  };
}

function summary(groupBy: UsageSummary["group_by"], taskId: string | null): UsageSummary {
  const total = aggregate({});
  return {
    project_id: P1,
    task_id: taskId,
    group_by: groupBy,
    since: null,
    until: null,
    generated_at: "2026-10-13T12:00:00Z",
    total,
    groups:
      groupBy === "task"
        ? [
            aggregate({ key: { task_id: T1, task_title: "Afficher le coût" }, entries: 1 }),
            aggregate({
              key: {},
              entries: 1,
              cost: { status: "unknown", known_sum: null, currency: null, by_currency: [], ...cov(0, 0, 1) },
            }),
          ]
        : [],
    truncated: false,
  };
}

async function loginUsage(page: Page, startHash: string): Promise<string[]> {
  const urls: string[] = [];
  await page.route("**/api/**", apiStub(newCaptured()));
  await page.route("**/healthz", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.route(/\/api\/v1\/usage\/summary(\?|$)/, async (route: Route) => {
    const url = new URL(route.request().url());
    urls.push(url.toString());
    const body = summary((url.searchParams.get("group_by") ?? "none") as UsageSummary["group_by"], url.searchParams.get("task_id"));
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto(`/${startHash}`);
  await expect(page.locator("#login-form")).toBeVisible({ timeout: 15_000 });
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible({ timeout: 15_000 });
  return urls;
}

async function visibleText(page: Page, selector: string): Promise<string> {
  return page.locator(selector).first().evaluate((node) => {
    const clone = node.cloneNode(true) as HTMLElement;
    clone.querySelectorAll("details").forEach((d) => d.remove());
    return clone.textContent ?? "";
  });
}

test("vue d'ensemble projet : durée, coût partiel et sources, valeurs serveur sans UUID visible", async ({ page }) => {
  const watch = watchErrors(page);
  const urls = await loginUsage(page, `#/projects/${P1}`);
  const section = page.locator("section[data-usage]");
  await expect(section).toBeVisible({ timeout: 15_000 });
  const total = section.locator("[data-usage-total]");
  await expect(total.locator('[data-usage-metric="duration"]')).toHaveAttribute("data-usage-value", "17");
  const cost = total.locator('[data-usage-metric="cost"]');
  await expect(cost).toHaveAttribute("data-usage-status", "partial");
  await expect(cost).toHaveAttribute("data-usage-value", "0.125");
  await expect(cost).toContainText("au moins");
  await expect(total.locator("[data-usage-sources]")).toContainText("studio-claude-code (1) · studio-runner (1)");

  const groups = section.locator("[data-usage-group]");
  await expect(groups).toHaveCount(2);
  await expect(groups.nth(0)).toContainText("Afficher le coût");
  await expect(groups.nth(1)).toContainText("Sans tâche");
  await expect(groups.nth(1).locator('[data-usage-metric="cost"]')).toHaveText("inconnu");
  expect(await visibleText(page, "section[data-usage]")).not.toMatch(UUID_RE);
  expect(new URL(urls[0] ?? "").searchParams.get("group_by")).toBe("task");

  await section.locator("[data-usage-period]").selectOption("all");
  await expect.poll(() => urls.length).toBe(2);
  expect(new URL(urls[1] ?? "").searchParams.has("since")).toBe(false);
  expectClean(watch);
});

test("fiche tâche : section Consommation filtrée sur la tâche", async ({ page }) => {
  const watch = watchErrors(page);
  const urls = await loginUsage(page, `#/tasks/${T1}`);
  const section = page.locator("section[data-usage]");
  await expect(section).toBeVisible({ timeout: 15_000 });
  await expect(section.locator('[data-usage-metric="cost"]')).toContainText("au moins 0,125 USD");
  expect(await visibleText(page, "section[data-usage]")).not.toMatch(UUID_RE);
  const query = new URL(urls[0] ?? "").searchParams;
  expect(query.get("task_id")).toBe(T1);
  expect(query.get("project_id")).toBe(P1);
  expectClean(watch);
});
