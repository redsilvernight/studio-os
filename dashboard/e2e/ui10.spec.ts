/**
 * UI-10 Transferts (navigateur, API stubbée déterministe) : liste FR sans
 * table SQL, fichier + état lisibles, stockage invisible (ni clé S3 ni URL
 * signée), recherche/filtres locaux, tiroir de détail DS (Échap, retour
 * focus), empty state, envoi réel (create → initiate MD5 → PUT direct →
 * complete), mobile 375 sans overflow, zéro violation CSP, zéro erreur page.
 * Captures hors dépôt.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const SHOTS = "C:/Users/redsi/AppData/Local/Temp/opencode/ui10";

const P1 = "99999999-3333-4333-8333-000000000009";
const T1 = "88888888-4444-4444-8444-000000000008";
const RECIPIENT = "cccccccc-5555-4555-8555-000000000003";
const FUTURE = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
const PAST = new Date(Date.now() - 60 * 60 * 1000).toISOString();

function transfer(id: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id,
    transfer_code: `TRF-${id.slice(0, 6).toUpperCase()}`,
    sender_user_id: "bbbbbbbb-2222-4222-8222-000000000002",
    recipient_user_id: null,
    project_id: null,
    task_id: null,
    build_id: null,
    category: "temporary",
    filename: `${id}.bin`,
    object_key: `studio/unscoped/2026/09/${id}/secret-object-key.bin`,
    content_type: "application/octet-stream",
    size_bytes: 1024,
    sha256: null,
    content_md5: null,
    status: "created",
    expires_at: FUTURE,
    created_at: new Date(Date.now() - 3600_000).toISOString(),
    uploaded_at: null,
    downloaded_at: null,
    deleted_at: null,
    ...overrides,
  };
}

const TRANSFERS: Record<string, unknown>[] = [
  transfer("ready-1111", {
    filename: "build-studio-os.zip",
    category: "build",
    status: "ready",
    size_bytes: 1536,
    project_id: P1,
    task_id: T1,
    uploaded_at: new Date(Date.now() - 3000_000).toISOString(),
    created_at: new Date(Date.now() - 1000_000).toISOString(),
  }),
  transfer("attente-2222", {
    filename: "notes.txt",
    category: "temporary",
    status: "created",
    recipient_user_id: RECIPIENT,
    created_at: new Date(Date.now() - 2000_000).toISOString(),
  }),
  transfer("supprime-3333", {
    filename: "vieux.log",
    status: "deleted",
    expires_at: PAST,
    deleted_at: PAST,
    created_at: new Date(Date.now() - 3000_000).toISOString(),
  }),
];

const PROJECTS = [{ id: P1, slug: "studio-os", name: "Studio OS", description: null, archived: false, created_at: PAST, updated_at: PAST, version: 1 }];
const TASKS = [{ id: T1, project_id: P1, readable_id: "T-1", title: "Refonte UI", description: null, status: "in_progress", created_at: PAST, updated_at: PAST, version: 1, claimed_by_machine_id: null, claimed_by_agent_id: null }];
const CONSUMPTION = { project_id: null, consumed_bytes: 5 * 1024 * 1024, quota_bytes: 10 * 1024 * 1024, remaining_bytes: 5 * 1024 * 1024 };

interface StubOptions {
  empty?: boolean;
  failTransfers?: boolean;
  upload?: boolean;
  captured?: { create?: unknown; initiateMd5?: boolean };
}

function apiStub(opts: StubOptions = {}) {
  return async (route: Route): Promise<void> => {
    const request = route.request();
    const url = request.url();
    const method = request.method();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) {
      await json(200, { access_token: "e2e-token", token_type: "bearer" });
      return;
    }
    if (url.includes("/api/v1/transfers/consumption")) {
      await json(200, CONSUMPTION);
      return;
    }
    if (url.includes("/api/v1/transfers/") && url.includes("/upload/initiate")) {
      const body = request.postDataJSON() as { content_md5?: string } | null;
      if (body?.content_md5 === undefined) {
        await json(422, { detail: { error_code: "missing_content_md5" } });
        return;
      }
      if (opts.captured !== undefined) opts.captured.initiateMd5 = true;
      await json(200, { transfer_id: "new-0000", multipart: false, upload_url: "http://storage.test/put" });
      return;
    }
    if (url.includes("/api/v1/transfers/") && url.includes("/upload/complete")) {
      await json(200, transfer("new-0000", { filename: "tiny.bin", status: "ready", size_bytes: 3, uploaded_at: new Date().toISOString() }));
      return;
    }
    if (url.includes("/api/v1/transfers/") && url.includes("/download-url")) {
      await json(200, { transfer_id: "ready-1111", download_url: "http://storage.test/get/signed", expires_at: FUTURE });
      return;
    }
    if (/\/api\/v1\/transfers\/?$/.test(url) && method === "POST") {
      const body = request.postDataJSON() as Record<string, unknown> | null;
      if (opts.captured !== undefined) opts.captured.create = body;
      await json(201, transfer("new-0000", { ...(body ?? {}), status: "created", uploaded_at: null }));
      return;
    }
    if (/\/api\/v1\/transfers\/?/.test(url) && method === "GET") {
      if (opts.failTransfers === true) {
        await json(500, { detail: "boom" });
        return;
      }
      await json(200, opts.empty === true ? [] : TRANSFERS);
      return;
    }
    if (url.includes("/api/v1/projects")) {
      await json(200, PROJECTS);
      return;
    }
    if (url.includes("/api/v1/tasks")) {
      await json(200, TASKS);
      return;
    }
    await json(200, []);
  };
}

async function login(page: Page, opts: StubOptions = {}): Promise<void> {
  await page.route("**/api/**", apiStub(opts));
  await page.route("http://storage.test/**", async (route) => {
    await route.fulfill({ status: 200, headers: { ETag: '"e2e-etag"' }, body: "" });
  });
  await page.goto("/#/transfers");
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

test.describe("UI-10 page Transferts", () => {
  test("liste en français, fichier/état lisibles, stockage invisible", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page);
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Transferts");
    await expect(view.locator(".transfer-row")).toHaveCount(3);
    await expect(view.locator(".transfers-list table")).toHaveCount(0);

    // Priorité : nom de fichier, état humain, taille, date.
    await expect(view).toContainText("build-studio-os.zip");
    await expect(view).toContainText("Disponible");
    await expect(view).toContainText("En attente d'envoi");
    await expect(view).toContainText("Supprimé");
    await expect(view).toContainText("1,5 Ko");

    // Contexte réel uniquement : projet + tâche vers les routes existantes.
    await expect(view.locator(`a[href="#/projects/${P1}"]`)).toHaveCount(1);
    await expect(view.locator(`a[href="#/tasks/${T1}"]`)).toHaveCount(1);

    // Le stockage reste technique : ni clé d'objet, ni URL signée en liste.
    await expect(view.locator(".transfers-list")).not.toContainText("secret-object-key");
    await expect(view).not.toContainText("X-Amz");
    await expect(view).not.toContainText("download_url");

    // Télécharger seulement pour un objet réellement disponible.
    await expect(view.locator('[data-transfer-download]')).toHaveCount(1);
    await page.screenshot({ path: `${SHOTS}/transfers-liste-1280.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("recherche locale, filtres état/catégorie, réinitialisation", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page);
    const view = page.locator("#view");
    await expect(view.locator(".transfer-row")).toHaveCount(3);

    await view.locator("#transfers-search").fill("notes");
    await expect(view.locator(".transfer-row")).toHaveCount(1);
    await expect(view).toContainText("1 transfert(s) affiché(s) sur 3 chargé(s)");
    await expect(view).toContainText("recherche et filtres locaux");

    await view.locator("#transfers-search").fill("");
    await view.locator("#transfers-status").selectOption("deleted");
    await expect(view.locator(".transfer-row")).toHaveCount(1);
    await expect(view).toContainText("vieux.log");

    await view.locator("[data-reset]").click();
    await expect(view.locator(".transfer-row")).toHaveCount(3);

    await view.locator("#transfers-category").selectOption("build");
    await expect(view.locator(".transfer-row")).toHaveCount(1);
    await expect(view).toContainText("build-studio-os.zip");
    await view.locator("[data-reset]").click();
    await expect(view.locator(".transfer-row")).toHaveCount(3);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("tiroir détail : hiérarchie, technique replié, Échap + retour focus", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page);
    const view = page.locator("#view");
    const details = view.locator('[data-transfer-details]').first();
    await details.click();
    const drawer = view.locator("#transfer-drawer");
    await expect(drawer).not.toHaveAttribute("hidden", "");
    await expect(drawer).toContainText("Catégorie");
    await expect(drawer).toContainText("Expéditeur");
    await expect(drawer).toContainText("Destinataire");
    await expect(drawer).toContainText("Informations techniques");
    await expect(drawer).toContainText("Référence de stockage");
    await expect(drawer).toContainText("Suppression, annulation, prolongation et renvoi ne sont pas proposés");
    await expect(drawer.locator('[data-transfer-download]')).toHaveCount(1);
    await page.screenshot({ path: `${SHOTS}/transfers-detail-1280.png` });

    await page.keyboard.press("Escape");
    await expect(drawer).toHaveAttribute("hidden", "");
    await expect(details).toBeFocused();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("état vide : explication + CTA d'envoi réel", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, { empty: true });
    const view = page.locator("#view");
    await expect(view).toContainText("Aucun transfert");
    await expect(view).toContainText("Les transferts permettent d'échanger des fichiers via Studi'OS.");
    await expect(view.locator("[data-transfer-upload-open]")).toBeVisible();
    await expect(view).not.toContainText("transfers-toolbar");
    await page.screenshot({ path: `${SHOTS}/transfers-vide-1280.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("envoi réel : create → initiate MD5 → PUT direct → complete", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured: { create?: unknown; initiateMd5?: boolean } = {};
    await login(page, { upload: true, captured });
    const view = page.locator("#view");

    await view.locator("#transfer-upload-open").click();
    const modal = view.locator("#transfer-upload");
    await expect(modal).not.toHaveAttribute("hidden", "");
    await modal.locator('input[type="file"]').setInputFiles({
      name: "tiny.bin",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("abc"),
    });
    await expect(modal.locator("[data-file-info]")).toContainText("tiny.bin");

    await modal.locator('button[type="submit"]').click();
    await expect(page.locator("#ds-toast-region")).toContainText("envoyé");
    // Le POST de création ne transporte jamais d'octets, seulement la taille.
    expect(captured.create).toMatchObject({ filename: "tiny.bin", size_bytes: 3 });
    // L'initiate a été rejoué avec l'empreinte MD5 après le 422 initial.
    expect(captured.initiateMd5).toBe(true);
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("téléchargement : aucune URL signée exposée dans l'interface", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page);
    const view = page.locator("#view");
    await view.locator('[data-transfer-download]').first().click();
    await expect(view).not.toContainText("storage.test");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("erreur de chargement : message explicite + recharger, pas d'écran vide", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, { failTransfers: true });
    const view = page.locator("#view");
    await expect(view.locator('[role="alert"]')).toContainText("Impossible de charger les transferts");
    await expect(view.locator("#transfers-reload")).toBeVisible();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("mobile 375 : une colonne, pas d'overflow, tiroir utilisable", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page);
    const view = page.locator("#view");
    await expect(view.locator(".transfer-row")).toHaveCount(3);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await view.locator('[data-transfer-details]').first().click();
    await expect(view.locator("#transfer-drawer")).not.toHaveAttribute("hidden", "");
    await page.screenshot({ path: `${SHOTS}/transfers-mobile-375.png` });
    await page.keyboard.press("Escape");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});
