/**
 * UI-15 — Responsive approfondi : une même information, une hiérarchie
 * cohérente, quelle que soit la largeur disponible.
 *
 * Le responsive adapte l'interface, il ne la compresse pas : aucun scroll
 * horizontal GLOBAL (seuls des scrolls LOCAUX explicites sont permis),
 * aucune action essentielle inaccessible, aucune colonne d'onglets masquée.
 *
 * API stubbée déterministe, avec variantes volontairement longues
 * (noms, titres, filenames, stable_keys, refs runtime) pour casser le
 * layout avant l'utilisateur. Zéro violation CSP, zéro pageerror.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const SHOTS = "C:/Users/redsi/AppData/Local/Temp/opencode/ui15";

const P1 = "11111111-2222-4333-8444-555555555555";
const T1 = "aaaaaaaa-0000-4111-8111-000000000001";
const M1 = "aaaaaaaa-0000-4111-8111-000000000001";
const LIB_ID = "11111111-1111-4111-8111-111111111111";
const LONG_KEY = "studio.sous-espace-de-configuration-partagee.sous-espace-de-configuration-partagee.cle-maitresse-de-resolution";

const LOREM =
  "Hébergement et maintenance de la plateforme de compilation incrémentale pour les mondes ouverts persistants ";
const LONG_TITLE = `Tâche ${"très longue qui s'étire indéfiniment pour éprouver le retour à la ligne ".repeat(6)}— fin`;
const LONG_FILE = `${"nom-de-fichier-de-transfert-excessivement-long-pour-casser-le-layout_".repeat(3)}build-final.zip`;

interface StubData {
  projects: unknown[];
  tasks: unknown[];
  reviewItems: unknown[];
}

function stubData(long: boolean): StubData {
  const projects = [
    {
      id: P1,
      slug: "phare",
      name: long ? `Jeu Phare — ${LOREM.repeat(3)}` : "Jeu Phare",
      description: long ? LOREM.repeat(8) : "Le jeu principal du studio",
      archived: false,
      created_at: "2026-09-01T10:00:00Z",
      updated_at: "2026-09-10T10:00:00Z",
      version: 7,
    },
  ];
  const tasks = [
    {
      id: T1,
      project_id: P1,
      readable_id: "T-001",
      title: long ? LONG_TITLE : "Caméra Android bloquée",
      description: long ? LOREM.repeat(10) : "La caméra reste figée au lancement sur Android.",
      status: "blocked",
      claimed_by_machine_id: null,
      claimed_by_agent_id: null,
      created_at: "2026-09-10T10:00:00Z",
      updated_at: "2026-09-11T10:00:00Z",
      version: 2,
    },
    {
      id: "bbbbbbbb-0000-4111-8111-000000000002",
      project_id: P1,
      readable_id: "T-002",
      title: long ? `${LONG_TITLE} (copie)` : "Refonte de l'écran titre",
      description: null,
      status: "in_progress",
      claimed_by_machine_id: M1,
      claimed_by_agent_id: "ag-claude",
      created_at: "2026-09-10T10:00:00Z",
      updated_at: "2026-09-11T10:00:00Z",
      version: 1,
    },
    {
      id: "cccccccc-0000-4111-8111-000000000003",
      project_id: P1,
      readable_id: "T-003",
      title: "Corriger le doublon de tâche",
      description: "Petite tâche",
      status: "created",
      claimed_by_machine_id: null,
      claimed_by_agent_id: null,
      created_at: "2026-09-10T10:00:00Z",
      updated_at: "2026-09-11T10:00:00Z",
      version: 1,
    },
    {
      id: "dddddddd-0000-4111-8111-000000000004",
      project_id: P1,
      readable_id: "T-004",
      title: "Publier la démo",
      description: null,
      status: "done",
      claimed_by_machine_id: null,
      claimed_by_agent_id: null,
      created_at: "2026-09-10T10:00:00Z",
      updated_at: "2026-09-11T10:00:00Z",
      version: 3,
    },
  ];
  const reviewItems = [
    {
      kind: "ai_work_review",
      id: "rw1",
      project_id: P1,
      task_id: T1,
      title: long ? LONG_TITLE : "Relire la sortie agent",
      agent_id: "ag-claude",
      requested_at: "2026-09-10T10:00:00Z",
    },
    {
      kind: "decision_proposal",
      id: "rw2",
      project_id: P1,
      task_id: null,
      readable_id: "DEC-0049",
      title: long ? LONG_TITLE : "Choisir le moteur de rendu",
      proposed_by_type: "agent",
      requested_at: "2026-09-10T10:00:00Z",
    },
  ];
  return { projects, tasks, reviewItems };
}

function apiStub15(long: boolean) {
  const data = stubData(long);
  const agents = [
    {
      id: "ag-claude",
      machine_id: M1,
      display_name: "Claude",
      agent_kind: "dev",
      agent_profile: null,
      harness: long ? "opencode-harness-a-reference-tres-longue-pour-eprouver-le-layout" : "opencode",
      provider: long ? "anthropic-proxy-regional-europe-ouest-beaucoup-trop-long" : "anthropic",
      model: long ? "claude-sonnet-5-edition-aux-metadonnees-interminables" : "claude-sonnet-5",
      created_at: "2026-09-14T10:00:00Z",
      updated_at: "2026-09-14T10:00:00Z",
      version: 1,
    },
  ];
  const transfers = [
    {
      id: "aaaaaaaa-1111-4111-8111-000000000001",
      transfer_code: "TRF-ABCD1234",
      sender_user_id: "bbbbbbbb-2222-4222-8222-000000000002",
      recipient_user_id: "cccccccc-5555-4555-8555-000000000003",
      project_id: P1,
      task_id: T1,
      build_id: null,
      category: "build",
      filename: long ? LONG_FILE : "build-studio-os.zip",
      object_key: "studio/studio-os/2026/09/aaaa/build-studio-os.zip",
      content_type: "application/zip",
      size_bytes: 1536,
      sha256: "deadbeef",
      content_md5: "YWJjZA==",
      status: "ready",
      expires_at: new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString(),
      created_at: new Date(Date.now() - 3600 * 1000).toISOString(),
      uploaded_at: new Date(Date.now() - 3000 * 1000).toISOString(),
      downloaded_at: null,
      deleted_at: null,
    },
  ];
  const library = [
    {
      id: LIB_ID,
      kind: "rule",
      stable_key: long ? LONG_KEY : "coding-standard",
      scope: "studio",
      status: "active",
      active_version: 2,
      owner_user_id: null,
      project_id: null,
      created_by_user_id: null,
      version: 3,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
    },
    {
      id: "33333333-3333-4333-8333-333333333333",
      kind: "skill",
      stable_key: "review-helper",
      scope: "project",
      status: "draft",
      active_version: 0,
      owner_user_id: null,
      project_id: P1,
      created_by_user_id: null,
      version: 1,
      created_at: "2026-02-01T00:00:00Z",
      updated_at: "2026-02-02T00:00:00Z",
    },
  ];
  const versions = [
    {
      id: "22222222-2222-4222-8222-222222222222",
      resource_id: LIB_ID,
      version: 2,
      title: long ? LONG_TITLE : "Coding standard v2",
      description: long ? LOREM.repeat(6) : "Standard de code",
      content: { text: long ? LOREM.repeat(20) : "Contenu de la règle." },
      dependencies: [],
      created_by_user_id: null,
      created_at: "2026-01-02T00:00:00Z",
    },
  ];
  const decisions = [
    {
      id: "dec-1",
      readable_id: "DEC-0049",
      project_id: P1,
      task_id: T1,
      title: long ? LONG_TITLE : "Choisir le moteur de rendu",
      body: long ? LOREM.repeat(8) : "Nous choisissons Godot.",
      status: "accepted",
      proposed_by_type: "agent",
      proposed_by_id: "ag-claude",
      created_at: "2026-09-10T10:00:00Z",
    },
  ];
  const runtimes = [
    {
      id: "rt1",
      owner_user_id: "u1",
      machine_id: M1,
      harness_ref: long ? "opencode-harness-a-reference-tres-longue-pour-casser-le-layout" : "opencode",
      provider_ref: long ? "anthropic-proxy-regional-avec-un-nom-beaucoup-trop-long" : "anthropic",
      model_ref: long ? "claude-sonnet-5-edition-speciale-aux-metadonnees-interminables" : null,
      capabilities: { coding: true, tools: [], local: true },
      capability_source: "declared",
      runtime_metadata: {},
      status: "active",
      version: 1,
      created_at: "2026-09-14T10:00:00Z",
      updated_at: null,
    },
  ];
  const bindings = [
    {
      id: "bd1",
      level: "project",
      owner_user_id: "u1",
      project_id: P1,
      target_kind: "rule",
      target_stable_key: long ? LONG_KEY : "coding-standard",
      target: "rt1",
      created_at: "2026-09-14T10:00:00Z",
    },
  ];
  const claims = [
    {
      id: "cl1",
      project_id: P1,
      resource_path: long
        ? `godot/${"scenes/niveaux/monde-ouvert/zone-nord/".repeat(4)}niveau-final.tscn`
        : "godot/scenes/niveau.tscn",
      resource_type: "file",
      claimed_by_machine_id: M1,
      task_id: T1,
      status: "active",
      ttl_seconds: 3600,
      created_at: new Date(Date.now() - 1000).toISOString(),
      renewed_at: null,
      expires_at: new Date(Date.now() + 3600 * 1000).toISOString(),
      released_at: null,
    },
  ];
  const sessions = [
    {
      id: "sess-active",
      task_id: T1,
      machine_id: M1,
      agent_id: "ag-claude",
      started_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
      ended_at: null,
    },
  ];
  const envelope = (id: string) => ({
    event_id: id,
    event_type: "session.started",
    project_id: P1,
    task_id: T1,
    machine_id: M1,
    actor_type: "agent",
    actor_id: "ag-claude",
    client_timestamp: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
    server_timestamp: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
    payload: {},
    schema_version: 1,
  });
  const resolution = {
    agent: {
      resource_id: "a1",
      kind: "agent_definition",
      stable_key: long ? LONG_KEY : "review-helper",
      scope: "studio",
      version: 4,
      version_origin: "lock",
      deprecated: false,
      title: long ? LONG_TITLE : "Review helper",
      content: {},
      provenance: { source: "project_lock", version: 4, scope: "studio", version_origin: "lock", locked: true },
    },
    rules: [],
    skills: [],
    model_profile: {
      resource_id: "m1",
      stable_key: "review-profile",
      scope: "studio",
      version: 2,
      version_origin: "pin",
      deprecated: false,
      title: "",
      requirements: { coding: true },
      provenance: { source: "version_pin", version: 5, relation: "uses_skill", via: "agent_definition:review-helper" },
    },
    requirements: { coding: true },
    composed_agents: [],
    workflows: [],
    runtime: {
      target: {
        runtime_id: "rt1",
        harness_ref: long ? "opencode-harness-a-reference-tres-longue-pour-casser-le-layout" : "opencode",
        provider_ref: long ? "anthropic-proxy-regional-avec-un-nom-beaucoup-trop-long" : "anthropic",
        model_ref: long ? "claude-sonnet-5-edition-speciale-aux-metadonnees-interminables" : "model_a",
        capabilities: { coding: true, tools: [], local: false },
      },
      level: "project_override",
      matched_kind: "agent_definition",
      matched_stable_key: long ? LONG_KEY : "review-helper",
      compatible: true,
      unsatisfied: [],
      provenance: { source: "runtime_binding", binding_level: "project_override", via: "agent_definition:review-helper" },
    },
  };
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
    if (method === "POST" && url.endsWith("/api/v1/resolutions")) {
      await json(200, resolution);
      return;
    }
    if (method === "POST" && url.endsWith("/api/v1/tasks")) {
      await json(201, { ...(data.tasks[0] as object), id: "aaaaaaaa-0000-4111-8111-000000000009" });
      return;
    }
    if (method === "GET" && /\/api\/v1\/machines\/?$/.test(url)) {
      await json(404, { detail: "not found" });
      return;
    }
    if (/\/api\/v1\/projects\/[^/]+\/state$/.test(url)) {
      await json(200, { project_id: P1, active_tasks: [], active_claims: [], generated_at: "2026-09-12T10:00:00Z" });
      return;
    }
    if (/\/api\/v1\/projects\/[^/]+$/.test(url)) {
      await json(200, data.projects[0]);
      return;
    }
    if (url.endsWith("/api/v1/projects")) {
      await json(200, data.projects);
      return;
    }
    if (/\/api\/v1\/tasks\/[^/]+$/.test(url)) {
      await json(200, data.tasks[0]);
      return;
    }
    if (url.includes("/api/v1/tasks")) {
      await json(200, data.tasks);
      return;
    }
    if (url.includes("/api/v1/transfers/consumption")) {
      await json(200, { consumed_bytes: 512, quota_bytes: 104857600, remaining_bytes: 104857088, project_id: null });
      return;
    }
    if (/\/api\/v1\/transfers\/[^/]+$/.test(url)) {
      await json(200, transfers[0]);
      return;
    }
    if (url.includes("/api/v1/transfers")) {
      await json(200, transfers);
      return;
    }
    if (/\/api\/v1\/library\/[^/]+\/versions/.test(url)) {
      await json(200, versions);
      return;
    }
    if (/\/api\/v1\/library\/[^/]+$/.test(url)) {
      await json(200, library[0]);
      return;
    }
    if (url.includes("/api/v1/library-locks")) {
      await json(200, []);
      return;
    }
    if (url.includes("/api/v1/library")) {
      await json(200, library);
      return;
    }
    if (url.includes("/api/v1/decisions")) {
      await json(200, decisions);
      return;
    }
    if (url.includes("/api/v1/review-queue")) {
      await json(200, { items: data.reviewItems, generated_at: "2026-09-10T10:00:00Z" });
      return;
    }
    if (/\/api\/v1\/runtimes\/[^/]+$/.test(url)) {
      await json(200, runtimes[0]);
      return;
    }
    if (url.includes("/api/v1/runtimes")) {
      await json(200, runtimes);
      return;
    }
    if (url.includes("/api/v1/runtime-bindings")) {
      await json(200, bindings);
      return;
    }
    if (url.includes("/api/v1/timeline")) {
      await json(200, { project_id: P1, days: [{ date: "2026-09-11", events: [envelope("e1")] }] });
      return;
    }
    if (url.includes("/api/v1/claims")) {
      await json(200, claims);
      return;
    }
    if (url.includes("/api/v1/agents")) {
      await json(200, agents);
      return;
    }
    if (url.includes("/api/v1/sessions")) {
      await json(200, sessions);
      return;
    }
    if (url.includes("/api/v1/events")) {
      await json(200, [envelope("e1")]);
      return;
    }
    await json(200, []);
  };
}

interface ErrorWatch {
  csp: string[];
  fatal: Error[];
  errors: string[];
}

function watchErrors(page: Page): ErrorWatch {
  const watch: ErrorWatch = { csp: [], fatal: [], errors: [] };
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      watch.errors.push(msg.text());
      if (CSP_RE.test(msg.text())) watch.csp.push(msg.text());
    }
  });
  page.on("pageerror", (error) => watch.fatal.push(error));
  return watch;
}

function expectClean(watch: ErrorWatch): void {
  expect(watch.csp, `violations CSP: ${watch.csp.join(" | ")}`).toEqual([]);
  expect(watch.fatal, `pageerrors: ${watch.fatal.map(String).join(" | ")}`).toEqual([]);
  // Bruit connu et attendu : le stub renvoie 404 sur GET /machines (comme
  // UI-14) pour exercer le chemin dégradé ; le navigateur journalise le
  // chargement en échec alors que la vue l'absorbe en notice. Tout autre
  // message console reste un échec.
  const unexpected = watch.errors.filter(
    (message) => message !== "Failed to load resource: the server responded with a status of 404 (Not Found)",
  );
  expect(unexpected, `erreurs console: ${unexpected.join(" | ")}`).toEqual([]);
}

async function login(page: Page, startHash: string, long: boolean): Promise<void> {
  await page.route("**/api/**", apiStub15(long));
  // Santé système : réponse déterministe, jamais le backend ambient ni le
  // réseau (un backend local sans jeton répond 401 sur /healthz).
  await page.route("**/healthz", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.goto(`/${startHash}`);
  await expect(page.locator("#login-form")).toBeVisible({ timeout: 15_000 });
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible({ timeout: 15_000 });
}

