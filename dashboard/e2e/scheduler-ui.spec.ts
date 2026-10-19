/**
 * MC P05 — panneau d'admission batch d'une roadmap (API stubbée déterministe).
 *
 * Le serveur calcule seul l'ordre, l'éligibilité, les exclusions et le
 * `plan_digest` ; le dashboard affiche le dry-run tel quel puis renvoie ce
 * digest à l'admission. On vérifie ici les garanties du contrat : ordre
 * serveur respecté, exclusions motivées, aucun POST avant confirmation, un
 * seul lot au double clic, un aperçu périmé (409 `admission_plan_changed`)
 * remplacé et re-confirmé, un POST 503 rejoué à l'identique après rechargement
 * (`Idempotency-Key` conservée) et un second utilisateur refusé sans créer de
 * second lot. Aucun backend : tout passe par `page.route`.
 */
import { expect, test, type Page, type Route } from "@playwright/test";
import type { components } from "../src/openapi-schema";
import { go, login, newCaptured } from "./support/ui16-stub";

type AdmissionDryRun = components["schemas"]["AdmissionDryRun"];
type AdmissionCandidate = components["schemas"]["AdmissionCandidate"];
type AdmissionExclusion = components["schemas"]["AdmissionExclusion"];
type AdmissionBatchRequest = components["schemas"]["AdmissionBatchRequest"];
type AdmissionBatchResult = components["schemas"]["AdmissionBatchResult"];
type MachineEligibility = components["schemas"]["MachineEligibility"];
type TaskLaunch = components["schemas"]["TaskLaunch"];

const PROJECT_ID = "11111111-2222-4333-8444-555555555555";
const ROADMAP_ID = "11111111-1111-4111-8111-111111111111";
const T1 = "aaaaaaaa-0000-4111-8111-000000000001";
const T2 = "aaaaaaaa-0000-4111-8111-000000000002";
const T3 = "aaaaaaaa-0000-4111-8111-000000000003";
const TX = "aaaaaaaa-0000-4111-8111-000000000009";
const TX2 = "aaaaaaaa-0000-4111-8111-00000000000a";
const MA = "aaaaaaaa-0000-4111-8111-0000000000a1";
const MB = "aaaaaaaa-0000-4111-8111-0000000000b2";

const DIGEST_V1 = `sha256:${"a".repeat(64)}`;
const DIGEST_V2 = `sha256:${"b".repeat(64)}`;

function candidate(taskId: string, stepKey: string, title: string, machineIds: string[]): AdmissionCandidate {
  return { task_id: taskId, step_key: stepKey, title, machine_ids: machineIds };
}

function exclusion(
  taskId: string,
  stepKey: string,
  title: string,
  reasons: AdmissionExclusion["reasons"],
  waitingOn: string[] = [],
): AdmissionExclusion {
  return { task_id: taskId, step_key: stepKey, title, reasons, waiting_on: waitingOn };
}

function machine(id: string, name: string, freeSlots: number): MachineEligibility {
  return {
    machine_id: id,
    display_name: name,
    status: "online",
    eligible: true,
    reasons: [],
    harnesses: [
      { harness_id: "claude-code", version: "2.1.0", detected: true, configured: true },
      { harness_id: "ghost", version: null, detected: false, configured: false },
    ],
    free_slots: freeSlots,
    reported_at: "2026-10-16T08:00:00Z",
  };
}

/** Aperçu confirmé par l'humain : ordre serveur T1, T2, T3 puis exclusions. */
function planV1(): AdmissionDryRun {
  return {
    roadmap_id: ROADMAP_ID,
    project_id: PROJECT_ID,
    roadmap_status: "active",
    roadmap_version: 7,
    harness_id: null,
    launchable: [
      candidate(T1, "P1.1", "Boucle de jeu", [MA, MB]),
      candidate(T2, "P1.2", "Sons", [MA]),
      candidate(T3, "P1.3", "Finition", [MB]),
    ],
    excluded: [
      exclusion(TX, "P1.4", "Refonte réseau", ["dependency_pending"], ["P1.3"]),
      exclusion(TX2, "P1.5", "Publier la démo", ["task_completed"]),
    ],
    steps_without_tasks: [],
    machines: [machine(MA, "flo-laptop", 2), machine(MB, "mathieu-desktop", 1)],
    plan_digest: DIGEST_V1,
    evaluated_at: "2026-10-16T09:00:00Z",
  };
}

