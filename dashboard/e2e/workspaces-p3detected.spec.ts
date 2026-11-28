/**
 * P3-detected — « Dépôts détectés non suivis » sur #/reglages/dossiers (Desktop).
 *
 * Web : la page reste une notice Desktop, sans pont ni section détectée.
 * Desktop : un `invoke` Tauri simulé joue le pont local (commandes
 * `workspace.*` dont `workspace.list_detected`) ; l'API REST est stubbée
 * par route. Parcours : Lier (admin/developer) → remote ajouté au projet,
 * dossier suivi sans autre action ; viewer → pas de Lier, aide textuelle.
 */
import { expect, test, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { expectClean, watchErrors } from "./support/ui16-stub";

const PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const CSP_RE = /content security policy|securitypolicyviolation/i;

async function apiStub(role: string, repositoriesStatus: number) {
  const calls: string[] = [];
  const stub = async (route: Route): Promise<void> => {
    const req = route.request();
    const url = req.url();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) return json(200, { access_token: "e2e-token", token_type: "bearer" });
    if (url.endsWith("/api/v1/auth/me")) {
      return json(200, { user_id: "00000000-0000-4000-8000-0000000000e2", display_name: "E2E", email: "e2e@example.test", role, machine_id: "m1" });
    }
    if (req.method() === "POST" && /\/api\/v1\/projects\/[^/]+\/repositories$/.test(url)) {
      calls.push(`${req.method()} ${url.replace(/^https?:\/\/[^/]+/, "")}`);
      return repositoriesStatus < 300
        ? json(repositoriesStatus, { project_id: PROJECT_ID, url: "github.com/org/untracked-game", created_at: "2026-11-10T10:00:00Z", created_by: null })
        : json(repositoriesStatus, { detail: { error_code: "repository_already_linked", message: "already linked" } });
    }
    if (url.endsWith("/api/v1/projects")) {
      return json(200, [{ id: PROJECT_ID, slug: "mon-jeu", name: "Mon jeu", description: null, archived: false, created_at: "2026-11-01T10:00:00Z", updated_at: "2026-11-10T10:00:00Z", version: 1 }]);
    }
    if (url.includes("/api/v1/review-queue")) return json(200, { items: [] });
    if (url.includes("/api/v1/transfers/consumption")) return json(200, { used_bytes: 0, remaining_bytes: 0, quota_bytes: 0 });
    if (url.endsWith("/api/v1/machines")) return json(404, { detail: "not found" });
    if (url.includes("/api/v1/events/stream")) return new Promise<void>(() => {});
    return json(200, []);
  };
  return { stub, calls };
}

async function installDesktop(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "studio-os.onboarding.v1",
      JSON.stringify({ schema: 1, status: "completed", current: "termine" }),
    );
    let detected = [
      { root: "C:/Projects/untracked-game", remotes: ["github.com/org/untracked-game"], reason: "not_found", last_seen_at: "2026-11-10T09:00:00Z" },
    ];
    let saved: Record<string, unknown>[] = [];
    const log: string[] = [];
    (window as unknown as { __bridgeLog: string[] }).__bridgeLog = log;
    const error = (req: { message_id: string; correlation_id: string }, code: string, reason: string) => ({
      kind: "error",
      protocol: "studio.local/v1",
      message_id: "daemon-error",
      request_id: req.message_id,
      correlation_id: req.correlation_id,
      sent_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
      error: { code, component: "workspace", message: "refused", retryable: false, correlation_id: null, details: { reason } },
    });
    const invoke = async (name: string, args?: { request?: { command: string; message_id: string; correlation_id: string; payload: Record<string, unknown> } }) => {
      if (name === "desktop_info") {
        return { product: "Studi'OS Desktop", desktop_version: "0.1.0", mode: "desktop", protocol: "studio.local/v1", sidecar: { state: "not_started" } };
      }
      if (name === "get_server_origin") return { configured: location.origin, applied: location.origin, restart_required: false };
      if (name !== "bridge_request" || !args?.request) throw new Error("unexpected " + name);
      const req = args.request;
      log.push(req.command);
      const answer = (payload: unknown) => ({
        kind: "response",
        protocol: "studio.local/v1",
        message_id: "daemon-" + log.length,
        request_id: req.message_id,
        correlation_id: req.correlation_id,
        sent_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
        command: req.command,
        payload,
      });
      if (req.command === "identity.get_view") {
        const profile = { profile_id: "default", server_origin: location.origin };
        return answer({ profile, machine: { machine_id: "11111111-2222-4333-8444-555555555555", machine_name: "poste-e2e", profile, registered_at: "2026-11-10T09:00:00Z" } });
      }
      if (req.command === "workspace.list") {
        return answer({
          items: saved.map((config) => {
            const workspace_id = (config as { workspace_id: string }).workspace_id;
            return { workspace_id, health: "valid", action: "none", config };
          }),
        });
      }
      if (req.command === "workspace.list_detected") return answer({ items: detected });
      if (req.command === "workspace.confirm_roots") return answer({ root_confirmation_id: "rc-e2e", expires_in_s: 600 });
      if (req.command === "workspace.save_config") {
        const config = req.payload["config"] as Record<string, unknown>;
        saved = [...saved, config];
        const roots = config["roots"] as { workspace_root: string };
        detected = detected.filter((item) => item.root !== roots.workspace_root);
        return answer(config);
      }
      return error(req, "not_supported", "unsupported");
    };
    (window as unknown as { __TAURI__: unknown }).__TAURI__ = { core: { invoke } };
  });
}