async function go(page: Page, hash: string): Promise<void> {
  await page.evaluate((target) => {
    window.location.hash = target;
  }, hash);
  await page.waitForTimeout(800);
}

/** Bouton d'envoi (header toujours présent ; doublon dans l'état vide). */
function uploadOpen(page: Page) {
  return page.locator("#transfer-upload-open, #view [data-transfer-upload-open]");
}

/** Clic réel après remontée au centre (barre sticky sinon interceptrice). */
async function centerClick(target: import("@playwright/test").Locator): Promise<void> {
  await target.scrollIntoViewIfNeeded();
  await target.evaluate((el) => el.scrollIntoView({ block: "center" }));
  await target.click();
}
/** Dépassement horizontal GLOBAL (0 toléré au-delà d'1 px technique). */
async function globalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth));
}

async function expectNoGlobalOverflow(page: Page, label: string): Promise<void> {
  const overflow = await globalOverflow(page);
  expect(overflow, `${label} : overflow horizontal global de ${overflow}px`).toBeLessThanOrEqual(1);
}

test.describe("UI-15 matrice sans overflow global (données longues)", () => {
  test("desktop 1440/1280", async ({ page }) => {
    test.setTimeout(300_000);
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await login(page, "#/", true);
    const routes: Array<[string, string]> = [
      ["#/", "Accueil"],
      ["#/projects", "Projets"],
      ["#/tasks", "Tâches"],
      ["#/library", "Bibliothèque"],
      ["#/transfers", "Transferts"],
      ["#/machines", "Machines"],
      ["#/decisions", "Décisions"],
      ["#/inspector", "Inspecteur"],
      ["#/configuration/runtimes", "Paramètres"],
      ["#/design-system", "Design System"],
    ];
    for (const [hash] of routes) {
      await go(page, hash);
      await expect(page.locator("#view h1").first()).toBeVisible({ timeout: 10_000 });
      await expectNoGlobalOverflow(page, `${hash} @1440`);
    }
    await page.screenshot({ path: `${SHOTS}/avant-accueil-1440.png` });
    await page.setViewportSize({ width: 1280, height: 800 });
    await go(page, "#/projects");
    await page.screenshot({ path: `${SHOTS}/avant-projects-1280.png` });
    for (const [hash] of routes) {
      await go(page, hash);
      await expectNoGlobalOverflow(page, `${hash} @1280`);
    }
    expectClean(watch);
  });

  test("moyen 1024/900 : workspace et listes", async ({ page }) => {
    test.setTimeout(300_000);
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1024, height: 800 });
    await login(page, "#/", true);
    const routes = [
      `#/projects/${P1}`,
      `#/projects/${P1}/tasks`,
      `#/projects/${P1}/claims`,
      `#/projects/${P1}/activity`,
      `#/projects/${P1}/decisions`,
      "#/tasks",
      "#/library",
    ];
    for (const hash of routes) {
      await go(page, hash);
      await expect(page.locator("#view h1").first()).toBeVisible({ timeout: 10_000 });
      await expectNoGlobalOverflow(page, `${hash} @1024`);
    }
    await go(page, `#/projects/${P1}`);
    await page.screenshot({ path: `${SHOTS}/avant-workspace-1024.png` });
    await page.setViewportSize({ width: 900, height: 800 });
    await go(page, "#/tasks");
    await expectNoGlobalOverflow(page, "#/tasks @900");
    await page.screenshot({ path: `${SHOTS}/avant-tasks-900.png` });
    expectClean(watch);
  });

  test("étroit 768/640 : détails et technique", async ({ page }) => {
    test.setTimeout(300_000);
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 768, height: 800 });
    await login(page, "#/", true);
    const routes = [
      `#/tasks/${T1}`,
      "#/agents",
      "#/agents/ag-claude",
      `#/library/rules/${LIB_ID}`,
      "#/configuration/runtimes/rt1",
      "#/configuration/bindings",
      "#/configuration/project",
      "#/configuration/project/locks",
      `#/inspector/${encodeURIComponent(LONG_KEY)}`,
    ];
    for (const hash of routes) {
      await go(page, hash);
      await expect(page.locator("#view h1").first()).toBeVisible({ timeout: 10_000 });
      await expectNoGlobalOverflow(page, `${hash} @768`);
    }
    await go(page, `#/tasks/${T1}`);
    await page.screenshot({ path: `${SHOTS}/avant-taskdetail-768.png` });
    await go(page, "#/agents");
    await page.screenshot({ path: `${SHOTS}/avant-agents-640.png` });
    await page.setViewportSize({ width: 640, height: 800 });
    for (const hash of routes) {
      await go(page, hash);
      await expectNoGlobalOverflow(page, `${hash} @640`);
    }
    expectClean(watch);
  });

  test("mobile 480/375 : toutes les surfaces", async ({ page }) => {
    test.setTimeout(600_000);
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/", true);
    const routes = [
      "#/",
      "#/projects",
      `#/projects/${P1}`,
      `#/projects/${P1}/tasks`,
      `#/projects/${P1}/claims`,
      `#/projects/${P1}/activity`,
      `#/projects/${P1}/decisions`,
      "#/tasks",
      `#/tasks/${T1}`,
      "#/agents",
      "#/machines",
      "#/transfers",
      "#/decisions",
      "#/library",
      "#/library/rules",
      `#/library/rules/${LIB_ID}`,
      "#/configuration/runtimes",
      "#/configuration/bindings",
      "#/configuration/project",
      "#/inspector",
      "#/route-inexistante-xyz",
    ];
    for (const hash of routes) {
      await go(page, hash);
      await expect(page.locator("#view h1").first()).toBeVisible({ timeout: 10_000 });
      await expectNoGlobalOverflow(page, `${hash} @375`);
    }
    for (const [hash, shot] of [
      ["#/library", "avant-library-375.png"],
      ["#/decisions", "avant-decisions-375.png"],
      ["#/machines", "avant-machines-375.png"],
      ["#/transfers", "avant-transfers-375.png"],
      ["#/inspector", "avant-inspector-375.png"],
      ["#/configuration/runtimes", "avant-settings-375.png"],
    ] as Array<[string, string]>) {
      await go(page, hash);
      await page.screenshot({ path: `${SHOTS}/${shot}` });
    }
    await page.setViewportSize({ width: 480, height: 800 });
    for (const hash of routes) {
      await go(page, hash);
      await expectNoGlobalOverflow(page, `${hash} @480`);
    }
    expectClean(watch);
  });
});

