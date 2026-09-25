/**
 * A0 — isolation projet côté dashboard (API stubbée) : un 403 `resource:
 * project` n'est pas une erreur d'authentification (pas de déconnexion,
 * message d'accès), le flux SSE refusé en 403 s'arrête sans boucle de retry
 * et le signale, et une liste de projets vide explique comment obtenir
 * l'accès. Zéro erreur page ni CSP.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const P1 = "11111111-2222-4333-8444-555555555555";
const USER = "aaaaaaaa-0000-4111-8111-000000000001";

const PROJECT = {
  id: P1,
  slug: "phare",
  name: "Jeu Phare",
  description: null,
  archived: false,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-10T10:00:00Z",
  version: 1,
};

const DENIED = { detail: { error_code: "forbidden", message: "forbidden", resource: "project", action: "read" } };

const b64url = (value: string): string => Buffer.from(value).toString("base64url");
const jwt = `${b64url('{"alg":"none"}')}.${b64url(JSON.stringify({ sub: USER, role: "developer" }))}.sig`;

interface Stub {
  projects: unknown[];
  denyProject: boolean;
  streamCalls: number;
}

function apiStub(stub: Stub) {
  return async (route: Route) => {
    const url = route.request().url();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) return json(200, { access_token: jwt, token_type: "bearer" });
    if (url.includes("/api/v1/events/stream")) {
      stub.streamCalls += 1;
      return json(403, DENIED);
    }
    if (url.includes(`/projects/${P1}`) && stub.denyProject) return json(403, DENIED);
    if (url.includes("/state")) return json(200, { project_id: P1, active_tasks: [], active_claims: [], generated_at: PROJECT.updated_at });
    if (/\/api\/v1\/projects\/[^/]+$/.test(url)) return json(200, PROJECT);
    if (url.endsWith("/api/v1/projects")) return json(200, stub.projects);
    if (url.includes("/api/v1/review-queue")) return json(200, { items: [] });
    return json(200, []);
  };
}

async function login(page: Page, hash: string, stub: Stub): Promise<void> {
  await page.route("**/api/**", apiStub(stub));
  await page.goto(`/${hash}`);
  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();
}

function watchErrors(page: Page): { csp: string[]; fatal: Error[] } {
  const csp: string[] = [];
  const fatal: Error[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && CSP_RE.test(msg.text())) csp.push(msg.text());
  });
  page.on("pageerror", (error) => fatal.push(error));
  return { csp, fatal };
}

test.describe("A0 isolation projet", () => {
  test("projet refusé (403) : message d'accès, session conservée", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const stub: Stub = { projects: [PROJECT], denyProject: true, streamCalls: 0 };
    await login(page, `#/projects/${P1}`, stub);
    await expect(page.locator("#view")).toContainText("Vous n'avez pas accès à ce projet");
    await expect(page.locator("#login-form")).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText("Session expirée");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("flux temps réel refusé (403) : arrêt définitif et bannière", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const stub: Stub = { projects: [PROJECT], denyProject: false, streamCalls: 0 };
    await login(page, "#/projects", stub);
    // Le flux temps réel s'ouvre sur le projet sélectionné dans la liste.
    await page.locator(`[data-open="${P1}"]`).first().click();
    await expect(page.locator("#conflict-banner")).toContainText("Accès à ce projet refusé");
    const calls = stub.streamCalls;
    expect(calls).toBeGreaterThan(0);
    await page.waitForTimeout(3000);
    expect(stub.streamCalls).toBe(calls);
    await expect(page.locator("#login-form")).toHaveCount(0);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("aucun projet accessible : état vide explicite", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const stub: Stub = { projects: [], denyProject: false, streamCalls: 0 };
    await login(page, "#/projects", stub);
    await expect(page.locator("#view")).toContainText("Aucun projet accessible");
    await expect(page.locator("#view")).toContainText("demandez à un administrateur");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});