/** Plan frais : le serveur a bougé (T1 verrouillée, ordre différent). */
function planV2(): AdmissionDryRun {
  return {
    ...planV1(),
    launchable: [
      candidate(T2, "P1.2", "Sons", [MA]),
      candidate(T3, "P1.3", "Finition", [MB]),
    ],
    excluded: [exclusion(T1, "P1.1", "Boucle de jeu", ["task_claimed_elsewhere"])],
    plan_digest: DIGEST_V2,
    evaluated_at: "2026-10-16T09:05:00Z",
  };
}

function launch(taskId: string, machineId: string, index: number): TaskLaunch {
  return {
    created_at: "2026-10-16T09:30:00Z",
    updated_at: "2026-10-16T09:30:00Z",
    version: 1,
    id: `dddddddd-0000-4111-8111-${String(index).padStart(12, "0")}`,
    project_id: PROJECT_ID,
    task_id: taskId,
    machine_id: machineId,
    requested_by_user_id: "00000000-0000-4000-8000-0000000000e2",
    harness_id: "claude-code",
    agent_stable_key: null,
    status: "requested",
    reason_code: "none",
    session_id: null,
    output_excerpt: null,
    expires_at: "2026-10-16T09:45:00Z",
    finished_at: null,
    profile: null,
  };
}

type ServerMode = "ok" | "stale" | "unavailable" | "multi";

interface AdmissionServer {
  mode: ServerMode;
  dryRun: AdmissionDryRun;
  freshPlan: AdmissionDryRun;
  posts: { key: string | null; body: unknown }[];
  created: number;
  admitted: boolean;
}

function newServer(mode: ServerMode): AdmissionServer {
  return { mode, dryRun: planV1(), freshPlan: planV2(), posts: [], created: 0, admitted: false };
}

function project(): Record<string, unknown> {
  return {
    id: PROJECT_ID,
    slug: "admission-fixture",
    name: "Studi'OS Admission",
    description: "Projet de validation du panneau d'admission.",
    archived: false,
    created_at: "2026-09-20T10:00:00Z",
    updated_at: "2026-09-20T12:00:00Z",
    version: 1,
  };
}

function roadmapSummary(): Record<string, unknown> {
  return {
    id: ROADMAP_ID,
    project_id: PROJECT_ID,
    title: "Sprint admission",
    status: "active",
    revision_no: 2,
    approved_revision_no: 1,
    progress: { done: 0, total: 3, skipped: 0, ratio: 0 },
    current_step_key: "P1.1",
  };
}

function activeRoadmap(): Record<string, unknown> {
  const step = (key: string, title: string, taskId: string): Record<string, unknown> => ({
    id: `st-${key}`,
    roadmap_id: ROADMAP_ID,
    phase_id: "ph1",
    key,
    position: 0,
    title,
    state: "not_started",
    available: true,
    waiting_on: [],
    acceptance_criteria: ["Critère OK"],
    depends_on: [],
    tasks: [{ hydration_key: taskId, title }],
    linked_tasks: [],
    criteria_checked: [],
  });
  return {
    ...roadmapSummary(),
    objective: "Lancer le lot de tâches éligibles",
    version: 7,
    phases: [
      {
        id: "ph1",
        roadmap_id: ROADMAP_ID,
        key: "P1",
        position: 0,
        title: "Prototype",
        progress: { done: 0, total: 3, skipped: 0, ratio: 0 },
        steps: [step("P1.1", "Boucle de jeu", T1), step("P1.2", "Sons", T2), step("P1.3", "Finition", T3)],
      },
    ],
  };
}

const json = (route: Route, status: number, body: unknown): Promise<void> =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