test.describe("UI-15 onglets Bibliothèque à 375 (dette UI-7)", () => {
  test("wrap, deep links, clavier, aria-current", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/library", false);
    const nav = page.locator('nav.tabs[aria-label="Catégories de la bibliothèque"]');
    await expect(nav).toBeVisible();
    const tabs = nav.locator("a.tab");
    await expect(tabs).toHaveCount(5);
    // Les 5 onglets restent des liens profonds stables, pas un faux select.
    for (const slug of ["rules", "skills", "agent-definitions", "workflows", "model-profiles"]) {
      await expect(nav.locator(`a.tab[href="#/library/${slug}"]`)).toHaveCount(1);
    }
    // Adaptation étroite : plusieurs lignes OU scroll local, jamais d'overflow global.
    const layout = await page.evaluate(() => {
      const el = document.querySelector("nav.tabs");
      if (!(el instanceof HTMLElement)) return { wrapped: false, scrollable: false };
      const items = [...el.querySelectorAll("a.tab")];
      const tops = new Set(items.map((item) => (item as HTMLElement).offsetTop));
      const style = getComputedStyle(el);
      return { wrapped: tops.size > 1, scrollable: style.overflowX === "auto" || style.overflowX === "scroll" };
    });
    expect(layout.wrapped || layout.scrollable, "onglets adaptés à 375 (wrap ou scroll local)").toBe(true);
    await expectNoGlobalOverflow(page, "library tabs @375");
    // Clavier : les onglets sont atteignables et activent le deep link.
    await tabs.nth(1).focus();
    await expect(tabs.nth(1)).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#view h1").first()).toBeVisible({ timeout: 10_000 });
    expect(page.url()).toContain("#/library/");
    // aria-current sur l'onglet actif.
    await expect(nav.locator('a.tab[aria-current="page"]')).toHaveCount(1);
    expectClean(watch);
  });
});

