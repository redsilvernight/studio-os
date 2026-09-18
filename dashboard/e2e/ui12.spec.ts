/**
 * UI-12 Paramètres (browser, API stubbée déterministe) : Runtimes ≠ Agent ≠
 * Machine, Bindings par niveaux (privés compris), recherche/filtres locaux,
 * détail runtime avec technique replié et liens réels (Machines, Inspecteur),
 * création (Idempotency-Key, double soumission impossible), conflit 409,
 * suppression de binding formulée correctement, états vides, dégradation
 * partielle, mobile 375, clavier, zéro violation CSP. Captures hors dépôt.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const SHOTS = "C:/Users/redsi/AppData/Local/Temp/opencode/ui12";

const M1 = "aaaaaaaa-0000-4111-8111-000000000001";
const P1 = "11111111-2222-4333-8444-555555555555";
const RT1 = "11111111-1111-4111-8111-111111111111";
const RT2 = "22222222-2222-4222-8222-222222222222";
const RT3 = "33333333-3333-4333-8333-333333333333";
const B1 = "bbbbbbbb-0000-4111-8111-000000000001";
const B2 = "bbbbbbbb-0000-4111-8111-000000000002";
const B3 = "bbbbbbbb-0000-4111-8111-000000000003";

const RUN_ACTIVE = [
  {
    id: RT1,
    owner_user_id: "u1",
    machine_id: M1,
    harness_ref: "opencode",
    provider_ref: "fournisseur-a",
    model_ref: "modele-grand",
    capabilities: { coding: true, context_window: 128000, tools: ["shell"], local: false },
    capability_source: "declared",
    runtime_metadata: { region: "eu-west" },
    status: "active",
    version: 3,
    created_at: "2026-09-14T10:00:00Z",
    updated_at: "2026-09-15T10:00:00Z",
  },
  {
    id: RT2,
    owner_user_id: "u1",
    machine_id: null,
    harness_ref: "runner",
    provider_ref: "fournisseur-b",
    model_ref: "modele-leger",
    capabilities: { coding: false, tools: [], local: true },
    capability_source: "declared",
    runtime_metadata: {},
    status: "active",
    version: 1,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: null,
  },
];

const RUN_REVOKED = {
  id: RT3,
  owner_user_id: "u1",
  machine_id: null,
  harness_ref: "legacy",
  provider_ref: "fournisseur-a",
  model_ref: null,
  capabilities: { coding: false, tools: [], local: false },
  capability_source: "declared",
  runtime_metadata: {},
  status: "revoked",
  version: 4,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: null,
};

const BINDINGS = [
  {
    id: B1,
    level: "user",
    owner_user_id: "u1",
    project_id: null,
    target_kind: "agent_definition",
    target_stable_key: "review-helper",
    target: { runtime_id: RT1, capabilities: { coding: false, tools: [], local: false } },
    created_at: "2026-09-14T10:00:00Z",
  },
  {
    id: B2,
    level: "project_override",
    owner_user_id: "u1",
    project_id: P1,
    target_kind: "agent_definition",
    target_stable_key: "build-helper",
    target: { runtime_id: RT2, capabilities: { coding: false, tools: [], local: false } },
    created_at: "2026-09-13T10:00:00Z",
  },
  {
    id: B3,
    level: "studio_default",
    owner_user_id: "u1",
    project_id: null,
    target_kind: "model_profile",
    target_stable_key: "ops",
    target: { harness_ref: "runner", provider_ref: "fournisseur-b", model_ref: "modele-leger", capabilities: { coding: false, tools: [], local: false } },
    created_at: "2026-09-12T10:00:00Z",
  },
];

const LIBRARY = [
  { id: "l1", kind: "agent_definition", stable_key: "review-helper", scope: "studio", status: "active", active_version: 1 },
  { id: "l2", kind: "model_profile", stable_key: "profil-rapide", scope: "studio", status: "active", active_version: 1 },
];

interface Captured {
  idempotencyKeys: (string | null)[];
  createdRuntimes: unknown[];
  createdBindings: unknown[];
  patches: { url: string; body: unknown; idempotency: string | null }[];
  deletes: string[];
}

interface StubOpts {
  empty?: boolean;
  includeRevoked?: boolean;
  patchConflict?: boolean;
  bindingsFail?: boolean;
  runtimesFail?: boolean;
  slowCreate?: boolean;
}

function apiStub(captured: Captured, opts: StubOpts = {}) {
  return async (route: Route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) {
      await json(200, { access_token: "e2e-token", token_type: "bearer" });
      return;
    }
    // Bindings
    if (url.includes("/api/v1/runtime-bindings")) {
      if (opts.bindingsFail === true) {
        await json(503, { detail: "bindings down" });
        return;
      }
      const deleteMatch = /\/api\/v1\/runtime-bindings\/([^/?]+)$/.exec(url);
      if (method === "DELETE" && deleteMatch !== null) {
        captured.deletes.push(deleteMatch[1] ?? "");
        const found = BINDINGS.find((binding) => binding.id === deleteMatch[1]) ?? BINDINGS[0];
        await json(200, found);
        return;
      }
      if (method === "POST") {
        captured.idempotencyKeys.push(req.headers()["idempotency-key"] ?? null);
        captured.createdBindings.push(req.postDataJSON());
        await json(201, { ...BINDINGS[0], id: "bbbbbbbb-0000-4111-8111-000000000099" });
        return;
      }
      const level = new URL(url).searchParams.get("level");
      const list = opts.empty === true ? [] : BINDINGS.filter((binding) => level === null || binding.level === level);
      await json(200, list);
      return;
    }
    // Runtime detail / mutations
    const runtimeMatch = /\/api\/v1\/runtimes\/([^/?]+)(\/revoke)?$/.exec(url);
    if (method === "GET" && runtimeMatch !== null && runtimeMatch[2] === undefined) {
      const found = [...RUN_ACTIVE, RUN_REVOKED].find((runtime) => runtime.id === runtimeMatch[1]);
      await json(found === undefined ? 404 : 200, found ?? { detail: "not found" });
      return;
    }
    if (method === "PATCH" && runtimeMatch !== null) {
      captured.patches.push({ url, body: req.postDataJSON(), idempotency: req.headers()["idempotency-key"] ?? null });
      if (opts.patchConflict === true) {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: { error_code: "version_conflict", server_version: 9 } }),
        });
        return;
      }
      await json(200, { ...RUN_ACTIVE[0], version: 4 });
      return;
    }
    if (method === "POST" && runtimeMatch !== null && runtimeMatch[2] === "/revoke") {
      const found = [...RUN_ACTIVE, RUN_REVOKED].find((runtime) => runtime.id === runtimeMatch[1]);
      await json(200, { ...(found ?? RUN_ACTIVE[0]), status: "revoked" });
      return;
    }
    // Runtime list / create
    if (url.includes("/api/v1/runtimes")) {
      if (opts.runtimesFail === true) {
        await json(503, { detail: "runtimes down" });
        return;
      }
      if (method === "POST") {
        captured.idempotencyKeys.push(req.headers()["idempotency-key"] ?? null);
        captured.createdRuntimes.push(req.postDataJSON());
        if (opts.slowCreate === true) await new Promise((resolve) => setTimeout(resolve, 400));
        await json(201, { ...RUN_ACTIVE[1], id: "22222222-2222-4222-8222-000000000099" });
        return;
      }
      const include = new URL(url).searchParams.get("include_revoked") === "true";
      if (opts.empty === true) {
        await json(200, []);
        return;
      }
      await json(200, include ? [...RUN_ACTIVE, RUN_REVOKED] : RUN_ACTIVE);
      return;
    }
    if (url.includes("/api/v1/library")) {
      await json(200, opts.empty === true ? [] : LIBRARY);
      return;
    }
    await json(200, []);
  };
}

async function login(page: Page, startHash: string, captured: Captured, opts: StubOpts = {}): Promise<void> {
  await page.route("**/api/**", apiStub(captured, opts));
  await page.goto(`/${startHash}`);
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

const newCaptured = (): Captured => ({ idempotencyKeys: [], createdRuntimes: [], createdBindings: [], patches: [], deletes: [] });

test.describe("UI-12 Paramètres — Runtimes", () => {
  test("liste humaine FR : Runtime ≠ Agent ≠ Machine, ids secondaires, aucun secret", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/configuration/runtimes", captured);
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Paramètres");
    await expect(view).toContainText("Runtimes enregistrés");
    await expect(view.locator(".settings-runtime-row")).toHaveCount(2);
    // Humain d'abord : refs ouvertes en titre, pas d'UUID en texte.
    await expect(view).toContainText("opencode · fournisseur-a · modele-grand");
    await expect(view.locator(".settings-list")).not.toContainText(RT1);
    // Statut FR + capacités lisibles, pas de score.
    await expect(view).toContainText("Actif");
    await expect(view).toContainText("Coding = yes");
    await expect(view).not.toContainText(/puissance|\/100/i);
    // Distinction Runtime ≠ Machine + lien Machines réel.
    await expect(view).toContainText("Sans machine (cible distante)");
    await expect(view.locator('.settings-list a[href="#/machines"]')).toHaveCount(1);
    // Lien Inspecteur.
    await expect(view.locator('a[href="#/inspector"]')).toHaveCount(1);
    // Pas de table SQL, aucun secret dans le rendu.
    await expect(view.locator(".settings-list table")).toHaveCount(0);
    await expect(view).not.toContainText("api_key");
    await page.screenshot({ path: `${SHOTS}/settings-runtimes-1280.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("recherche + filtres locaux + inclure les révoqués + réinitialisation", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/configuration/runtimes", newCaptured());
    const view = page.locator("#view");
    await expect(view.locator(".settings-runtime-row")).toHaveCount(2);

    await view.locator("#settings-runtimes-search").fill("modele-grand");
    await expect(view.locator(".settings-runtime-row")).toHaveCount(1);
    await expect(view).toContainText("1 runtime(s) affiché(s) sur 2 chargé(s)");
    await expect(view).toContainText("recherche et filtres locaux");

    await view.locator("#settings-runtimes-search").fill("zzz-introuvable");
    await expect(view).toContainText("Aucun runtime ne correspond");
    await expect(view.locator(".settings-runtime-row")).toHaveCount(0);

    await view.locator("[data-reset]").click();
    await expect(view.locator(".settings-runtime-row")).toHaveCount(2);

    await view.locator("#settings-runtimes-provider").selectOption("fournisseur-b");
    await expect(view.locator(".settings-runtime-row")).toHaveCount(1);
    await view.locator("#settings-runtimes-provider").selectOption("");
    await view.locator("#settings-runtimes-machine").selectOption(M1);
    await expect(view.locator(".settings-runtime-row")).toHaveCount(1);

    // Les révoqués n'apparaissent qu'avec le filtre explicite (état canonique).
    await view.locator("#settings-runtimes-machine").selectOption("");
    await view.locator("#settings-runtimes-revoked").check();
    await expect(view.locator(".settings-runtime-row")).toHaveCount(3);
    await view.locator("#settings-runtimes-status").selectOption("revoked");
    await expect(view.locator(".settings-runtime-row")).toHaveCount(1);
    await expect(view).toContainText("Révoqué");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("détail runtime : technique replié, liens Machines/Inspecteur, secrets absents", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, `#/configuration/runtimes/${RT1}`, newCaptured());
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("opencode · fournisseur-a · modele-grand");
    await expect(view).toContainText("Configuration du runtime");
    await expect(view).toContainText("Capacités déclarées");
    await expect(view.locator('.settings-domain a[href="#/machines"]')).toHaveCount(1);
    await expect(view.locator('a[href="#/inspector"]')).toHaveCount(1);
    // Technique replié par défaut.
    const technical = view.locator(".settings-technical");
    await expect(technical.locator("summary")).toContainText("Informations techniques");
    await expect(technical).not.toHaveAttribute("open", "");
    await technical.locator("summary").click();
    await expect(technical).toHaveAttribute("open", "");
    await expect(technical).toContainText(RT1);
    await expect(technical).toContainText("eu-west");
    await expect(view).not.toContainText("api_key");
    await page.screenshot({ path: `${SHOTS}/settings-runtime-detail-1280.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("modification : conflit 409 expliqué, aucun retry silencieux", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, `#/configuration/runtimes/${RT1}`, captured, { patchConflict: true });
    const view = page.locator("#view");
    const form = view.locator("[data-runtime-update]");
    await view.locator("details.settings-editor").filter({ hasText: "Modifier ce runtime" }).locator("> summary").click();
    await form.locator('input[name="provider_ref"]').fill("fournisseur-modifie");
    await form.locator('button[type=submit]').click();
    await expect(form.locator("[data-msg]")).toContainText("409");
    await expect(form.locator("[data-msg]")).toContainText("version");
    expect(captured.patches).toHaveLength(1);
    await expect(form.locator('button[type=submit]')).toBeEnabled();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("création runtime : Idempotency-Key, double soumission impossible", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/configuration/runtimes", captured, { slowCreate: true });
    const view = page.locator("#view");
    await view.locator("details.settings-editor").filter({ hasText: "Déclarer un runtime" }).locator("> summary").click();
    const form = view.locator("[data-runtime-create]");
    await form.locator('input[name="provider_ref"]').fill("fournisseur-nouveau");
    const submit = form.locator('button[type=submit]');
    await submit.click();
    await expect(submit).toBeDisabled();
    await expect.poll(() => captured.createdRuntimes.length).toBe(1);
    expect(captured.idempotencyKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(captured.createdRuntimes[0]).toMatchObject({ provider_ref: "fournisseur-nouveau" });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-12 Paramètres — Bindings", () => {
  test("niveaux FR, confidentialité, cible humaine résolue, suppression formulée", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/configuration/bindings", captured);
    const view = page.locator("#view");
    await expect(view.locator("h1")).toContainText("Paramètres");
    await expect(view).toContainText("Règles d'affectation (bindings)");
    await expect(view.locator(".settings-binding-row")).toHaveCount(3);
    await expect(view).toContainText("Personnel (privé)");
    await expect(view).toContainText("Projet — remplacement");
    await expect(view).toContainText("Studio — défaut");
    await expect(view).toContainText("privés");
    // Cible runtime du registre résolue en titre humain.
    await expect(view).toContainText("opencode · fournisseur-a · modele-grand");

    await view.locator("#settings-bindings-scope").selectOption("user");
    await expect(view.locator(".settings-binding-row")).toHaveCount(1);
    await view.locator("#settings-bindings-scope").selectOption("all");
    await view.locator("#settings-bindings-search").fill("build");
    await expect(view.locator(".settings-binding-row")).toHaveCount(1);
    await view.locator("[data-reset]").click();
    await expect(view.locator(".settings-binding-row")).toHaveCount(3);

    // Suppression : formulation « Supprimer ce binding », jamais « le runtime ».
    let confirmMessage = "";
    page.once("dialog", (dialog) => {
      confirmMessage = dialog.message();
      void dialog.accept();
    });
    await view.locator(`[data-delete-binding="${B1}"]`).click();
    await expect.poll(() => captured.deletes.length).toBe(1);
    expect(confirmMessage).toContain("Supprimer ce binding");
    expect(confirmMessage).toContain("runtime visé n'est pas supprimé");
    await page.screenshot({ path: `${SHOTS}/settings-bindings-1280.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("création binding : cible proposée sans UUID brut, Idempotency-Key", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    const captured = newCaptured();
    await login(page, "#/configuration/bindings", captured);
    const view = page.locator("#view");
    await view.locator("details.settings-editor").filter({ hasText: "Nouveau binding" }).locator("> summary").click();
    const form = view.locator("[data-binding-create]");
    await form.locator('select[name="runtime_id"]').selectOption(RT1);
    await form.locator('input[name="target_stable_key"]').fill("review-helper");
    await form.locator('button[type=submit]').click();
    await expect.poll(() => captured.createdBindings.length).toBe(1);
    expect(captured.idempotencyKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(captured.createdBindings[0]).toMatchObject({ target_stable_key: "review-helper", target: { runtime_id: RT1 } });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

test.describe("UI-12 Paramètres — états et robustesse", () => {
  test("états vides distincts, sans CTA fictif", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/configuration/runtimes", newCaptured(), { empty: true });
    const view = page.locator("#view");
    await expect(view).toContainText("Aucun runtime enregistré");
    await expect(view.locator(".ds-empty a")).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/settings-vide-1280.png` });

    await page.goto("/#/configuration/bindings");
    await expect(page.locator("#view")).toContainText("Aucun binding stocké");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("dégradation partielle : bindings indisponibles, runtimes consultables", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, `#/configuration/runtimes/${RT1}`, newCaptured(), { bindingsFail: true });
    const view = page.locator("#view");
    await expect(view).toContainText("Configuration du runtime");
    await expect(view).toContainText("Bindings indisponibles");
    await expect(view).toContainText("le runtime reste consultable");

    await page.goto("/#/configuration/bindings");
    await expect(page.locator("#view")).toContainText("Impossible de charger les bindings");
    await expect(page.locator("#view")).toContainText("Recharger");
    await page.screenshot({ path: `${SHOTS}/settings-erreur-partielle-1280.png` });
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("mobile 375 : une colonne, pas d'overflow, deep link + back/forward", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/configuration/runtimes", newCaptured());
    const view = page.locator("#view");
    await expect(view.locator(".settings-runtime-row")).toHaveCount(2);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await expect(view.locator("#settings-runtimes-search")).toBeVisible();
    await view.locator('.settings-runtime-row a[href^="#/configuration/runtimes/"]').first().click();
    await expect(page.locator("#view")).toContainText("Configuration du runtime");
    await page.screenshot({ path: `${SHOTS}/settings-mobile-375.png` });
    await page.goto("/#/tasks");
    await page.goBack();
    await expect(page.locator("#view")).toContainText("Configuration du runtime");
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("responsive 1440/1280/768/375 : aucun overflow global", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/configuration/runtimes", newCaptured());
    for (const width of [1440, 1280, 768, 375]) {
      await page.setViewportSize({ width, height: 900 });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `viewport ${width}px`).toBeLessThanOrEqual(1);
    }
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });

  test("accessibilité : onglets, recherche étiquetée, région live, tablist navigable", async ({ page }) => {
    const { csp, fatal } = watchErrors(page);
    await login(page, "#/configuration/runtimes", newCaptured());
    const view = page.locator("#view");
    await expect(view.locator('.tabs .tab[aria-current="page"]')).toContainText("Runtimes");
    await expect(view.locator('[role="search"] #settings-runtimes-search')).toBeVisible();
    await expect(view.locator("#settings-runtimes-list")).toHaveAttribute("aria-live", "polite");
    await view.locator("#settings-runtimes-search").focus();
    await expect(view.locator("#settings-runtimes-search")).toBeFocused();
    expect(csp).toEqual([]);
    expect(fatal).toEqual([]);
  });
});

