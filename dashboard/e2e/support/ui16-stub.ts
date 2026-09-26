/**
 * API stubbée déterministe pour la clôture UI-16 : données réalistes (statuts
 * réels du contrat, dates récentes), écritures capturées, échecs pilotables.
 * Aucun backend, aucun réseau : tout passe par page.route.
 */
import { expect, type Page, type Route } from "@playwright/test";

export const P1 = "11111111-2222-4333-8444-555555555555";
export const T1 = "aaaaaaaa-0000-4111-8111-000000000001";
export const M1 = "aaaaaaaa-0000-4111-8111-0000000000a1";
export const LIB_ID = "11111111-1111-4111-8111-111111111111";
export const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
export const ISO_RE = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
const CSP_RE = /content security policy|securitypolicyviolation/i;

export interface StubOptions {
  /** Statut forcé de POST /projects (défaut 201). */
  createProjectStatus?: number;
  /** Corps d'erreur renvoyé si createProjectStatus ≥ 400. */
  createProjectError?: unknown;
  /** Délai appliqué à POST /tasks (pour observer l'état en vol). */
  createTaskDelayMs?: number;
  /** GET /review-queue répond 500 (dégradation partielle de l'Accueil). */
  reviewQueueFails?: boolean;
  /** GET /tasks répond 401. */
  tasksUnauthorized?: boolean;
  /** Rôle renvoyé par GET /auth/me (défaut : route non stubbée, aucune identité). */
  role?: string;
}

export interface Captured {
  taskPosts: number;
  bindingDeletes: string[];
  claimReleases: string[];
  apiCalls: string[];
}

export function newCaptured(): Captured {
  return { taskPosts: 0, bindingDeletes: [], claimReleases: [], apiCalls: [] };
}

const now = Date.now();
const ago = (ms: number): string => new Date(now - ms).toISOString();
const ahead = (ms: number): string => new Date(now + ms).toISOString();