test.describe("UI-15 shell et navigation mobile", () => {
  test("sidebar permanente ≥900, drawer <900", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1280, height: 800 });
    await login(page, "#/tasks", false);
    await expect(page.locator("#app-sidebar")).toBeVisible();
    await expect(page.locator("#nav-open")).toBeHidden();
    await page.setViewportSize({ width: 375, height: 800 });
    await expect(page.locator("#nav-open")).toBeVisible();
    // Le drawer fermé ne doit pas créer d'overflow global.
    await expectNoGlobalOverflow(page, "shell mobile fermé @375");
    expectClean(watch);
  });

  test("menu mobile : ouvrir, Échap, scrim, retour focus", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/tasks", false);
    const open = page.locator("#nav-open");
    await open.click();
    const sidebar = page.locator("#app-sidebar.open");
    await expect(sidebar).toBeVisible();
    await expect(page.locator("#app-scrim")).toBeVisible();
    expect(await open.getAttribute("aria-expanded")).toBe("true");
    // Le focus entre dans la navigation (piège UI-14 préservé).
    await expect(sidebar.locator("a.app-navlink").first()).toBeFocused();
    await expectNoGlobalOverflow(page, "menu mobile ouvert @375");
    await page.screenshot({ path: `${SHOTS}/avant-menu-mobile-375.png` });
    // Échap ferme et rend le focus au bouton.
    await page.keyboard.press("Escape");
    await expect(page.locator("#app-sidebar.open")).toHaveCount(0);
    await expect(open).toBeFocused();
    // Réouvrir puis fermer via le scrim.
    await open.click();
    await expect(page.locator("#app-sidebar.open")).toBeVisible();
    await page.locator("#app-scrim").click();
    await expect(page.locator("#app-sidebar.open")).toHaveCount(0);
    // Naviguer ferme le menu (stress cycle 1).
    await open.click();
    await sidebar.locator('a.app-navlink[href="#/projects"]').click();
    await expect(page.locator("#view h1").first()).toContainText("Projets", { timeout: 10_000 });
    await expect(page.locator("#app-sidebar.open")).toHaveCount(0);
    expectClean(watch);
  });
});

