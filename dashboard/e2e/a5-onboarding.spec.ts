/**
 * A5 — onboarding Web (API stubbée) : visite → inscription → lien reçu →
 * vérification → connexion → « En attente d'accès » → accès attribué →
 * tableau de bord. Le secret du lien quitte l'adresse avant tout rendu ;
 * ni secret ni jeton dans le stockage, l'URL ou la console. Chaque état
 * d'erreur a son écran ou son message fixe. Zéro erreur page ni CSP.
 */
import { expect, test, type Page, type Request, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const USER = "aaaaaaaa-0000-4111-8111-00000000a5a5";
const P1 = "11111111-2222-4333-8444-5555555555a5";
const SECRET = "A5-verification-secret-0123456789abcdef";
const PASSWORD = "correct horse battery";

const b64url = (value: string): string => Buffer.from(value).toString("base64url");
const JWT = `${b64url('{"alg":"none"}')}.${b64url(JSON.stringify({ sub: USER, auth_version: 0 }))}.sig`;

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

interface Stub {
  registration: "open" | "closed";
  verifyStatus: number;
  forgotStatus: number;
  loginStatus: number;
  projects: unknown[];
  requests: Request[];
}

const newStub = (overrides: Partial<Stub> = {}): Stub => ({
  registration: "open",
  verifyStatus: 200,
  forgotStatus: 202,
  loginStatus: 200,
  projects: [],
  requests: [],
  ...overrides,
});

const coded = (code: string) => ({ detail: { error_code: code } });

function apiStub(stub: Stub) {
  return async (route: Route) => {
    const request = route.request();
    const url = request.url();
    stub.requests.push(request);
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/register") || url.endsWith("/api/v1/auth/resend-verification")) {
      return stub.registration === "open" ? json(202, { status: "accepted" }) : json(404, coded("registration_unavailable"));
    }
    if (url.endsWith("/api/v1/auth/verify-email")) {
      return stub.verifyStatus === 200 ? json(200, { status: "verified" }) : json(stub.verifyStatus, coded("invalid_or_expired_token"));
    }
    if (url.endsWith("/api/v1/auth/forgot-password")) {
      return stub.forgotStatus === 202 ? json(202, { status: "accepted" }) : json(stub.forgotStatus, { detail: "rate limit exceeded" });
    }
    if (url.endsWith("/api/v1/auth/token")) {
      return stub.loginStatus === 200
        ? json(200, { access_token: JWT, token_type: "bearer", expires_in: 900 })
        : json(stub.loginStatus, { detail: "invalid email or password" });
    }
    if (url.endsWith("/api/v1/auth/me")) {
      return json(200, { user_id: USER, display_name: "Ada", email: "ada@example.test", role: "readonly", machine_id: null });
    }
    if (url.includes("/api/v1/events/stream")) return json(200, []);
    if (url.includes("/state")) return json(200, { project_id: P1, active_tasks: [], active_claims: [], generated_at: PROJECT.updated_at });
    if (/\/api\/v1\/projects\/[^/?]+$/.test(url)) return json(200, PROJECT);
    if (url.endsWith("/api/v1/projects")) return json(200, stub.projects);
    if (url.includes("/api/v1/review-queue")) return json(200, { items: [] });
    return json(200, []);
  };
}

function watch(page: Page): { csp: string[]; fatal: Error[]; console: string[] } {
  const seen = { csp: [] as string[], fatal: [] as Error[], console: [] as string[] };
  page.on("console", (msg) => {
    seen.console.push(msg.text());
    if (msg.type() === "error" && CSP_RE.test(msg.text())) seen.csp.push(msg.text());
  });
  page.on("pageerror", (error) => seen.fatal.push(error));
  return seen;
}

async function storageDump(page: Page): Promise<string> {
  return page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage }, cookie: document.cookie }));
}

const screen = (page: Page, name: string) => page.locator(`[data-testid=account-screen][data-screen="${name}"]`);

async function submitAccountForm(page: Page): Promise<void> {
  await page.locator("[data-testid=account-screen] form button[type=submit]").click();
}

