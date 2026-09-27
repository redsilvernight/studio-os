/**
 * A2 — fin de session (DEC-0110) : une session révoquée côté serveur (401 sur
 * le token courant) renvoie au login avec un message explicite, sans boucle
 * de reconnexion ni appel API après la déconnexion ; se reconnecter rétablit
 * l'interface. Zéro erreur page ni CSP.
 */
import { expect, test, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const USER = "aaaaaaaa-0000-4111-8111-000000000001";
const b64url = (value: string): string => Buffer.from(value).toString("base64url");
const token = (n: number): string =>
  `${b64url('{"alg":"none"}')}.${b64url(JSON.stringify({ sub: USER, auth_version: n }))}.sig`;

interface State {
  revoked: boolean;
  logins: number;
  refused: number;
}

function apiStub(state: State) {
  return async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname.endsWith("/api/v1/auth/token")) {
      state.logins += 1;
      state.revoked = false;
      return json(200, { access_token: token(state.logins), token_type: "bearer", expires_in: 900 });
    }
    if (state.revoked) {
      state.refused += 1;
      return json(401, { detail: "invalid or revoked machine token" });
    }
    return json(200, []);
  };
}

test("une session révoquée renvoie au login avec un message, sans boucle", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (CSP_RE.test(message.text())) errors.push(message.text());
  });
  const state: State = { revoked: false, logins: 0, refused: 0 };
  await page.route("**/api/**", apiStub(state));

  await page.goto("/#/projects");
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#login-form")).toHaveCount(0);

  state.revoked = true;
  await page.evaluate(() => {
    location.hash = "#/machines";
  });

  await expect(page.getByTestId("login-notice")).toHaveText(
    "Votre session a expiré ou a été révoquée. Reconnectez-vous pour continuer.",
  );
  const refusedAtNotice = state.refused;
  await page.waitForTimeout(1500);
  expect(state.refused).toBe(refusedAtNotice);
  expect(refusedAtNotice).toBeLessThanOrEqual(10);

  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#login-form")).toHaveCount(0);
  expect(state.logins).toBe(2);
  expect(errors).toEqual([]);
});