test.describe("UI-15 en-têtes et hiérarchie", () => {
  test("PageHeader : actions sous le titre à 375, pas de collision", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/transfers", false);
    const header = page.locator(".ds-page-header").first();
    await expect(header).toBeVisible();
    const geometry = await page.evaluate(() => {
      const h = document.querySelector(".ds-page-header");
      const title = h?.querySelector("h1");
      const actions = h?.querySelector(".ds-page-actions");
      if (!(h instanceof HTMLElement) || !(title instanceof HTMLElement)) return null;
      const hr = h.getBoundingClientRect();
      const tr = title.getBoundingClientRect();
      const ar = actions instanceof HTMLElement ? actions.getBoundingClientRect() : null;
      return {
        titleTop: tr.top,
        titleBottom: tr.bottom,
        actionsTop: ar?.top ?? null,
        overlap: ar !== null && ar.top < tr.bottom && ar.left < tr.right && ar.height > 0 && tr.height > 0,
      };
    });
    expect(geometry).not.toBeNull();
    if (geometry?.actionsTop !== null && geometry?.actionsTop !== undefined) {
      // Les actions passent sous le titre (wrap), jamais en collision.
      expect(geometry.overlap, "pas de collision titre/actions").toBe(false);
    }
    await expectNoGlobalOverflow(page, "PageHeader @375");
    expectClean(watch);
  });

  test("Workspace tabs à 375 : 6 onglets, ARIA, flèches, deep links", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, `#/projects/${P1}`, false);
    const tablist = page.locator('[data-ws-tabs][role="tablist"]');
    await expect(tablist).toBeVisible();
    const tabs = tablist.locator('[role="tab"]');
    await expect(tabs).toHaveCount(6);
    await expectNoGlobalOverflow(page, "workspace tabs @375");
    // Roving tabindex + flèches (invariant UI-14).
    await tabs.nth(0).focus();
    await page.keyboard.press("ArrowRight");
    await expect(tabs.nth(1)).toBeFocused();
    await page.keyboard.press("End");
    await expect(tabs.nth(5)).toBeFocused();
    await page.keyboard.press("Home");
    await expect(tabs.nth(0)).toBeFocused();
    // Activation = deep link réel.
    await tabs.nth(3).focus();
    await page.keyboard.press("Enter");
    expect(page.url()).toContain(`/projects/${P1}/claims`);
    await expect(page.locator("#view h1").first()).toContainText("Jeu Phare", { timeout: 10_000 });
    expectClean(watch);
  });
});

