/**
 * AIB R4 — fiche tâche « Lancer sur… » (API stubbée déterministe).
 *
 * Couvre le sélecteur de poste (inéligible non sélectionnable), le sélecteur
 * harnais/agent, l'aperçu de résolution avant lancement et la création d'un
 * TaskLaunch (Idempotency-Key), sans jamais afficher d'état non rapporté.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const P1 = "11111111-2222-4333-8444-555555555555";
const TASK_ID = "aaaaaaaa-0000-4111-8111-000000000002";

const TASK = {
  id: TASK_ID,
  project_id: P1,
  readable_id: "T-002",
  title: "Optimiser les éclairages",
  description: "Revoir les sampler densities.",
  status: "created",
  claimed_by_machine_id: null,
  claimed_by_agent_id: null,
  created_at: "2026-09-10T10:00:00Z",
  updated_at: "2026-09-11T10:00:00Z",
  version: 1,
};

const ELIGIBLE = {
  task_id: TASK_ID,
  project_id: P1,
  harness_id: null,
  machines: [
    {
      machine_id: "m-ok",
      display_name: "flo-laptop",
      status: "online",
      eligible: true,
      reasons: [],
      harnesses: [
        { harness_id: "claude-code", version: "2.1.0", detected: true, configured: true },
        { harness_id: "ghost", version: null, detected: false, configured: false },
      ],
      free_slots: 2,
      reported_at: "2026-09-30T09:00:00Z",
    },
    {
      machine_id: "m-off",
      display_name: "mathieu-desktop",
      status: "offline",
      eligible: false,
      reasons: ["offline"],
      harnesses: [],
      free_slots: 0,
      reported_at: "2026-09-29T09:00:00Z",
    },
  ],
};

const AGENTS = [
  {
    id: "d1",
    kind: "agent_definition",
    stable_key: "review-helper",
    scope: "studio",
    status: "active",
    active_version: 1,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
    version: 1,
  },
];

const RESOLVED = {
  agent: { resource_id: "d1", kind: "agent_definition", stable_key: "review-helper", scope: "studio", version: 1, version_origin: "active", deprecated: false, title: "Aide", content: {}, provenance: {} },
  rules: [{ resource_id: "r1", stable_key: "python-conventions", scope: "studio", version: 1, version_origin: "active", deprecated: false, title: "Python", content: {}, paths: [] }],
  skills: [{ resource_id: "s1", stable_key: "studio-session", scope: "studio", version: 1, version_origin: "active", deprecated: false, title: "Session", content: {} }],
  model_profile: null,
  requirements: { coding: false, tools_required: [], local_compatible: false },
  composed_agents: [],
  workflows: [],
  runtime: null,
};

type Launch = Record<string, unknown>;

interface Captured {
  idempotencyKeys: (string | null)[];
  bodies: unknown[];
  cancelCalls: { launchId: string; body: unknown }[];
  /** Lancement simulé côté serveur : seule source de vérité du suivi. */
  launch: Launch | null;
  cancelConflict: boolean;
  sessionEnded: boolean;
}

function launchFixture(overrides: Launch = {}): Launch {
  return {
    id: "l-existing",
    project_id: P1,
    task_id: TASK_ID,
    machine_id: "m-ok",
    requested_by_user_id: "u-e2e",
    harness_id: "claude-code",
    agent_stable_key: null,
    status: "running",
    reason_code: "none",
    session_id: null,
    output_excerpt: null,
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
    expires_at: "2026-10-01T10:15:00Z",
    version: 3,
    finished_at: null,
    ...overrides,
  };
}

function newCaptured(launch: Launch | null = null): Captured {
  return { idempotencyKeys: [], bodies: [], cancelCalls: [], launch, cancelConflict: false, sessionEnded: false };
}

