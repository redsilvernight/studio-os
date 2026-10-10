/**
 * P02 — Mission Control (vue projet, lecture seule), API stubbée déterministe.
 *
 * Ne dépend que du contrat DOM de docs/mission-control/ui.md et des routes
 * `#/projects/<id>` (vue d'ensemble) et `#/projects/<id>/mission` (onglet).
 * Le read model GET /api/v1/projects/{id}/mission est stubbé avec des données
 * conformes à components["schemas"]["ProjectMission"], y compris un verdict
 * inconnu (vocabulaire additif) et une lacune `machine_unknown`.
 */
import { expect, test, type Page, type Route } from "@playwright/test";
import type { components } from "../src/openapi-schema";
import { apiStub, expectClean, newCaptured, P1, UUID_RE, watchErrors, type Captured } from "./support/ui16-stub";

type ProjectMission = components["schemas"]["ProjectMission"];
type MissionRun = components["schemas"]["MissionRun"];

const MACHINE = "aaaaaaaa-0000-4111-8111-0000000000a1";
const CURSOR = "opaque-cursor-page-2";
const HANDOFF_SUMMARY = "Écran titre refondu, tests verts, PR ouverte.";
const now = Date.now();
const ago = (ms: number): string => new Date(now - ms).toISOString();

const RUN = {
  running: "10000000-0000-4111-8111-000000000001",
  waiting: "10000000-0000-4111-8111-000000000002",
  attention: "10000000-0000-4111-8111-000000000003",
  done: "10000000-0000-4111-8111-000000000004",
  failed: "10000000-0000-4111-8111-000000000005",
  unknown: "10000000-0000-4111-8111-000000000006",
  gap: "10000000-0000-4111-8111-000000000007",
  page2: "10000000-0000-4111-8111-000000000008",
} as const;

function run(runId: string, n: number, overrides: Partial<MissionRun>): MissionRun {
  return {
    run_id: runId,
    source: "launch",
    task_id: `20000000-0000-4111-8111-00000000000${n}`,
    task_title: `Tâche mission ${n}`,
    task_status: "in_progress",
    machine_id: MACHINE,
    machine_status: "online",
    launch: {
      id: `30000000-0000-4111-8111-00000000000${n}`,
      status: "running",
      reason_code: "none",
      harness_id: "claude-code",
      created_at: ago(3_600_000),
      finished_at: null,
    },
    session: null,
    handoff: null,
    protocol_state: "missing",
    verdict: "running",
    reasons: ["process_running"],
    active_claims: 0,
    data_gaps: [],
    updated_at: ago(60_000 * n),
    ...overrides,
  };
}

function session(n: number, ended: boolean): NonNullable<MissionRun["session"]> {
  return {
    id: `40000000-0000-4111-8111-00000000000${n}`,
    status: ended ? "ended" : "active",
    agent_id: null,
    started_at: ago(3_000_000),
    ended_at: ended ? ago(600_000) : null,
    last_activity_at: ago(600_000),
  };
}

const PAGE1_RUNS: MissionRun[] = [
  run(RUN.running, 1, { session: session(1, false), protocol_state: "open" }),
  run(RUN.waiting, 2, {
    session: session(2, false),
    protocol_state: "open",
    verdict: "waiting_human",
    reasons: ["review_requested", "process_running"],
  }),
  run(RUN.attention, 3, {
    launch: {
      id: "30000000-0000-4111-8111-000000000003",
      status: "succeeded",
      reason_code: "none",
      harness_id: "claude-code",
      created_at: ago(7_200_000),
      finished_at: ago(3_600_000),
    },
    verdict: "needs_attention",
    reasons: ["process_exited_without_session"],
  }),
  run(RUN.done, 4, {
    launch: {
      id: "30000000-0000-4111-8111-000000000004",
      status: "succeeded",
      reason_code: "none",
      harness_id: "claude-code",
      created_at: ago(7_200_000),
      finished_at: ago(3_600_000),
    },
    session: session(4, true),
    handoff: {
      ai_work_id: "50000000-0000-4111-8111-000000000004",
      status: "completed",
      summary: HANDOFF_SUMMARY,
      completed_at: ago(600_000),
    },
    protocol_state: "handed_off",
    verdict: "done",
    reasons: ["handed_off"],
    task_status: "completed",
  }),
  run(RUN.failed, 5, {
    launch: {
      id: "30000000-0000-4111-8111-000000000005",
      status: "failed",
      reason_code: "harness_exited",
      harness_id: "claude-code",
      created_at: ago(7_200_000),
      finished_at: ago(5_000_000),
    },
    verdict: "failed",
    reasons: ["launch_failed"],
  }),
  // Vocabulaire additif : le client doit tolérer un verdict inconnu.
  run(RUN.unknown, 6, {
    verdict: "future_verdict" as MissionRun["verdict"],
    reasons: ["process_running"],
  }),
  run(RUN.gap, 7, {
    source: "session",
    launch: null,
    session: session(7, false),
    protocol_state: "open",
    machine_status: null,
    verdict: "stale",
    reasons: ["machine_offline"],
    data_gaps: ["machine_unknown"],
  }),
];