test.describe("UI-15 tâches : liste et kanban étroits", () => {
  test("liste : titre d'abord, pas d'overflow (données longues)", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/tasks", true);
    await expect(page.locator("#view h1").first()).toContainText("Tâches");
    await expect(page.locator("#view .task-row").first()).toBeVisible({ timeout: 10_000 });
    await expectNoGlobalOverflow(page, "task list @375 long");
    // L'information principale (titre) précède les métadonnées dans le DOM.
    const order = await page.evaluate(() => {
      const row = document.querySelector("#view .task-row");
      const title = row?.querySelector(".ds-list-title");
      const sub = row?.querySelector(".ds-list-sub");
      if (!(row instanceof HTMLElement) || !(title instanceof Node) || !(sub instanceof Node)) return false;
      return (Node.DOCUMENT_POSITION_FOLLOWING & row.compareDocumentPosition(title)) !== 0 &&
        (Node.DOCUMENT_POSITION_FOLLOWING & title.compareDocumentPosition(sub)) !== 0;
    });
    expect(order, "titre avant métadonnées").toBe(true);
    await page.setViewportSize({ width: 768, height: 800 });
    await go(page, "#/tasks");
    await expectNoGlobalOverflow(page, "task list @768 long");
    expectClean(watch);
  });

  test("kanban à 375 : 4 colonnes, scroll local, clavier préservé", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/tasks", true);
    await page.locator('#view [data-view="board"]').click();
    const board = page.locator("#view .tasks-board");
    await expect(board).toBeVisible({ timeout: 10_000 });
    // Les 4 statuts restent présents, aucun masqué.
    await expect(board.locator(".task-col")).toHaveCount(4);
    const titles = board.locator(".task-col-title");
    for (const name of ["À faire", "En cours", "Bloqué", "Terminé"]) {
      await expect(titles.getByText(name, { exact: false }).first()).toBeVisible();
    }
    // Scroll horizontal LOCAL, pas global.
    const scroll = await page.evaluate(() => {
      const el = document.querySelector("#view .tasks-board");
      if (!(el instanceof HTMLElement)) return null;
      const style = getComputedStyle(el);
      return { local: style.overflowX === "auto" || style.overflowX === "scroll", sw: el.scrollWidth, cw: el.clientWidth };
    });
    expect(scroll).not.toBeNull();
    expect(scroll?.local, "kanban scroll local").toBe(true);
    await expectNoGlobalOverflow(page, "kanban @375");
    // Alternative clavier/bouton UI-5 toujours disponible.
    const move = board.locator(".task-move select").first();
    await expect(move).toBeVisible();
    await expect(move).toBeEnabled();
    expectClean(watch);
  });
});

