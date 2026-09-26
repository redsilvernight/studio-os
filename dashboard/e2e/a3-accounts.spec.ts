/**
 * A3 — page Comptes (browser, API stubbée avec état) : un admin voit l'état
 * de chaque compte, désactive (confirmation) puis réactive un compte, révoque
 * ses sessions et consulte ses accès ; aucune action sur son propre compte.
 * Un non-admin voit une note, sans aucun appel aux routes d'administration.
 * Zéro erreur page ni CSP.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const ADMIN = "aaaaaaaa-0000-4111-8111-000000000001";
const DORA = "bbbbbbbb-0000-4111-8111-000000000002";
const P1 = "11111111-2222-4333-8444-555555555555";
const b64url = (value: string): string => Buffer.from(value).toString("base64url");
const TOKEN = `${b64url('{"alg":"none"}')}.${b64url(JSON.stringify({ sub: ADMIN, auth_version: 0 }))}.sig`;
const STAMP = "2026-09-25T10:00:00Z";

interface Stub {
  status: Record<string, "active" | "pending" | "disabled">;
  adminCalls: string[];
}

const account = (id: string, name: string, status: string): Record<string, unknown> => ({
  id,
  display_name: name,
  email: `${name.toLowerCase()}@example.test`,
  role: id === ADMIN ? "admin" : "developer",
  status,
  created_at: STAMP,
  updated_at: STAMP,
  version: 1,
});

function apiStub(role: string, stub: Stub) {
  return async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname.endsWith("/api/v1/auth/token")) {
      return json(200, { access_token: TOKEN, token_type: "bearer", expires_in: 900 });
    }
    if (url.pathname.endsWith("/api/v1/auth/me")) {
      return json(200, { user_id: ADMIN, display_name: "Ada", email: "ada@example.test", role, machine_id: ADMIN });
    }
    const action = /\/api\/v1\/users\/([^/]+)\/(disable|enable|revoke-sessions)$/.exec(url.pathname);
    if (action !== null && action[1] !== undefined) {
      stub.adminCalls.push(`${action[2]} ${action[1]}`);
      if (action[2] === "disable") stub.status[action[1]] = "disabled";
      if (action[2] === "enable") stub.status[action[1]] = "active";
      return json(200, account(action[1], "Dora", stub.status[action[1]] ?? "active"));
    }
    const memberships = /\/api\/v1\/users\/([^/]+)\/memberships$/.exec(url.pathname);
    if (memberships !== null) {
      stub.adminCalls.push("memberships");
      return json(200, [{ project_id: P1, user_id: DORA, granted_by_user_id: ADMIN, created_at: STAMP }]);
    }
    if (url.pathname.endsWith("/api/v1/users")) {
      stub.adminCalls.push("directory");
      return json(200, [account(ADMIN, "Ada", "active"), account(DORA, "Dora", stub.status[DORA] ?? "active")]);
    }
    return json(200, []);
  };
}

async function open(page: Page, role: string, stub: Stub): Promise<string[]> {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (CSP_RE.test(message.text())) errors.push(message.text());
  });
  await page.route("**/api/**", apiStub(role, stub));
  await page.goto("/#/accounts");
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#view h1")).toHaveText("Comptes");
  return errors;
}

test.describe("A3 comptes", () => {
  test("admin : état, désactivation confirmée, réactivation, sessions, accès", async ({ page }) => {
    const stub: Stub = { status: { [DORA]: "active" }, adminCalls: [] };
    const errors = await open(page, "admin", stub);
    const doraRow = page.locator(`[data-account-row="${DORA}"]`);
    const selfRow = page.locator(`[data-account-row="${ADMIN}"]`);
    await expect(selfRow).toContainText("Votre compte");
    await expect(selfRow.getByRole("button")).toHaveCount(0);
    await expect(doraRow).toContainText("Actif");

    page.once("dialog", (dialog) => void dialog.dismiss());
    await doraRow.getByRole("button", { name: "Désactiver Dora" }).click();
    expect(stub.adminCalls.filter((c) => c.startsWith("disable"))).toEqual([]);

    page.once("dialog", (dialog) => void dialog.accept());
    await doraRow.getByRole("button", { name: "Désactiver Dora" }).click();
    await expect(page.locator("[data-msg]")).toContainText("Compte désactivé");
    await expect(page.locator(`[data-account-row="${DORA}"]`)).toContainText("Désactivé");

    await page.locator(`[data-account-row="${DORA}"]`).getByRole("button", { name: "Réactiver Dora" }).click();
    await expect(page.locator(`[data-account-row="${DORA}"]`)).toContainText("Actif");

    page.once("dialog", (dialog) => void dialog.accept());
    await page.locator(`[data-account-row="${DORA}"]`).getByRole("button", { name: "Révoquer les sessions de Dora" }).click();
    await expect(page.locator("[data-msg]")).toContainText("Sessions révoquées");

    await page.locator(`[data-account-row="${DORA}"]`).getByRole("button", { name: "Voir les accès de Dora" }).click();
    await expect(page.locator(`[data-access-body="${DORA}"] a`)).toHaveAttribute("href", `#/projects/${P1}/members`);

    expect(stub.adminCalls.filter((c) => c.includes(ADMIN))).toEqual([]);
    expect(stub.adminCalls).toEqual(
      expect.arrayContaining([`disable ${DORA}`, `enable ${DORA}`, `revoke-sessions ${DORA}`, "memberships"]),
    );
    expect(errors).toEqual([]);
  });

  test("non-admin : note explicite, aucun appel d'administration", async ({ page }) => {
    const stub: Stub = { status: {}, adminCalls: [] };
    const errors = await open(page, "developer", stub);
    await expect(page.locator("#view [role=note]")).toContainText("réservée au rôle admin");
    expect(stub.adminCalls).toEqual([]);
    expect(errors).toEqual([]);
  });
});
