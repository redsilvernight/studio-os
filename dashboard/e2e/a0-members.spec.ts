/**
 * A0 — onglet Membres du workspace projet (browser, API stubbée avec état) :
 * un admin liste, ajoute (201 puis 200 « déjà membre ») et retire (204,
 * confirmation) ; un UUID invalide est refusé sans appel ; un non-admin voit
 * une note, sans aucun appel aux routes membres. Zéro erreur page ni CSP.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const P1 = "11111111-2222-4333-8444-555555555555";
const ADMIN = "aaaaaaaa-0000-4111-8111-000000000001";
const DEV = "bbbbbbbb-0000-4111-8111-000000000002";

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

const b64url = (value: string): string => Buffer.from(value).toString("base64url");
const jwt = (role: string): string => `${b64url('{"alg":"none"}')}.${b64url(JSON.stringify({ sub: ADMIN, role }))}.sig`;

interface Stub {
  members: Array<{ project_id: string; user_id: string; granted_by_user_id: string | null; created_at: string }>;
  memberCalls: string[];
}

function apiStub(role: string, stub: Stub) {
  return async (route: Route) => {
    const request = route.request();
    const url = request.url();
    const json = (status: number, body?: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: body === undefined ? "" : JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) return json(200, { access_token: jwt(role), token_type: "bearer" });
    const member = /\/api\/v1\/projects\/[^/]+\/members(?:\/([^/?]+))?/.exec(url);
    if (member !== null) {
      stub.memberCalls.push(`${request.method()} ${member[1] ?? ""}`.trim());
      const userId = member[1];
      if (request.method() === "GET") return json(200, stub.members);
      if (request.method() === "PUT" && userId !== undefined) {
        const existing = stub.members.find((m) => m.user_id === userId);
        if (existing !== undefined) return json(200, existing);
        const created = { project_id: P1, user_id: userId, granted_by_user_id: ADMIN, created_at: "2026-09-25T10:00:00Z" };
        stub.members.push(created);
        return json(201, created);
      }
      if (request.method() === "DELETE" && userId !== undefined) {
        stub.members = stub.members.filter((m) => m.user_id !== userId);
        return route.fulfill({ status: 204 });
      }
    }
    if (url.includes("/state")) return json(200, { project_id: P1, active_tasks: [], active_claims: [], generated_at: PROJECT.updated_at });
    if (/\/api\/v1\/projects\/[^/]+$/.test(url)) return json(200, PROJECT);
    if (url.endsWith("/api/v1/projects")) return json(200, [PROJECT]);
    if (url.includes("/api/v1/review-queue")) return json(200, { items: [] });
    return json(200, []);
  };
}

async function login(page: Page, role: string, stub: Stub): Promise<void> {
  await page.route("**/api/**", apiStub(role, stub));
  await page.goto(`/#/projects/${P1}/members`);
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

test.describe("A0 membres du projet", () => {
  test("admin : liste, ajout, ré-ajout sans effet, retrait confirmé", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const stub: Stub = { members: [], memberCalls: [] };
    await login(page, "admin", stub);
    const panel = page.locator("#workspace-panel");
    await expect(page.locator('[data-ws-tab="members"]')).toHaveAttribute("aria-selected", "true");
    await expect(panel).toContainText("Aucun membre");

    const input = panel.locator('input[name="user_id"]');
    await input.fill("pas-un-uuid");
    await panel.locator("[data-grant] button[type=submit]").click();
    await expect(panel.locator("[data-grant-msg]")).toContainText("UUID");
    expect(stub.memberCalls.filter((c) => c.startsWith("PUT"))).toHaveLength(0);

    await input.fill(DEV);
    await panel.locator("[data-grant] button[type=submit]").click();
    await expect(panel.locator("[data-msg]")).toHaveText("Membre ajouté.");
    await expect(panel.locator("tbody tr")).toHaveCount(1);
    await expect(panel.locator("tbody")).toContainText(DEV);

    await panel.locator('input[name="user_id"]').fill(DEV);
    await panel.locator("[data-grant] button[type=submit]").click();
    await expect(panel.locator("[data-msg]")).toHaveText("Déjà membre : accès inchangé.");
    await expect(panel.locator("tbody tr")).toHaveCount(1);

    page.once("dialog", (dialog) => void dialog.accept());
    await panel.locator(`[data-revoke="${DEV}"]`).click();
    await expect(panel.locator("[data-msg]")).toHaveText("Membre retiré.");
    await expect(panel).toContainText("Aucun membre");
    expect(stub.memberCalls).toContain(`DELETE ${DEV}`);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("non-admin : note explicite, aucun appel aux routes membres", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const stub: Stub = { members: [], memberCalls: [] };
    await login(page, "developer", stub);
    const panel = page.locator("#workspace-panel");
    await expect(panel).toContainText("réservée au rôle admin");
    await expect(panel.locator("[data-grant]")).toHaveCount(0);
    expect(stub.memberCalls).toEqual([]);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});