test.describe("UI-15 tables et contenus techniques", () => {
  test("claims : scroll local, scopes, pas d'overflow", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 640, height: 800 });
    await login(page, `#/projects/${P1}/claims`, true);
    await expect(page.locator("#view h1").first()).toContainText("Jeu Phare", { timeout: 10_000 });
    const table = page.locator("#workspace-panel table").first();
    await expect(table).toBeVisible({ timeout: 10_000 });
    // En-têtes à portée conservés (invariant UI-14).
    expect(await table.locator("th[scope]").count()).toBeGreaterThan(0);
    // Scroll horizontal LOCAL : la table (ou un ancêtre proche) borne le débordement.
    const local = await page.evaluate(() => {
      const el = document.querySelector("#workspace-panel table");
      if (!(el instanceof HTMLElement)) return false;
      if (getComputedStyle(el).overflowX === "auto" || getComputedStyle(el).overflowX === "scroll") return true;
      let node = el.parentElement;
      while (node !== null && node !== document.body) {
        const overflowX = getComputedStyle(node).overflowX;
        if (overflowX === "auto" || overflowX === "scroll") return true;
        node = node.parentElement;
      }
      return false;
    });
    expect(local, "table claims en scroll local").toBe(true);
    await expectNoGlobalOverflow(page, "claims table @640 long");
    await page.setViewportSize({ width: 375, height: 800 });
    await go(page, `#/projects/${P1}/claims`);
    await expectNoGlobalOverflow(page, "claims table @375 long");
    expectClean(watch);
  });

  test("inspector : blocs techniques en scroll local", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, `#/inspector/${encodeURIComponent(LONG_KEY)}`, true);
    await expect(page.locator("#view h1").first()).toBeVisible({ timeout: 10_000 });
    // Le formulaire reste utilisable : inputs dans le viewport.
    const inputBox = await page.locator("#view input").first().boundingBox();
    expect(inputBox).not.toBeNull();
    expect(inputBox?.x ?? -1).toBeGreaterThanOrEqual(0);
    expect((inputBox?.x ?? 9999) + (inputBox?.width ?? 0)).toBeLessThanOrEqual(376);
    // Soumettre pour afficher le résultat avec longues refs.
    await page.locator('#view button[type="submit"]').first().click();
    await page.waitForTimeout(1200);
    await expectNoGlobalOverflow(page, "inspector résultat @375 long");
    const codeScroll = await page.evaluate(() => {
      const codes = [...document.querySelectorAll("#view pre, #view .code")];
      return codes.map((el) => getComputedStyle(el).overflowX);
    });
    for (const overflow of codeScroll) {
      expect(["auto", "scroll", "visible"], `bloc technique scrollable : ${overflow}`).toContain(overflow);
    }
    expectClean(watch);
  });
});

test.describe("UI-15 drawers et modales à 375", () => {
  test("Machine drawer : plein écran étroit, fermeture, retour focus", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/machines", false);
    const trigger = page.locator("#view [data-machine-details]").first();
    await expect(trigger).toBeVisible({ timeout: 10_000 });
    await centerClick(trigger);
    const drawer = page.locator("#machine-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer.locator('[role="dialog"]')).toBeVisible();
    const width = await drawer.locator('[role="dialog"]').evaluate((el) => el.getBoundingClientRect().width);
    expect(width, `drawer ≤ viewport (mesuré ${width}px)`).toBeLessThanOrEqual(376);
    await expectNoGlobalOverflow(page, "machine drawer @375");
    await page.screenshot({ path: `${SHOTS}/avant-drawer-375.png` });
    // Tab reste piégé (invariant UI-14), Échap ferme + retour focus.
    await page.keyboard.press("Tab");
    const inDrawer = await page.evaluate(() => document.getElementById("machine-drawer")?.contains(document.activeElement) ?? false);
    expect(inDrawer, "focus piégé dans le drawer").toBe(true);
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(trigger).toBeFocused();
    expectClean(watch);
  });

  test("Transfer drawer + upload modal 375 : input natif, actions atteignables", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/transfers", true);
    const details = page.locator("#view [data-transfer-details]").first();
    await expect(details).toBeVisible({ timeout: 10_000 });
    await centerClick(details);
    const drawer = page.locator("#transfer-drawer");
    await expect(drawer).toBeVisible();
    // Titre de drawer avec filename très long : wrap, pas d'overflow.
    await expectNoGlobalOverflow(page, "transfer drawer @375 long");
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    // Modale d'envoi : input file natif dans le viewport.
    await centerClick(uploadOpen(page).first());
    const modal = page.locator("#transfer-upload");
    await expect(modal).toBeVisible();
    const fileInput = modal.locator('input[type="file"]');
    await expect(fileInput).toBeVisible();
    const box = await fileInput.boundingBox();
    expect(box).not.toBeNull();
    expect((box?.x ?? 9999) + (box?.width ?? 0)).toBeLessThanOrEqual(376);
    await expectNoGlobalOverflow(page, "upload modal @375");
    await page.screenshot({ path: `${SHOTS}/avant-modal-375.png` });
    // Le bouton de validation reste atteignable (scroll interne si besoin).
    const submit = modal.locator('button[type="submit"]');
    await submit.scrollIntoViewIfNeeded();
    await expect(submit).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(modal).toBeHidden();
    expectClean(watch);
  });

  test("modale viewport court 375×667 : validation accessible", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 667 });
    await login(page, "#/transfers", false);
    await centerClick(uploadOpen(page).first());
    const modal = page.locator("#transfer-upload");
    await expect(modal).toBeVisible();
    const dialog = modal.locator('[role="dialog"]');
    const rect = await dialog.evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, height: r.height };
    });
    expect(rect.top, "modale dans le viewport").toBeGreaterThanOrEqual(-1);
    expect(rect.bottom, `modale tient en hauteur (${rect.bottom}px pour 667)`).toBeLessThanOrEqual(668);
    const submit = modal.locator('button[type="submit"]');
    await submit.scrollIntoViewIfNeeded();
    await expect(submit).toBeVisible();
    expectClean(watch);
  });
});