const PAGE2_RUNS: MissionRun[] = [
  run(RUN.page2, 8, { task_title: "Tâche de la page deux", session: session(8, false), protocol_state: "open" }),
];

/** Compteurs sur toute la fenêtre : volontairement supérieurs à la page. */
const COUNTS: ProjectMission["counts"] = {
  by_verdict: { running: 12, waiting_human: 7, needs_attention: 9, stale: 3, done: 23, failed: 4, future_verdict: 2 },
  total: 60,
};

function mission(page2: boolean): ProjectMission {
  return {
    project_id: P1,
    generated_at: ago(5_000),
    window_hours: 168,
    runs: page2 ? PAGE2_RUNS : PAGE1_RUNS,
    counts: COUNTS,
    next_cursor: page2 ? null : CURSOR,
    truncated: false,
  };
}

interface MissionOptions {
  /** GET /mission répond 403. */
  denied?: boolean;
  /** Le flux SSE du shell échoue (connexion interrompue). */
  abortStream?: boolean;
}

interface MissionCapture {
  urls: string[];
}

/**
 * Connexion authentifiée avec la base ui16, puis routes spécifiques
 * enregistrées APRÈS : Playwright essaie les handlers du plus récent au plus
 * ancien, donc /mission et le flux SSE priment sur le stub générique.
 */
async function loginMission(page: Page, startHash: string, options: MissionOptions = {}): Promise<MissionCapture> {
  const captured: Captured = newCaptured();
  const capture: MissionCapture = { urls: [] };
  await page.route("**/api/**", apiStub(captured));
  await page.route("**/healthz", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.route(/\/api\/v1\/projects\/[^/]+\/mission(\?|$)/, async (route: Route) => {
    const url = route.request().url();
    capture.urls.push(url);
    if (options.denied === true) {
      return route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: { error_code: "forbidden" } }) });
    }
    const page2 = new URL(url).searchParams.get("cursor") === CURSOR;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(mission(page2)) });
  });
  if (options.abortStream === true) {
    await page.route("**/api/v1/events/stream**", (route) => route.abort("failed"));
  }
  await page.goto(`/${startHash}`);
  await expect(page.locator("#login-form")).toBeVisible({ timeout: 15_000 });
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible({ timeout: 15_000 });
  return capture;
}

const MISSION_HASH = `#/projects/${P1}/mission`;
const runLocator = (page: Page, runId: string) => page.locator(`[data-mission-run="${runId}"]`);