/** Routes roadmap actives (catalogue + détail) : l'onglet démarre en Exécution. */
async function installRoadmap(page: Page): Promise<void> {
  await page.route(new RegExp(`/api/v1/projects/${PROJECT_ID}/state$`), (route) =>
    json(route, 200, { project_id: PROJECT_ID, active_tasks: [], active_claims: [], generated_at: "2026-10-16T09:00:00Z" }),
  );
  await page.route(new RegExp(`/api/v1/projects/${PROJECT_ID}$`), (route) => json(route, 200, project()));
  await page.route(new RegExp(`/api/v1/projects/${PROJECT_ID}/roadmaps`), (route) => json(route, 200, [roadmapSummary()]));
  await page.route(new RegExp("/api/v1/roadmaps/[^/]+$"), (route) => json(route, 200, activeRoadmap()));
}

/** Aperçu + admission stubbés sur un état serveur partagé (multi-utilisateur). */
async function installAdmission(page: Page, server: AdmissionServer): Promise<void> {
  await page.route(/\/api\/v1\/roadmaps\/[^/]+\/admission\/dry-run/, (route) => {
    const harnessId = new URL(route.request().url()).searchParams.get("harness_id");
    return json(route, 200, { ...server.dryRun, harness_id: harnessId });
  });
  await page.route(/\/api\/v1\/roadmaps\/[^/]+\/admission$/, (route) => {
    const request = route.request();
    const body = request.postDataJSON() as AdmissionBatchRequest;
    server.posts.push({ key: request.headers()["idempotency-key"] ?? null, body });
    if (server.mode === "unavailable") return json(route, 503, { detail: "service indisponible" });
    if (server.mode === "stale") {
      server.dryRun = server.freshPlan;
      return json(route, 409, { detail: { error_code: "admission_plan_changed", plan: server.freshPlan } });
    }
    if (server.mode === "multi" && server.admitted) {
      return json(route, 409, { detail: { error_code: "admission_plan_changed", plan: server.freshPlan } });
    }
    server.admitted = true;
    server.created += 1;
    const result: AdmissionBatchResult = {
      roadmap_id: ROADMAP_ID,
      plan_digest: body.plan_digest,
      launches: body.items.map((item, index) => launch(item.task_id, item.machine_id, index + 1)),
      admitted_at: "2026-10-16T09:30:00Z",
    };
    return json(route, 201, result);
  });
}

async function openAdmission(page: Page, server: AdmissionServer): Promise<void> {
  await login(page, "#/projects", newCaptured(), { role: "admin" });
  await installRoadmap(page);
  await installAdmission(page, server);
  await go(page, `#/projects/${PROJECT_ID}/roadmap`);
  await expect(page.locator("[data-admission-panel]")).toBeVisible();
}

/** Le harnais est requis pour activer la confirmation ; il relance le dry-run. */
async function chooseHarness(page: Page): Promise<void> {
  await expect(page.locator('select[data-admission-harness] option[value="claude-code"]')).toHaveCount(1);
  await page.locator("select[data-admission-harness]").selectOption("claude-code");
  await expect(page.locator("[data-admission-confirm]")).toBeEnabled();
}

async function confirmAndSubmit(page: Page): Promise<void> {
  await page.locator("[data-admission-confirm]").click();
  await expect(page.locator("[data-admission-confirmation]")).toBeVisible();
  await page.locator("[data-admission-submit]").click();
}

/** Rejoue la connexion après `page.reload()` (JWT en mémoire uniquement). */
async function fillLogin(page: Page): Promise<void> {
  await expect(page.locator("#login-form")).toBeVisible({ timeout: 15_000 });
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible({ timeout: 15_000 });
}

async function launchableIds(page: Page): Promise<(string | null)[]> {
  return page
    .locator("[data-admission-launchable] li[data-task-id]")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-task-id")));
}

