/**
 * C2 — nouvel utilisateur Web contre une VRAIE API (pile jetable
 * `desktop/e2e/gate_stack.py`, inscriptions ouvertes, emails en fichiers) :
 * inscription par l'écran → lien lu dans le .eml → vérification → connexion
 * → « En attente d'accès » → l'admin attribue un projet → tableau de bord →
 * premier usage : la tâche du projet attribué est listée, rien de l'autre
 * projet n'apparaît. Ni mot de passe ni jeton hors mémoire.
 *
 * Ignoré sans `STUDIO_C2_LIVE` : lancer via `node scripts/c2-new-user-live.mjs`.
 */
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

interface Live {
  api: string;
  email: string;
  password: string;
  project: string;
  mailDir: string;
}

const RAW = process.env.STUDIO_C2_LIVE;
const LIVE: Live | null = RAW ? (JSON.parse(RAW) as Live) : null;
const CSP_RE = /content security policy|securitypolicyviolation/i;
const JWT_RE = /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/;
const TASK = "C2 · première tâche";
const HIDDEN_TASK = "C2 · hors périmètre";

async function api(path: string, init: { method?: string; token?: string; body?: unknown } = {}) {
  const headers: Record<string, string> = { "Content-Type": "application/json", "Idempotency-Key": randomUUID() };
  if (init.token) headers.Authorization = `Bearer ${init.token}`;
  const response = await fetch(`${LIVE!.api}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  const text = await response.text();
  return { status: response.status, json: text ? JSON.parse(text) : null };
}

async function login(email: string, password: string): Promise<string> {
  const answer = await api("/api/v1/auth/token", { method: "POST", body: { email, password } });
  expect(answer.status, `login ${email}`).toBe(200);
  return answer.json.access_token as string;
}

async function verificationSecret(email: string): Promise<string> {
  for (let i = 0; i < 40; i++) {
    const files = existsSync(LIVE!.mailDir) ? readdirSync(LIVE!.mailDir).filter((f) => f.endsWith(".eml")) : [];
    for (const file of files) {
      const raw = readFileSync(join(LIVE!.mailDir, file), "utf-8").replace(/=\r?\n/g, "");
      if (!raw.includes(email)) continue;
      const match = /verify-email#token=(?:3D)?([A-Za-z0-9_-]+)/.exec(raw);
      if (match?.[1]) return match[1];
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`no verification e-mail for ${email}`);
}

/** The page calls `/api` and `/healthz` on its own origin: forward them to the live API. */
async function proxyToLiveApi(page: Page): Promise<void> {
  await page.route(/\/(api\/|healthz)/, async (route) => {
    const url = new URL(route.request().url());
    // The SSE stream never completes: a buffered proxy would hang on it.
    if (url.pathname.startsWith("/api/v1/events/stream")) {
      return route.fulfill({ status: 204, body: "" });
    }
    const response = await route.fetch({ url: `${LIVE!.api}${url.pathname}${url.search}` });
    return route.fulfill({ response });
  });
}

const screen = (page: Page, name: string) => page.locator(`[data-testid=account-screen][data-screen="${name}"]`);
const submitAccountForm = (page: Page) => page.locator("[data-testid=account-screen] form button[type=submit]").click();

test.describe("C2 nouvel utilisateur Web (API réelle)", () => {
  test.skip(LIVE === null, "STUDIO_C2_LIVE absent : lancer node scripts/c2-new-user-live.mjs");
  test.setTimeout(120_000);

  test("inscription → vérification → attente d'accès → accès → premier usage", async ({ page }) => {
    const live = LIVE!;
    const email = `c2-${randomUUID().slice(0, 8)}@example.test`;
    const password = `c2-${randomUUID()}`;
    const seen = { csp: [] as string[], fatal: [] as Error[], console: [] as string[] };
    page.on("console", (msg) => {
      seen.console.push(msg.text());
      if (msg.type() === "error" && CSP_RE.test(msg.text())) seen.csp.push(msg.text());
    });
    page.on("pageerror", (error) => seen.fatal.push(error));
    await proxyToLiveApi(page);

    // Côté serveur : un projet attribuable avec une tâche, et un autre projet
    // qui ne sera jamais attribué.
    const admin = await login(live.email, live.password);
    const gate = ((await api("/api/v1/projects", { token: admin })).json as { id: string; slug: string; name: string }[]).find(
      (p) => p.slug === live.project,
    )!;
    expect(gate, "gate project").toBeTruthy();
    const other = await api("/api/v1/projects", {
      method: "POST",
      token: admin,
      body: { slug: `c2-other-${randomUUID().slice(0, 6)}`, name: "C2 autre projet" },
    });
    expect(other.status).toBe(201);
    for (const [projectId, title] of [
      [gate.id, TASK],
      [other.json.id, HIDDEN_TASK],
    ]) {
      expect((await api("/api/v1/tasks", { method: "POST", token: admin, body: { project_id: projectId, title } })).status).toBe(201);
    }

    // Inscription par l'écran.
    await page.goto("/");
    await page.locator("a[data-account-action=register]").click();
    await page.fill("input[name=email]", email);
    await submitAccountForm(page);
    await expect(screen(page, "sent")).toContainText(email);

    // Lien reçu par email (fichier .eml de la pile) : vérification.
    const secret = await verificationSecret(email);
    await page.goto(`/verify-email#token=${secret}`);
    await expect(screen(page, "verify")).toBeVisible();
    expect(page.url()).not.toContain(secret);
    await page.fill("input[name=display_name]", "Ada C2");
    await page.fill("input[name=password]", password);
    await page.fill("input[name=confirmation]", password);
    await submitAccountForm(page);
    await expect(screen(page, "verified")).toContainText("Votre compte est actif");

    // Connexion : compte actif readonly sans projet.
    await submitAccountForm(page);
    await page.fill("#login-email", email);
    await page.fill("#login-password", password);
    await page.locator("#login-form button[type=submit]").click();
    await expect(page.locator("[data-testid=awaiting-access]")).toBeVisible();
    const me = (await api("/api/v1/auth/me", { token: await login(email, password) })).json;
    expect(me.role).toBe("readonly");

    // L'admin attribue le projet ; « Vérifier à nouveau » ouvre le tableau de bord.
    expect((await api(`/api/v1/projects/${gate.id}/members/${me.user_id}`, { method: "PUT", token: admin })).status).toBe(201);
    await page.locator("[data-testid=awaiting-access-recheck]").click();
    await expect(page.locator("[data-testid=awaiting-access]")).toHaveCount(0);
    await expect(page.locator("#view")).toContainText(gate.name);
    await expect(page.locator("#view")).not.toContainText("C2 autre projet");

    // Premier usage : la tâche du projet attribué, rien de l'autre.
    await page.goto("/#/tasks");
    await expect(page.locator("#view .task-row", { hasText: TASK })).toHaveCount(1);
    await expect(page.locator("body")).not.toContainText(HIDDEN_TASK);

    const dump = await page.evaluate(() =>
      JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage }, cookie: document.cookie }),
    );
    for (const value of [secret, password]) {
      expect(dump).not.toContain(value);
      expect(page.url()).not.toContain(value);
      expect(seen.console.join("\n")).not.toContain(value);
    }
    expect(dump).not.toMatch(JWT_RE);
    expect(seen.console.join("\n")).not.toMatch(JWT_RE);
    expect(seen.csp).toEqual([]);
    expect(seen.fatal).toEqual([]);
  });
});