test("onglet : compteurs de fenêtre, verdict par run, résultat du handoff, verdict inconnu toléré", async ({ page }) => {
  const watch = watchErrors(page);
  await loginMission(page, MISSION_HASH);

  const root = page.locator("[data-mission]");
  await expect(root).toBeVisible({ timeout: 15_000 });

  // Compteurs = `counts` (toute la fenêtre), pas le décompte de la page.
  const counts = page.locator("[data-mission-counts]").first();
  await expect(counts).toContainText("23");
  await expect(counts).toContainText("12");
  await expect(counts).toContainText("9");

  // Chaque run porte le verdict serveur tel quel.
  await expect(root.locator("[data-mission-run]")).toHaveCount(PAGE1_RUNS.length);
  for (const item of PAGE1_RUNS) {
    await expect(runLocator(page, item.run_id)).toHaveAttribute("data-verdict", item.verdict);
  }

  // Verdict inconnu : rendu neutre « inconnu », jamais d'erreur.
  await expect(runLocator(page, RUN.unknown)).toContainText(/inconnu/i);

  // Lacune explicite, jamais de valeur fabriquée.
  await expect(runLocator(page, RUN.gap).locator("[data-mission-gap]").first()).toBeAttached();

  // Un clic sur le résumé ouvre le run : lancement → session → résultat.
  const done = runLocator(page, RUN.done);
  await done.locator("summary").first().click();
  await expect(done.locator("[data-mission-result]")).toBeVisible();
  await expect(done.locator("[data-mission-result]")).toContainText(HANDOFF_SUMMARY);

  expectClean(watch);
});

test("vue d'ensemble : section résumée, au plus 3 runs à regarder, lien vers l'onglet", async ({ page }) => {
  const watch = watchErrors(page);
  await loginMission(page, `#/projects/${P1}`);

  const summary = page.locator("[data-mission-summary]");
  await expect(summary).toBeVisible({ timeout: 15_000 });

  const runs = summary.locator("[data-mission-run]");
  await expect(runs.first()).toBeVisible();
  const count = await runs.count();
  expect(count).toBeGreaterThanOrEqual(1);
  expect(count).toBeLessThanOrEqual(3);
  const attention = new Set(["waiting_human", "needs_attention", "stale", "failed"]);
  for (let index = 0; index < count; index += 1) {
    const verdict = await runs.nth(index).getAttribute("data-verdict");
    expect(attention.has(verdict ?? ""), `verdict à regarder attendu, reçu ${verdict}`).toBe(true);
  }

  await expect(summary.locator(`a[href="${MISSION_HASH}"]`).first()).toBeVisible();

  expectClean(watch);
});

test("pagination : le bouton suivant charge la page 2 via ?cursor=", async ({ page }) => {
  const watch = watchErrors(page);
  const capture = await loginMission(page, MISSION_HASH);

  await expect(page.locator("[data-mission]")).toBeVisible({ timeout: 15_000 });
  await expect(runLocator(page, RUN.page2)).toHaveCount(0);

  await page.locator("[data-mission-more]").click();
  await expect(runLocator(page, RUN.page2)).toBeVisible();
  await expect(runLocator(page, RUN.page2)).toHaveAttribute("data-verdict", "running");
  expect(capture.urls.some((url) => new URL(url).searchParams.get("cursor") === CURSOR)).toBe(true);
  // Fin de liste (next_cursor null) : plus de bouton suivant.
  await expect(page.locator("[data-mission-more]")).toHaveCount(0);

  expectClean(watch);
});

test("accès refusé : 403 sur /mission → état dédié, aucun run", async ({ page }) => {
  const watch = watchErrors(page);
  await loginMission(page, MISSION_HASH, { denied: true });

  await expect(page.locator("[data-mission-denied]")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("[data-mission-run]")).toHaveCount(0);

  expectClean(watch);
});

test("temps réel perdu : bandeau lost et bouton Actualiser", async ({ page }) => {
  const watch = watchErrors(page);
  await loginMission(page, MISSION_HASH, { abortStream: true });

  await expect(page.locator("[data-mission]")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('[data-mission-live="lost"]')).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("[data-mission-refresh]").first()).toBeVisible({ timeout: 15_000 });

  // Le flux interrompu journalise des échecs réseau attendus.
  expectClean(watch, [/Failed to load resource/i, /ERR_FAILED/i]);
});

test("lecture seule : aucun UUID visible, aucun bouton de mutation", async ({ page }) => {
  const watch = watchErrors(page);
  await loginMission(page, MISSION_HASH);

  const root = page.locator("[data-mission]");
  await expect(root).toBeVisible({ timeout: 15_000 });
  await expect(root.locator("[data-mission-run]").first()).toBeVisible();

  const visible = await root.innerText();
  expect(visible).not.toMatch(UUID_RE);

  await expect(root.getByRole("button", { name: /lancer|annuler|valider/i })).toHaveCount(0);

  expectClean(watch);
});