test.describe("Admission batch d'une roadmap", () => {
  test("aperçu : ordre serveur, exclusions motivées, aucun POST avant submit", async ({ page }) => {
    const server = newServer("ok");
    await openAdmission(page, server);

    await expect(page.locator("[data-admission-preview]")).toBeVisible();
    // Ordre des tâches = ordre serveur, tel quel.
    expect(await launchableIds(page)).toEqual([T1, T2, T3]);

    const excluded = page.locator("[data-admission-excluded] li[data-task-id]");
    await expect(excluded).toHaveCount(2);
    await expect(page.locator(`[data-admission-excluded] li[data-task-id="${TX}"]`)).toContainText("Refonte réseau");
    await expect(page.locator(`[data-admission-excluded] li[data-task-id="${TX}"] [data-admission-reason="dependency_pending"]`)).toBeVisible();
    await expect(page.locator(`[data-admission-excluded] li[data-task-id="${TX2}"] [data-admission-reason="task_completed"]`)).toBeVisible();

    await chooseHarness(page);
    await page.locator("[data-admission-confirm]").click();
    await expect(page.locator("[data-admission-confirmation]")).toBeVisible();
    // Aucun POST tant que submit n'est pas actionné.
    expect(server.posts).toHaveLength(0);

    await page.locator("[data-admission-submit]").click();
    await expect(page.locator("[data-admission-result]")).toBeVisible();
    expect(server.posts).toHaveLength(1);
    expect(server.created).toBe(1);
  });

  test("double clic sur submit : exactement un POST", async ({ page }) => {
    const server = newServer("ok");
    await openAdmission(page, server);
    await chooseHarness(page);
    await page.locator("[data-admission-confirm]").click();
    await expect(page.locator("[data-admission-confirmation]")).toBeVisible();

    // Deux clics synchrones : le garde d'envoi ne doit laisser passer qu'un lot.
    await page.locator("[data-admission-submit]").evaluate((node) => {
      (node as HTMLElement).click();
      (node as HTMLElement).click();
    });
    await expect(page.locator("[data-admission-result]")).toBeVisible();
    expect(server.posts).toHaveLength(1);
  });

  test("aperçu périmé : 409 plan_changed, plan remplacé, re-confirmation exigée", async ({ page }) => {
    const server = newServer("stale");
    await openAdmission(page, server);
    await chooseHarness(page);
    await confirmAndSubmit(page);

    await expect(page.locator("[data-admission-stale]")).toBeVisible();
    // Aucun lancement créé : le lot a été refusé en bloc.
    await expect(page.locator("[data-admission-result]")).toHaveCount(0);
    expect(server.created).toBe(0);
    expect(server.posts).toHaveLength(1);

    // Le plan frais remplace l'aperçu périmé (T1 désormais exclue).
    await expect
      .poll(() => launchableIds(page))
      .toEqual([T2, T3]);
    await expect(page.locator(`[data-admission-excluded] li[data-task-id="${T1}"] [data-admission-reason="task_claimed_elsewhere"]`)).toBeVisible();

    // Nouvelle confirmation exigée : le dialogue précédent est refermé.
    await expect(page.locator("[data-admission-confirmation]")).toBeHidden();
  });

  test("rechargement : POST 503 rejoué à l'identique via resume-send", async ({ page }) => {
    const server = newServer("unavailable");
    await openAdmission(page, server);
    await chooseHarness(page);
    await confirmAndSubmit(page);
    await expect.poll(() => server.posts.length).toBe(1);

    const first = server.posts[0];
    expect(first?.key).toBeTruthy();

    await page.reload();
    await fillLogin(page);
    await expect(page.locator("[data-admission-panel]")).toBeVisible();

    // Aucun POST automatique au rechargement : l'humain reprend la main.
    await expect(page.locator("[data-admission-resume]")).toBeVisible();
    expect(server.posts).toHaveLength(1);

    await page.locator("[data-admission-resume-send]").click();
    await expect.poll(() => server.posts.length).toBe(2);
    const second = server.posts[1];
    expect(second?.key).toBe(first?.key);
    expect(second?.body).toEqual(first?.body);
  });

  test("multi-utilisateur : le second lot est refusé, un seul 201 au total", async ({ browser }) => {
    const server = newServer("multi");
    const first = await browser.newContext();
    const second = await browser.newContext();
    try {
      const pageA = await first.newPage();
      await openAdmission(pageA, server);
      await chooseHarness(pageA);
      await confirmAndSubmit(pageA);
      await expect(pageA.locator("[data-admission-result]")).toBeVisible();
      expect(server.created).toBe(1);

      const pageB = await second.newPage();
      await openAdmission(pageB, server);
      await chooseHarness(pageB);
      await confirmAndSubmit(pageB);
      await expect(pageB.locator("[data-admission-stale]")).toBeVisible();
      await expect(pageB.locator("[data-admission-result]")).toHaveCount(0);
      expect(server.created).toBe(1);
    } finally {
      await first.close();
      await second.close();
    }
  });
});