test.describe("A5 onboarding Web", () => {
  test("visite → inscription → vérification → attente d'accès → accès attribué → tableau de bord", async ({ page }) => {
    const seen = watch(page);
    const stub = newStub();
    await page.route("**/api/**", apiStub(stub));

    // Visite : l'écran de connexion propose la création de compte.
    await page.goto("/");
    await expect(page.locator("#login-form")).toBeVisible();
    await page.locator("a[data-account-action=register]").click();
    await expect(screen(page, "register")).toBeVisible();
    expect(new URL(page.url()).hash).toBe("#/inscription");
    await page.fill("input[name=email]", "ada@example.test");
    await submitAccountForm(page);
    await expect(screen(page, "sent")).toContainText("Si une inscription est possible pour « ada@example.test »");
    const register = stub.requests.find((r) => r.url().endsWith("/api/v1/auth/register"))!;
    expect(register.postDataJSON()).toEqual({ email: "ada@example.test" });
    expect(register.headers()["idempotency-key"]).toBeTruthy();
    expect(register.headers()["authorization"]).toBeUndefined();

    // Lien reçu par email : le secret quitte l'adresse avant toute saisie.
    await page.goto(`/verify-email#token=${SECRET}`);
    await expect(screen(page, "verify")).toBeVisible();
    expect(page.url()).not.toContain(SECRET);
    expect(new URL(page.url()).pathname).toBe("/");
    await expect(page.locator("body")).not.toContainText(SECRET);
    await page.fill("input[name=display_name]", "Ada");
    await page.fill("input[name=password]", PASSWORD);
    await page.fill("input[name=confirmation]", PASSWORD);
    await submitAccountForm(page);
    await expect(screen(page, "verified")).toContainText("Votre compte est actif");
    const verify = stub.requests.find((r) => r.url().endsWith("/api/v1/auth/verify-email"))!;
    expect(verify.postDataJSON()).toEqual({ token: SECRET, password: PASSWORD, display_name: "Ada" });

    // Connexion : compte actif sans projet → attente d'accès.
    await submitAccountForm(page);
    await expect(page.locator("#login-form")).toBeVisible();
    await page.fill("#login-email", "ada@example.test");
    await page.fill("#login-password", PASSWORD);
    await page.locator("#login-form button[type=submit]").click();
    await expect(page.locator("[data-testid=awaiting-access]")).toBeVisible();
    await expect(page.locator("#view h1")).toContainText("En attente d'accès");

    // Accès attribué côté serveur : « Vérifier à nouveau » ouvre le tableau de bord.
    stub.projects = [PROJECT];
    await page.locator("[data-testid=awaiting-access-recheck]").click();
    await expect(page.locator("[data-testid=awaiting-access]")).toHaveCount(0);
    await expect(page.locator("#view")).toContainText("Jeu Phare");

    // Ni secret ni jeton hors mémoire.
    const dump = await storageDump(page);
    for (const secret of [SECRET, JWT, PASSWORD]) {
      expect(dump).not.toContain(secret);
      expect(page.url()).not.toContain(secret);
      expect(seen.console.join("\n")).not.toContain(secret);
    }
    expect(seen.csp).toEqual([]);
    expect(seen.fatal).toEqual([]);
  });

  test("inscriptions fermées : écran dédié", async ({ page }) => {
    const seen = watch(page);
    await page.route("**/api/**", apiStub(newStub({ registration: "closed" })));
    await page.goto("/#/inscription");
    await page.fill("input[name=email]", "ada@example.test");
    await submitAccountForm(page);
    await expect(screen(page, "failure-registration_unavailable")).toContainText("Inscriptions fermées");
    expect(seen.fatal).toEqual([]);
  });

  test("lien sans secret puis lien expiré : écran dédié et nouveau lien", async ({ page }) => {
    const seen = watch(page);
    const stub = newStub({ verifyStatus: 400 });
    await page.route("**/api/**", apiStub(stub));

    await page.goto("/verify-email");
    await expect(screen(page, "failure-invalid_or_expired_token")).toContainText("Lien invalide ou expiré");
    await submitAccountForm(page);
    await expect(screen(page, "resend")).toBeVisible();

    await page.goto(`/verify-email#token=${SECRET}`);
    await page.fill("input[name=display_name]", "Ada");
    await page.fill("input[name=password]", PASSWORD);
    await page.fill("input[name=confirmation]", PASSWORD);
    await submitAccountForm(page);
    await expect(screen(page, "failure-invalid_or_expired_token")).toBeVisible();
    await expect(page.locator("body")).not.toContainText(SECRET);
    expect(seen.fatal).toEqual([]);
  });

  test("lien de réinitialisation expiré : retour au mot de passe oublié", async ({ page }) => {
    await page.route("**/api/**", apiStub(newStub({ verifyStatus: 400 })));
    await page.goto(`/reset-password#token=${SECRET}`);
    await page.route("**/api/v1/auth/reset-password", (route) =>
      route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify(coded("invalid_or_expired_token")) }),
    );
    expect(page.url()).not.toContain(SECRET);
    await page.fill("input[name=password]", PASSWORD);
    await page.fill("input[name=confirmation]", PASSWORD);
    await submitAccountForm(page);
    await expect(screen(page, "failure-invalid_or_expired_token")).toBeVisible();
    await submitAccountForm(page);
    await expect(screen(page, "forgot")).toBeVisible();
  });

  test("trop de tentatives et serveur injoignable : message fixe, saisie conservée", async ({ page }) => {
    const stub = newStub({ forgotStatus: 429 });
    await page.route("**/api/**", apiStub(stub));
    await page.goto("/#/mot-de-passe-oublie");
    await page.fill("input[name=email]", "ada@example.test");
    await submitAccountForm(page);
    await expect(page.locator("[data-testid=account-error]")).toHaveText(
      "Trop de tentatives depuis cette connexion. Patientez une minute puis réessayez.",
    );
    await expect(page.locator("input[name=email]")).toHaveValue("ada@example.test");

    await page.route("**/api/v1/auth/forgot-password", (route) => route.abort("connectionrefused"));
    await submitAccountForm(page);
    await expect(page.locator("[data-testid=account-error]")).toContainText("Serveur injoignable");
    await expect(page.locator("input[name=email]")).toHaveValue("ada@example.test");
  });

  test("connexion refusée : message fixe qui rappelle la vérification", async ({ page }) => {
    await page.route("**/api/**", apiStub(newStub({ loginStatus: 401 })));
    await page.goto("/");
    await page.fill("#login-email", "ada@example.test");
    await page.fill("#login-password", PASSWORD);
    await page.locator("#login-form button[type=submit]").click();
    await expect(page.locator("#login-error")).toContainText("ouvrez d'abord le lien de vérification");
    await expect(page.locator("#login-error")).not.toContainText("invalid email");
  });
});