function data() {
  const project = {
    id: P1,
    slug: "phare",
    name: "Jeu Phare",
    description: "Le jeu principal du studio",
    archived: false,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-10T10:00:00Z",
    version: 7,
  };
  const task = (id: string, n: number, status: string, title: string, machine: string | null) => ({
    id,
    project_id: P1,
    readable_id: `T-00${n}`,
    title,
    description: n === 1 ? "La caméra reste figée au lancement sur Android." : null,
    status,
    claimed_by_machine_id: machine,
    claimed_by_agent_id: machine === null ? null : "ag-claude",
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-11T10:00:00Z",
    version: n,
  });
  const tasks = [
    task(T1, 1, "blocked", "Caméra Android bloquée", null),
    task("bbbbbbbb-0000-4111-8111-000000000002", 2, "in_progress", "Refonte de l'écran titre", M1),
    task("cccccccc-0000-4111-8111-000000000003", 3, "created", "Corriger le doublon de tâche", null),
    task("dddddddd-0000-4111-8111-000000000004", 4, "completed", "Publier la démo", null),
  ];
  const reviewItems = [
    { kind: "ai_work_review", id: "rw1", project_id: P1, task_id: T1, title: "Relire la sortie agent", agent_id: "ag-claude", requested_at: ago(3600_000) },
    { kind: "decision_proposal", id: "rw2", project_id: P1, task_id: null, readable_id: "DEC-0049", title: "Choisir le moteur de rendu", proposed_by_type: "agent", requested_at: ago(7200_000) },
  ];
  const decisions = [
    { id: "dec-1", readable_id: "DEC-0049", project_id: P1, task_id: T1, title: "Choisir le moteur de rendu", body: "Nous choisissons Godot.", status: "accepted", proposed_by_type: "agent", proposed_by_id: "ag-claude", created_at: ago(86400_000) },
  ];
  const agents = [
    { id: "ag-claude", machine_id: M1, display_name: "Claude", agent_kind: "dev", agent_profile: null, harness: "opencode", provider: "anthropic", model: "claude-sonnet-5", created_at: "2026-09-14T10:00:00Z", updated_at: "2026-09-14T10:00:00Z", version: 1 },
  ];
  const sessions = [{ id: "sess-1", task_id: T1, machine_id: M1, agent_id: "ag-claude", started_at: ago(300_000), ended_at: null }];
  const transfers = [
    {
      id: "aaaaaaaa-1111-4111-8111-000000000001",
      transfer_code: "TRF-ABCD1234",
      sender_user_id: "bbbbbbbb-2222-4222-8222-000000000002",
      recipient_user_id: null,
      project_id: P1,
      task_id: T1,
      build_id: null,
      category: "build",
      filename: "build-studio-os.zip",
      object_key: "studio/studio-os/build-studio-os.zip",
      content_type: "application/zip",
      size_bytes: 1536,
      sha256: "deadbeef",
      content_md5: "YWJjZA==",
      status: "ready",
      expires_at: ahead(7 * 86400_000),
      created_at: ago(3600_000),
      uploaded_at: ago(3000_000),
      downloaded_at: null,
      deleted_at: null,
    },
  ];
  const library = [
    { id: LIB_ID, kind: "rule", stable_key: "coding-standard", scope: "studio", status: "active", active_version: 2, owner_user_id: null, project_id: null, created_by_user_id: null, version: 3, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z" },
    { id: "33333333-3333-4333-8333-333333333333", kind: "skill", stable_key: "review-helper", scope: "project", status: "draft", active_version: 0, owner_user_id: null, project_id: P1, created_by_user_id: null, version: 1, created_at: "2026-02-01T00:00:00Z", updated_at: "2026-02-02T00:00:00Z" },
  ];
  const versions = [
    { id: "22222222-2222-4222-8222-222222222222", resource_id: LIB_ID, version: 2, title: "Coding standard v2", description: "Standard de code", content: { text: "Contenu de la règle." }, dependencies: [], created_by_user_id: null, created_at: "2026-01-02T00:00:00Z" },
  ];
  const runtimes = [
    { id: "rt1", owner_user_id: "u1", machine_id: M1, harness_ref: "opencode", provider_ref: "anthropic", model_ref: null, capabilities: { coding: true, tools: [], local: true }, capability_source: "declared", runtime_metadata: {}, status: "active", version: 1, created_at: "2026-09-14T10:00:00Z", updated_at: null },
  ];
  const bindings = [
    { id: "bd1", level: "project_override", owner_user_id: "u1", project_id: P1, target_kind: "rule", target_stable_key: "coding-standard", target: { runtime_id: "rt1" }, created_at: "2026-09-14T10:00:00Z" },
  ];
  const claims = [
    { id: "cl1", project_id: P1, resource_path: "godot/scenes/niveau.tscn", resource_type: "file", claimed_by_machine_id: M1, task_id: T1, status: "active", ttl_seconds: 3600, created_at: ago(1000), renewed_at: null, expires_at: ahead(3600_000), released_at: null },
  ];
  const envelope = {
    event_id: "e1",
    event_type: "session.started",
    project_id: P1,
    task_id: T1,
    machine_id: M1,
    actor_type: "agent",
    actor_id: "ag-claude",
    client_timestamp: ago(120_000),
    server_timestamp: ago(120_000),
    payload: {},
    schema_version: 1,
  };
  return { project, tasks, reviewItems, decisions, agents, sessions, transfers, library, versions, runtimes, bindings, claims, envelope };
}

export function apiStub(captured: Captured, options: StubOptions = {}) {
  const d = data();
  let taskSeq = 100;
  return async (route: Route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    captured.apiCalls.push(`${method} ${path}`);
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) return json(200, { access_token: "e2e-token", token_type: "bearer", expires_in: 900 });
    if (url.endsWith("/api/v1/auth/me") && options.role !== undefined) {
      return json(200, { user_id: "00000000-0000-4000-8000-0000000000e2", display_name: "E2E", email: "e2e@example.test", role: options.role });
    }
    if (method === "POST" && url.endsWith("/api/v1/projects")) {
      const status = options.createProjectStatus ?? 201;
      return json(status, status >= 400 ? (options.createProjectError ?? { detail: "erreur" }) : d.project);
    }
    if (method === "POST" && url.endsWith("/api/v1/tasks")) {
      captured.taskPosts += 1;
      if (options.createTaskDelayMs !== undefined) await new Promise((resolve) => setTimeout(resolve, options.createTaskDelayMs));
      taskSeq += 1;
      return json(201, { ...d.tasks[0], id: `eeeeeeee-0000-4111-8111-${String(taskSeq).padStart(12, "0")}` });
    }
    if (method === "DELETE" && /\/api\/v1\/runtime-bindings\/[^/]+$/.test(url)) {
      captured.bindingDeletes.push(path);
      return route.fulfill({ status: 204 });
    }
    if (method === "DELETE" && /\/api\/v1\/claims\/[^/]+$/.test(url)) {
      captured.claimReleases.push(path);
      return route.fulfill({ status: 204 });
    }
    if (url.endsWith("/api/v1/resolutions")) return json(200, { agent: null, rules: [], skills: [], requirements: {}, composed_agents: [], workflows: [], model_profile: null, runtime: null });
    if (method === "GET" && /\/api\/v1\/machines\/?$/.test(url)) return json(404, { detail: "not found" });
    if (/\/api\/v1\/projects\/[^/]+\/state$/.test(url)) return json(200, { project_id: P1, active_tasks: [], active_claims: [], generated_at: "2026-09-12T10:00:00Z" });
    if (/\/api\/v1\/projects\/[^/]+$/.test(url)) return json(200, d.project);
    if (url.endsWith("/api/v1/projects")) return json(200, [d.project]);
    if (options.tasksUnauthorized === true && url.includes("/api/v1/tasks") && method === "GET") return json(401, { detail: "Not authenticated" });
    if (/\/api\/v1\/tasks\/[^/]+$/.test(url)) return json(200, d.tasks[0]);
    if (url.includes("/api/v1/tasks")) return json(200, d.tasks);
    if (url.includes("/api/v1/transfers/consumption")) return json(200, { consumed_bytes: 512, quota_bytes: 104857600, remaining_bytes: 104857088, project_id: null });
    if (/\/api\/v1\/transfers\/[^/]+$/.test(url)) return json(200, d.transfers[0]);
    if (url.includes("/api/v1/transfers")) return json(200, d.transfers);
    if (/\/api\/v1\/library\/[^/]+\/versions/.test(url)) return json(200, d.versions);
    if (/\/api\/v1\/library\/[^/]+$/.test(url)) return json(200, d.library[0]);
    if (url.includes("/api/v1/library-locks")) return json(200, []);
    if (url.includes("/api/v1/library")) return json(200, d.library);
    if (url.includes("/api/v1/decisions")) return json(200, d.decisions);
    if (url.includes("/api/v1/review-queue")) {
      if (options.reviewQueueFails === true) return json(500, { detail: "boom" });
      return json(200, { items: d.reviewItems, generated_at: ago(1000) });
    }
    if (/\/api\/v1\/runtimes\/[^/]+$/.test(url)) return json(200, d.runtimes[0]);
    if (url.includes("/api/v1/runtimes")) return json(200, d.runtimes);
    if (url.includes("/api/v1/runtime-bindings")) return json(200, d.bindings);
    if (url.includes("/api/v1/timeline")) return json(200, { project_id: P1, days: [{ date: "2026-09-11", events: [d.envelope] }] });
    if (url.includes("/api/v1/claims")) return json(200, d.claims);
    if (url.includes("/api/v1/agents")) return json(200, d.agents);
    if (url.includes("/api/v1/sessions")) return json(200, d.sessions);
    if (url.includes("/api/v1/events")) return json(200, [d.envelope]);
    return json(200, []);
  };
}