async function login(page: Page, role: string, repositoriesStatus: number): Promise<string[]> {
  const { stub, calls } = await apiStub(role, repositoriesStatus);
  await page.route("**/api/**", stub);
  await page.goto("/#/reglages/dossiers");
  await expect(page.locator("#login-form")).toBeVisible({ timeout: 15_000 });
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("workspaces-desktop")).toBeVisible({ timeout: 15_000 });
  return calls;
}

const bridgeCalls = (page: Page): Promise<string[]> =>
  page.evaluate(() => (window as unknown as { __bridgeLog: string[] }).__bridgeLog);

test.describe("workspaces P3-detected (web)", () => {
  test("states this is a Desktop feature, with no detected section", async ({ page }) => {
    const cspErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && CSP_RE.test(msg.text())) cspErrors.push(msg.text());
    });
    const { stub } = await apiStub("admin", 201);
    await page.route("**/api/**", stub);
    await page.goto("/#/reglages/dossiers");
    await expect(page.locator("#login-form")).toBeVisible({ timeout: 15_000 });
    await page.fill("#login-email", "e2e@example.test");
    await page.fill("#login-password", "e2e-secret");
    await page.locator("#login-form button[type=submit]").click();
    await expect(page.locator(".app-sidebar")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("workspaces-web")).toContainText("Studi'OS Desktop");
    await expect(page.getByTestId("detected-repos")).toHaveCount(0);
    expect(cspErrors).toEqual([]);
  });
});

test.describe("workspaces P3-detected (Desktop)", () => {
  test("developer links a detected repo in one gesture: remote added, folder tracked", async ({ page }) => {
    const watch = watchErrors(page);
    await installDesktop(page);
    const apiCalls = await login(page, "developer", 201);
    const section = page.getByTestId("detected-repos");
    await expect(section).toContainText("Dépôts détectés non suivis");
    await expect(section).toContainText("untracked-game");
    await expect(section).toContainText("github.com/org/untracked-game");
    expect(await section.textContent()).not.toContain("C:/Projects/untracked-game");
    expect(await new AxeBuilder({ page }).include('[data-testid="detected-repos"]').withTags(["wcag2a", "wcag2aa"]).analyze().then((result) => result.violations)).toEqual([]);

    const link = section.getByRole("button", { name: /Lier .* au projet sélectionné/ });
    await expect(link).toHaveCount(1);
    await link.click();
    await expect(page.locator('[data-testid="workspaces-desktop"]')).toContainText("Dépôt lié au projet", { timeout: 10_000 });
    expect(apiCalls.some((call) => call === `POST /api/v1/projects/${PROJECT_ID}/repositories`)).toBe(true);
    const calls = await bridgeCalls(page);
    expect(calls).toEqual(expect.arrayContaining(["workspace.list_detected", "workspace.confirm_roots", "workspace.save_config"]));
    await expect(section).toContainText("Aucun dépôt détecté non suivi");
    await expect(page.locator('[data-testid="workspaces-desktop"]')).toContainText("untracked-game");
    expectClean(watch);
  });

  test("keyboard only: tab to the link button and confirm with Enter", async ({ page }) => {
    const watch = watchErrors(page);
    await installDesktop(page);
    await login(page, "admin", 201);
    const section = page.getByTestId("detected-repos");
    const link = section.getByRole("button", { name: /Lier .* au projet sélectionné/ });
    await link.focus();
    await expect(link).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator('[data-testid="workspaces-desktop"]')).toContainText("Dépôt lié au projet", { timeout: 10_000 });
    expectClean(watch);
  });

  test("viewer never sees the link action, only the access request help", async ({ page }) => {
    const watch = watchErrors(page);
    await installDesktop(page);
    await login(page, "viewer", 201);
    const section = page.getByTestId("detected-repos");
    await expect(section).toContainText("untracked-game");
    await expect(section.getByRole("button", { name: /Lier/ })).toHaveCount(0);
    await expect(section).toContainText("Demander l'accès");
    expect(await new AxeBuilder({ page }).include('[data-testid="detected-repos"]').withTags(["wcag2a", "wcag2aa"]).analyze().then((result) => result.violations)).toEqual([]);
    expectClean(watch);
  });

  test("a repo already linked elsewhere reports honestly and tracks nothing", async ({ page }) => {
    const watch = watchErrors(page);
    await installDesktop(page);
    await login(page, "admin", 409);
    const section = page.getByTestId("detected-repos");
    await section.getByRole("button", { name: /Lier .* au projet sélectionné/ }).click();
    await expect(page.locator('[data-testid="workspaces-desktop"]')).toContainText("déjà rattaché à un autre projet", { timeout: 10_000 });
    await expect(section).toContainText("untracked-game");
    expectClean(watch, [/Failed to load resource.*409/]);
  });
});