test.describe("UI-15 contextes particuliers", () => {
  test("login à 375 : formulaire dans le viewport", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await page.route("**/api/**", apiStub15(false));
    await page.goto("/#/");
    await expect(page.locator("#login-form")).toBeVisible({ timeout: 15_000 });
    await expectNoGlobalOverflow(page, "login @375");
    for (const selector of ["#login-email", "#login-password", '#login-form button[type="submit"]']) {
      const box = await page.locator(selector).boundingBox();
      expect(box, selector).not.toBeNull();
      expect((box?.x ?? 9999) + (box?.width ?? 0), `${selector} dans le viewport`).toBeLessThanOrEqual(376);
    }
    expectClean(watch);
  });

  test("paysage étroit 667×375 : tâches et bibliothèque utilisables", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 667, height: 375 });
    await login(page, "#/tasks", false);
    await expect(page.locator("#view h1").first()).toContainText("Tâches");
    await expectNoGlobalOverflow(page, "tasks paysage 667×375");
    await expect(page.locator("#nav-open")).toBeVisible();
    await page.locator("#nav-open").click();
    await expect(page.locator("#app-sidebar.open")).toBeVisible();
    await expectNoGlobalOverflow(page, "menu paysage 667×375");
    await page.keyboard.press("Escape");
    await go(page, "#/library/rules");
    await expectNoGlobalOverflow(page, "library paysage 667×375");
    expectClean(watch);
  });

  test("zoom 200 % (≈720px) et reflow extrême (≈360px)", async ({ page }) => {
    test.setTimeout(300_000);
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 720, height: 900 });
    await login(page, "#/", true);
    for (const hash of ["#/projects", "#/library", "#/inspector", "#/configuration/runtimes"]) {
      await go(page, hash);
      await expect(page.locator("#view h1").first()).toBeVisible({ timeout: 10_000 });
      await expectNoGlobalOverflow(page, `${hash} @720 (zoom 200 %)`);
    }
    // Reflow extrême : une surface représentative reste fonctionnelle.
    await page.setViewportSize({ width: 360, height: 800 });
    await go(page, "#/tasks");
    await expect(page.locator("#view h1").first()).toContainText("Tâches");
    await expectNoGlobalOverflow(page, "tasks @360 (reflow extrême)");
    expectClean(watch);
  });
});

test.describe("UI-15 invariants a11y après responsive (essentiels)", () => {
  test("skip-link premier Tab, focus visible, live region à 375", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/tasks", false);
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => {
      const active = document.activeElement;
      return active instanceof HTMLElement ? active.className : "(null)";
    });
    expect(focused, "premier Tab = skip-link").toContain("ds-skip-link");
    await expect(page.locator("#ds-toast-region[role=status][aria-live]")).toHaveCount(1);
    // Focus visible : la règle globale existe et aucun reset ne la supprime.
    const focusRule = await page.evaluate(() => {
      const found: string[] = [];
      for (const sheet of document.styleSheets) {
        let rules: CSSRuleList | null = null;
        try {
          rules = sheet.cssRules;
        } catch {
          continue;
        }
        if (rules === null) continue;
        for (const rule of rules) {
          if (rule instanceof CSSStyleRule && rule.selectorText.includes(":focus-visible")) {
            found.push(`${rule.selectorText} { ${rule.style.cssText} }`);
          }
        }
      }
      return found;
    });
    expect(focusRule.length, "règle :focus-visible présente").toBeGreaterThan(0);
    expect(focusRule.some((rule) => rule.includes("outline")), "focus-visible avec outline").toBe(true);
    expectClean(watch);
  });

  test("modal focus 375 : Tab, Shift+Tab, Échap, retour focus", async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/transfers", false);
    const trigger = uploadOpen(page).first();
    await expect(trigger).toBeVisible({ timeout: 10_000 });
    await centerClick(trigger);
    const modal = page.locator("#transfer-upload");
    await expect(modal).toBeVisible();
    await page.keyboard.press("Tab");
    const trapped = await page.evaluate(() => document.getElementById("transfer-upload")?.contains(document.activeElement) ?? false);
    expect(trapped, "Tab piégé dans la modale à 375").toBe(true);
    await page.keyboard.press("Shift+Tab");
    const stillTrapped = await page.evaluate(() => document.getElementById("transfer-upload")?.contains(document.activeElement) ?? false);
    expect(stillTrapped, "Shift+Tab piégé dans la modale à 375").toBe(true);
    await page.keyboard.press("Escape");
    await expect(modal).toBeHidden();
    await expect(trigger).toBeFocused();
    expectClean(watch);
  });

  test("axe : surfaces modifiées, 0 critique/sérieuse", async ({ page }) => {
    test.setTimeout(300_000);
    const watch = watchErrors(page);
    const serious: string[] = [];
    const collect = (scope: string, violations: { id: string; help: string; impact?: string | null; nodes: unknown[] }[]): void => {
      for (const violation of violations.filter((v) => v.impact === "critical" || v.impact === "serious")) {
        serious.push(`${scope}/${violation.id}: ${violation.help} (${(violation.nodes as unknown[]).length} nœuds)`);
      }
    };
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page, "#/library", true);
    collect("library-375", (await new AxeBuilder({ page }).analyze()).violations);
    await go(page, `#/projects/${P1}/claims`);
    collect("claims-375", (await new AxeBuilder({ page }).analyze()).violations);
    await page.setViewportSize({ width: 768, height: 800 });
    await go(page, "#/");
    collect("home-768-long", (await new AxeBuilder({ page }).analyze()).violations);
    expect(serious, `violations axe: ${serious.join(" | ")}`).toEqual([]);
    expectClean(watch);
  });
});
