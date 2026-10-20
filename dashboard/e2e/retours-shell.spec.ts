import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const PROJECT_ID = "11111111-2222-4333-8444-555555555555";
const project = { id: PROJECT_ID, name: "Projet retours", slug: "retours", description: null, archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-10-20T00:00:00Z", version: 1 };

async function prepare(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body: unknown = [];
    if (path.endsWith("/auth/token")) body = { access_token: "retours-token", token_type: "bearer" };
    else if (path.endsWith("/review-queue")) body = { items: [] };
    else if (path.endsWith("/timeline/dates")) body = ["2026-10-20", "2026-07-09"];
    else if (path.endsWith("/timeline")) {
      const day = (url.searchParams.get("since") ?? "2026-10-20").slice(0, 10);
      const offset = Number(url.searchParams.get("offset") ?? "0");
      const total = day === "2026-10-20" ? 501 : 1;
      const events = Array.from({ length: Math.max(0, Math.min(200, total - offset)) }, (_, index) => ({
        event_id: `event-${offset + index}`, event_type: "task.updated", project_id: PROJECT_ID, task_id: null, machine_id: null,
        actor_type: "user", actor_id: "user-test", client_timestamp: `${day}T12:00:00Z`,
        server_timestamp: `${day}T${String(23 - Math.floor((offset + index) / 60)).padStart(2, "0")}:${String(59 - ((offset + index) % 60)).padStart(2, "0")}:00Z`,
        payload: { title: `${day} activité ${offset + index}` }, schema_version: 1,
      }));
      body = { project_id: PROJECT_ID, days: [{ date: day, events: [...events].reverse() }] };
    } else if (path.endsWith("/claims")) body = Array.from({ length: 25 }, (_, index) => ({
      id: `claim-${String(index).padStart(2, "0")}`, project_id: PROJECT_ID, task_id: null,
      resource_path: `fichier-${String(index).padStart(2, "0")}.py`, resource_type: "file", claimed_by_machine_id: "machine-test",
      status: index % 2 === 0 ? "active" : "released", ttl_seconds: 3600,
      created_at: `2026-10-${String(index + 1).padStart(2, "0")}T12:00:00Z`, expires_at: "2099-01-01T00:00:00Z",
    })).reverse().sort((a, b) => a.id.localeCompare(b.id));
    else if (path.endsWith("/state")) body = { project_id: PROJECT_ID, active_tasks: [], active_claims: [], generated_at: "2026-10-20T00:00:00Z" };
    else if (path === `/api/v1/projects/${PROJECT_ID}`) body = project;
    else if (path.endsWith("/projects")) body = [project];
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.addInitScript(() => localStorage.setItem("studio-os.onboarding.v1", JSON.stringify({ schema: 1, status: "completed", current: "termine" })));
}

async function login(page: Page, hash: string): Promise<void> {
  await page.goto(`/${hash}`);
  await page.fill("#login-email", "retours@example.test");
  await page.fill("#login-password", "password-test");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeAttached();
}

for (const width of [1600, 1100, 390]) {
  test(`Administration en bas, accessible au clavier à ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await prepare(page);
    await login(page, "#/design-system");
    if (width <= 900) await page.locator("#nav-open").click();
    const groups = page.locator(".app-nav > .app-navgroup");
    await expect(groups.last()).toHaveClass(/app-navgroup--admin/);
    const admin = groups.last();
    await admin.locator("summary").focus();
    await page.keyboard.press("Enter");
    await expect(admin).toHaveAttribute("open", "");
    await expect(admin.getByRole("link", { name: "Comptes", exact: true })).toBeVisible();
    const scan = await new AxeBuilder({ page }).include(".app-sidebar").analyze();
    expect(scan.violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`administration-${width}.png`) });
    if (width === 1100) {
      await page.keyboard.press("Escape");
      await expect(admin).not.toHaveAttribute("open", "");
      await expect(admin.locator("summary")).toBeFocused();
      await page.keyboard.press("Enter");
    }
    await admin.getByRole("link", { name: "Comptes", exact: true }).click();
    await expect(page).toHaveURL(/#\/accounts$/);
    await expect(admin.locator('a[href="#/accounts"]')).toHaveAttribute("aria-current", "page");
    if (width === 1100) await expect(admin).not.toHaveAttribute("open", "");
  });
}

test("réservations : ordre décroissant conservé entre pages et filtres", async ({ page }) => {
  await prepare(page);
  await login(page, `#/projects/${PROJECT_ID}/claims`);
  const rows = page.locator("[data-list] tbody tr");
  await expect(rows.first()).toContainText("fichier-24.py");
  await page.locator("[data-filter]").selectOption("all");
  await expect(rows.first()).toContainText("fichier-24.py");
  await page.getByRole("button", { name: "Suivant", exact: true }).click();
  await expect(rows.first()).toContainText("fichier-14.py");
  await page.locator("[data-filter]").selectOption("past");
  await expect(rows.first()).toContainText("fichier-23.py");
});

test("activité : plus de 500 événements, tri et accès à un ancien mois", async ({ page }, testInfo) => {
  await prepare(page);
  await login(page, `#/projects/${PROJECT_ID}/activity`);
  const items = page.locator(".tl-item");
  await expect(items).toHaveCount(200);
  await expect(items.first()).toContainText("2026-10-20 activité 0");
  await page.locator("[data-timeline-more]").click();
  await expect(items).toHaveCount(400);
  await page.locator("[data-timeline-more]").click();
  await expect(items).toHaveCount(501);
  await expect(page.locator("[data-timeline-more]")).toHaveCount(0);
  for (let i = 0; i < 3; i++) await page.getByRole("button", { name: "Mois précédent" }).click();
  await page.locator('[data-cal-day="2026-07-09"]').click();
  await expect(items).toHaveCount(1);
  await expect(items.first()).toContainText("2026-07-09 activité 0");
  await expect(page.locator("#view")).toContainText("Dates et heures en UTC");
  await page.screenshot({ path: testInfo.outputPath("activite-ancien-mois.png") });
});

test("mise à jour Desktop : installation directe, erreur, progression et redémarrage", async ({ page }, testInfo) => {
  await prepare(page);
  await page.route("**/healthz", (route) => route.fulfill({ status: 200, contentType: "application/json", body: '{"status":"ok"}' }));
  await page.addInitScript(() => {
    const state = { installs: 0, restarts: 0, finish: null as (() => void) | null };
    (window as unknown as { updateTest: typeof state }).updateTest = state;
    const invoke = async (name: string) => {
      if (name === "desktop_info") return { product: "Studi'OS Desktop", desktop_version: "0.1.0", mode: "desktop", protocol: "studio.local/v1", sidecar: { state: "not_started" } };
      if (name === "get_server_origin") return { configured: location.origin, applied: location.origin, restart_required: false };
      if (name === "check_for_update") return { state: "available", current: "0.1.0", version: "0.2.0", notes: null };
      if (name === "install_update") {
        state.installs++;
        if (state.installs === 1) throw { code: "network" };
        await new Promise<void>((resolve) => { state.finish = resolve; });
        return null;
      }
      if (name === "restart_desktop") { state.restarts++; return null; }
      if (name === "load_session") return null;
      throw new Error("Unavailable test command");
    };
    (window as unknown as { __TAURI__: unknown }).__TAURI__ = { core: { invoke } };
  });
  await login(page, "#/design-system");
  const banner = page.locator("#desktop-update-banner");
  await expect(banner.getByRole("button", { name: "Installer", exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { updateTest: { installs: number } }).updateTest.installs)).toBe(0);
  await banner.getByRole("button", { name: "Installer", exact: true }).click();
  await expect(banner.getByRole("alert")).toContainText("injoignable");
  await banner.getByRole("button", { name: "Réessayer l'installation" }).click();
  await expect(banner.locator("progress")).toBeVisible();
  await expect(banner.getByRole("button")).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath("mise-a-jour-progression.png") });
  await page.evaluate(() => (window as unknown as { updateTest: { finish: (() => void) | null } }).updateTest.finish?.());
  await banner.getByRole("button", { name: "Redémarrer l'application" }).click();
  expect(await page.evaluate(() => (window as unknown as { updateTest: { installs: number; restarts: number } }).updateTest)).toMatchObject({ installs: 2, restarts: 1 });
  await expect(page).toHaveURL(/#\/design-system$/);
});