function apiStub(captured: Captured) {
  return async (route: Route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) return json(200, { access_token: "e2e-token", token_type: "bearer" });
    if (url.endsWith("/api/v1/auth/me")) {
      return json(200, {
        user_id: "u-e2e",
        display_name: "E2E",
        email: "e2e@example.test",
        role: "developer",
        machine_id: "m-ok",
      });
    }
    if (url.includes("/api/v1/tasks/") && url.endsWith("/eligible-machines")) return json(200, ELIGIBLE);
    if (url.includes("/api/v1/library")) return json(200, AGENTS);

    // Annulation (demandeur ou admin), version courante exigée par le serveur.
    if (method === "POST" && /\/task-launches\/[^/]+\/cancel$/.test(url)) {
      const launchId = url.split("/").slice(-2)[0] ?? "";
      captured.cancelCalls.push({ launchId, body: req.postDataJSON() });
      if (captured.cancelConflict) {
        captured.cancelConflict = false;
        return json(409, { detail: { error_code: "version_conflict", server_version: 5 } });
      }
      captured.launch = {
        ...(captured.launch ?? launchFixture()),
        status: "cancelled",
        reason_code: "cancelled_by_requester",
        finished_at: "2026-10-01T10:05:00Z",
        version: 4,
      };
      return json(200, captured.launch);
    }

    // Création : POST /projects/{pid}/task-launches.
    if (method === "POST" && url.includes("/task-launches")) {
      captured.idempotencyKeys.push(req.headers()["idempotency-key"] ?? null);
      captured.bodies.push(req.postDataJSON());
      captured.launch = launchFixture({ id: "l-new", status: "requested", version: 1, agent_stable_key: "review-helper" });
      return json(201, captured.launch);
    }

    // Lecture d'un lancement : GET /task-launches/{id}.
    if (method === "GET" && /\/task-launches\/[^/]+$/.test(url) && !url.includes("/projects/")) {
      if (captured.launch === null) return json(404, { detail: { error_code: "not_found" } });
      return json(200, captured.launch);
    }

    // Liste des lancements d'un projet.
    if (method === "GET" && url.includes("/projects/") && /\/task-launches(\?|$)/.test(url)) {
      return json(200, {
        items: captured.launch === null ? [] : [captured.launch],
        limit: 100,
        offset: 0,
        total: captured.launch === null ? 0 : 1,
      });
    }

    if (method === "POST" && url.includes("/api/v1/resolutions")) return json(200, RESOLVED);
    if (url.includes("/api/v1/sessions")) {
      const sessionId = captured.launch?.session_id;
      return json(
        200,
        typeof sessionId === "string"
          ? [
              {
                id: sessionId,
                machine_id: "m-ok",
                agent_id: null,
                started_at: "2026-10-01T10:00:00Z",
                ended_at: captured.sessionEnded ? "2026-10-01T10:05:00Z" : null,
              },
            ]
          : [],
      );
    }
    if (url.includes("/api/v1/ai-work")) return json(200, []);
    if (url.includes("/api/v1/claims")) return json(200, []);
    if (/\/api\/v1\/tasks\/[^/]+$/.test(url)) return json(200, TASK);
    if (url.includes("/api/v1/tasks")) return json(200, [TASK]);
    if (/\/api\/v1\/projects\/[^/]+\/state$/.test(url)) {
      return json(200, { project_id: P1, active_tasks: [], active_claims: [], generated_at: "2026-09-12T10:00:00Z" });
    }
    if (/\/api\/v1\/projects\/[^/]+$/.test(url)) {
      return json(200, { id: P1, slug: "phare", name: "Jeu Phare", archived: false, created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-10T10:00:00Z", version: 7 });
    }
    return json(200, []);
  };
}

async function openTaskDetail(page: Page, captured: Captured): Promise<void> {
  page.on("dialog", (dialog) => void dialog.accept());
  await page.route("**/api/**", apiStub(captured));
  await page.goto(`/#/tasks/${TASK_ID}`);
  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  // Les automatisations sont repliées par défaut (divulgation progressive) :
  // on ouvre le bloc avant de piloter le panneau.
  await page.locator("#task-mecanique summary").click();
  await expect(page.locator('[data-testid="launch-panel"]')).toBeVisible();
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

test("sélecteur : poste inéligible non sélectionnable, harnais et aperçu pilotés", async ({ page }) => {
  const captured = newCaptured();
  const errors = watchErrors(page);
  await openTaskDetail(page, captured);

  await expect(page.locator('#launch-machine option[value="m-off"]')).toHaveAttribute("disabled", "");
  await expect(page.locator('#launch-machine option[value="m-ok"]')).not.toHaveAttribute("disabled", "");
  await expect(page.locator('#launch-machine option[value="m-off"]')).toContainText("hors ligne");

  await expect(page.locator('[data-action="launch-preview"]')).toBeDisabled();
  await page.selectOption("#launch-machine", "m-ok");
  await expect(page.locator('#launch-harness option[value="ghost"]')).toHaveAttribute("disabled", "");
  await page.selectOption("#launch-harness", "claude-code");
  await page.selectOption("#launch-agent", "review-helper");
  await expect(page.locator('[data-action="launch-preview"]')).toBeEnabled();

  await page.locator('[data-action="launch-preview"]').click();
  await expect(page.locator('[data-testid="launch-preview-list"]')).toContainText("python-conventions");
  await expect(page.locator('[data-testid="launch-preview-list"]')).toContainText("studio-session");

  expect(errors.fatal).toEqual([]);
  expect(errors.csp).toEqual([]);
});

test("lancement : POST typé avec Idempotency-Key, état rapporté affiché", async ({ page }) => {
  const captured = newCaptured();
  const errors = watchErrors(page);
  await openTaskDetail(page, captured);

  await page.selectOption("#launch-machine", "m-ok");
  await page.selectOption("#launch-harness", "claude-code");
  await page.selectOption("#launch-agent", "review-helper");
  await page.locator('[data-action="launch-submit"]').click();

  await expect(page.locator('[data-testid="launch-latest"]')).toContainText("Demandé");
  expect(captured.idempotencyKeys).toHaveLength(1);
  expect(captured.idempotencyKeys[0]).toBeTruthy();
  expect(captured.bodies[0]).toMatchObject({
    task_id: TASK_ID,
    machine_id: "m-ok",
    harness_id: "claude-code",
    agent_stable_key: "review-helper",
  });

  expect(errors.fatal).toEqual([]);
  expect(errors.csp).toEqual([]);
});

test("suivi : l'actualisation relit l'état rapporté par le poste", async ({ page }) => {
  const captured = newCaptured(launchFixture({ status: "running" }));
  const errors = watchErrors(page);
  await openTaskDetail(page, captured);

  await expect(page.locator('[data-testid="launch-latest"]')).toContainText("En cours");
  captured.launch = launchFixture({ status: "succeeded", version: 4, finished_at: "2026-10-01T10:05:00Z" });
  await page.locator('[data-action="launch-refresh"]').click();
  await expect(page.locator('[data-testid="launch-latest"]')).toContainText("Terminé (succès)");

  expect(errors.fatal).toEqual([]);
  expect(errors.csp).toEqual([]);
});

test("annulation : POST versionné, état annulé affiché", async ({ page }) => {
  const captured = newCaptured(launchFixture({ status: "running", version: 3 }));
  const errors = watchErrors(page);
  await openTaskDetail(page, captured);

  await page.locator('[data-action="launch-cancel"]').click();
  await expect(page.locator('[data-testid="launch-latest"]')).toContainText("Annulé");
  expect(captured.cancelCalls).toHaveLength(1);
  expect(captured.cancelCalls[0]?.body).toEqual({ expected_version: 3 });
  await expect(page.locator('[data-action="launch-cancel"]')).toHaveCount(0);

  expect(errors.fatal).toEqual([]);
  expect(errors.csp).toEqual([]);
});

test("conflit de version : relecture et message, aucune réapplication aveugle", async ({ page }) => {
  const captured = newCaptured(launchFixture({ status: "running", version: 3 }));
  captured.cancelConflict = true;
  const errors = watchErrors(page);
  await openTaskDetail(page, captured);

  await page.locator('[data-action="launch-cancel"]').click();
  await expect(page.locator('[data-testid="launch-panel"]')).toContainText("a changé ailleurs");
  expect(captured.cancelCalls).toHaveLength(1);
  await expect(page.locator('[data-testid="launch-latest"]')).toContainText("En cours");

  expect(errors.fatal).toEqual([]);
  expect(errors.csp).toEqual([]);
});

test("session liée : lien vers la session puis vers le handoff une fois terminée", async ({ page }) => {
  const captured = newCaptured(
    launchFixture({ status: "running", session_id: "sess-0000-4111-8111-000000000001" }),
  );
  const errors = watchErrors(page);
  await openTaskDetail(page, captured);

  await expect(page.locator('[data-testid="launch-session-link"]')).toHaveAttribute("href", "#task-sessions");
  await expect(page.locator('[data-testid="launch-session-link"]')).toContainText("en cours");
  await expect(page.locator('[data-testid="launch-handoff-link"]')).toHaveCount(0);

  captured.sessionEnded = true;
  captured.launch = launchFixture({
    status: "succeeded",
    version: 4,
    session_id: "sess-0000-4111-8111-000000000001",
    finished_at: "2026-10-01T10:05:00Z",
  });
  await page.locator('[data-action="launch-refresh"]').click();
  await expect(page.locator('[data-testid="launch-session-link"]')).toContainText("terminée");
  await expect(page.locator('[data-testid="launch-handoff-link"]')).toHaveAttribute("href", "#task-ai-work");

  expect(errors.fatal).toEqual([]);
  expect(errors.csp).toEqual([]);
});

test("divulgation progressive : repli fermé par défaut, ancre interne qui l'ouvre", async ({ page }) => {
  const captured = newCaptured(
    launchFixture({ status: "running", session_id: "sess-0000-4111-8111-000000000001" }),
  );
  const errors = watchErrors(page);
  page.on("dialog", (dialog) => void dialog.accept());
  await page.route("**/api/**", apiStub(captured));
  await page.goto(`/#/tasks/${TASK_ID}`);
  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();

  // À l'arrivée, la mécanique est repliée : pas de panneau, pas d'identifiant.
  const hero = page.locator(".task-detail-hero");
  await expect(hero.locator("h1")).toHaveText(TASK.title);
  await expect(page.locator("#task-mecanique")).not.toHaveAttribute("open", "");
  await expect(page.locator('[data-testid="launch-panel"]')).toBeHidden();
  await expect(hero.locator(".ds-status")).toContainText("À faire");
  await expect(hero.locator(".ds-btn--primary")).toHaveCount(1);

  // Une ancre interne vers un bloc replié l'ouvre et défile : jamais le 404
  // du routeur, qui ne connaît pas les ancres de page.
  await page
    .locator('[data-testid="launch-session-link"]')
    .evaluate((node) => (node as HTMLElement).click());
  await expect(page.locator("#task-mecanique")).toHaveAttribute("open", "");
  await expect(page.locator("#task-sessions")).toBeVisible();
  await expect(page.locator("h1")).toHaveText(TASK.title);
  await expect(page).toHaveURL(new RegExp(`#/tasks/${TASK_ID}$`));

  expect(errors.fatal).toEqual([]);
  expect(errors.csp).toEqual([]);
});