export interface ErrorWatch {
  csp: string[];
  fatal: Error[];
  errors: string[];
}

export function watchErrors(page: Page): ErrorWatch {
  const watch: ErrorWatch = { csp: [], fatal: [], errors: [] };
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    watch.errors.push(msg.text());
    if (CSP_RE.test(msg.text())) watch.csp.push(msg.text());
  });
  page.on("pageerror", (error) => watch.fatal.push(error));
  return watch;
}

/**
 * Zéro violation CSP, zéro pageerror, zéro erreur console inattendue.
 * Bruit environnemental attendu et documenté : le navigateur journalise
 * « Failed to load resource » pour les réponses HTTP en échec que les vues
 * absorbent volontairement (404 de GET /machines, 401/500 injectés par un test).
 */
export function expectClean(watch: ErrorWatch, tolerated: RegExp[] = []): void {
  expect(watch.csp, `violations CSP: ${watch.csp.join(" | ")}`).toEqual([]);
  expect(watch.fatal, `pageerrors: ${watch.fatal.map(String).join(" | ")}`).toEqual([]);
  const unexpected = watch.errors.filter(
    (message) => !/^Failed to load resource: the server responded with a status of (404|401|403|500)/.test(message) && !tolerated.some((re) => re.test(message)),
  );
  expect(unexpected, `erreurs console: ${unexpected.join(" | ")}`).toEqual([]);
}

export async function login(page: Page, startHash: string, captured: Captured, options: StubOptions = {}): Promise<void> {
  await page.route("**/api/**", apiStub(captured, options));
  await page.route("**/healthz", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.goto(`/${startHash}`);
  await expect(page.locator("#login-form")).toBeVisible({ timeout: 15_000 });
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible({ timeout: 15_000 });
  // Le premier rendu remplace #view d'un bloc : attendre qu'il ait eu lieu.
  await expect(page.locator("#view h1")).toBeVisible({ timeout: 15_000 });
}

/**
 * Navigation par hash puis attente que la nouvelle vue ait réellement
 * remplacé l'ancienne (le rendu se fait hors-champ puis remplace #view).
 * Le hash cible doit différer du hash courant.
 */
export async function go(page: Page, hash: string): Promise<void> {
  await page.evaluate((target) => {
    (window as unknown as { __prevView: Element | null }).__prevView = document.getElementById("view");
    window.location.hash = target;
  }, hash);
  await page.waitForFunction(
    () => document.getElementById("view") !== (window as unknown as { __prevView: Element | null }).__prevView,
    undefined,
    { timeout: 10_000 },
  );
  await expect(page.locator("#view h1, #view h2").first()).toBeVisible({ timeout: 10_000 });
}

export async function globalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth));
}
