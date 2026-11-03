import { expect, test, type Page } from "@playwright/test";

async function adminFixture(page: Page, state: "healthy" | "attention" | "error") {
  let reads = 0;
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path.endsWith("/auth/token")) return json({ access_token: "e2e-admin-token", token_type: "bearer" });
    if (path.endsWith("/auth/me")) return json({ user_id: "user", display_name: "E2E", email: "e2e@example.test", role: "admin", machine_id: "dashboard", machine_name: "Dashboard", active: true });
    if (path.endsWith("/machines")) {
      reads++;
      return state === "error" ? json({ detail: { error_code: "forbidden" } }, 403) : json([{ id: "machine", display_name: "Bureau", owner_user_id: "user", status: state === "attention" ? "offline" : "online", last_seen_at: "2026-10-20T09:00:00Z", created_at: "2026-10-01T09:00:00Z", updated_at: "2026-10-01T09:00:00Z", version: 1 }]);
    }
    if (path.endsWith("/runtimes")) return state === "error" ? json({ detail: "indisponible" }, 503) : json(state === "attention" ? [] : [{ id: "runtime", status: "active", owner_user_id: "user", machine_id: "machine", harness_ref: "codex", provider_ref: "openai", model_ref: "configured", capabilities: { coding: true, tools: [], local: false }, version: 1, capability_source: "declared", runtime_metadata: {}, created_at: "2026-10-01T10:00:00Z" }]);
    if (path.endsWith("/runtime-bindings")) return json([{ id: "binding", level: "studio_default", owner_user_id: "user", target: { runtime_id: "runtime" }, target_kind: "agent_definition", target_stable_key: "assistant", created_at: "2026-10-01T10:00:00Z" }]);
    if (path.endsWith("/review-queue")) return state === "error" ? json({ detail: "indisponible" }, 503) : json({ items: state === "attention" ? [{ kind: "decision_proposal", id: "decision", title: "Une décision à prendre", readable_id: "DEC-0010", proposed_by_type: "user", requested_at: "2026-10-20T09:00:00Z" }] : [], generated_at: "2026-10-20T10:00:00Z" });
    if (path.endsWith("/transfers/consumption")) return state === "error" ? json({ detail: "indisponible" }, 503) : json({ consumed_bytes: state === "attention" ? 1024 : 256, quota_bytes: 1024, remaining_bytes: state === "attention" ? 0 : 768 });
    return json([]);
  });
  await page.goto("/#/administration");
  await page.locator("#login-email").fill("e2e@example.test");
  await page.locator("#login-password").fill("e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".admin-indicator")).toHaveCount(5);
  return { reads: () => reads };
}

test("administration : données saines, portée et actualisation explicites", async ({ page }) => {
  const source = await adminFixture(page, "healthy");
  await expect(page.locator(".admin .ds-hero")).toContainText("Aucun problème détecté dans les données consultées");
  await expect(page.locator(".admin")).toContainText("État local non observé");
  await expect(page.locator(".admin")).toContainText("Consulté le");
  await expect(page.locator(".admin")).toContainText("256 octets utilisés");
  const before = source.reads();
  await page.locator("[data-admin-refresh]").click();
  await expect.poll(source.reads).toBeGreaterThan(before);
  await expect(page.locator("[data-admin-refresh]")).toBeEnabled();
});

test("administration : problèmes réels actionnables et lisibles sur375px", async ({ page }, testInfo) => {
  await adminFixture(page, "attention");
  const cards = page.locator(".admin-indicator");
  await expect(cards.filter({ has: page.getByRole("heading", { name: "Postes", exact: true }) })).toContainText("1 hors ligne");
  await expect(cards.filter({ has: page.getByRole("heading", { name: "Configuration", exact: true }) })).toContainText("À compléter");
  await expect(cards.filter({ has: page.getByRole("heading", { name: "Validations", exact: true }) })).toContainText("1 en attente");
  await expect(cards.filter({ has: page.getByRole("heading", { name: "Stockage", exact: true }) })).toContainText("1 Ko utilisés");
  await expect(cards.filter({ has: page.getByRole("heading", { name: "Postes", exact: true }) }).locator("a")).toHaveAttribute("href", "#/machines");
  await expect(cards.filter({ has: page.getByRole("heading", { name: "Configuration", exact: true }) }).locator("a")).toHaveAttribute("href", "#/configuration/bindings");
  await expect(cards.filter({ has: page.getByRole("heading", { name: "Validations", exact: true }) }).locator("a")).toHaveAttribute("href", "#/decisions");
  await expect(cards.filter({ has: page.getByRole("heading", { name: "Stockage", exact: true }) }).locator("a")).toHaveAttribute("href", "#/transfers");
  await page.setViewportSize({ width: 375, height: 812 });
  if ((await page.locator("#nav-open").getAttribute("aria-expanded")) === "true") await page.locator("#nav-close").click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("admin-375.png"), fullPage: true });
  await cards.filter({ has: page.getByRole("heading", { name: "Postes", exact: true }) }).locator("a").click();
  await expect(page).toHaveURL(/#\/machines$/);
  await expect(page.locator("#view h1")).toHaveText("Postes");
});

test("administration : erreurs et refus ne sont pas présentés comme un état sain", async ({ page }) => {
  await adminFixture(page, "error");
  await expect(page.locator(".admin-indicator").filter({ hasText: "État inconnu" })).toHaveCount(4);
  await expect(page.locator(".admin .ds-hero")).not.toContainText("Aucun problème détecté");
  await expect(page.locator(".admin")).toContainText("4 point(s) à vérifier");
});
