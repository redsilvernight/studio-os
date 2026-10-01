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

interface Captured {
  idempotencyKeys: (string | null)[];
  bodies: unknown[];
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
    if (method === "POST" && url.includes("/task-launches")) {
      captured.idempotencyKeys.push(req.headers()["idempotency-key"] ?? null);
      captured.bodies.push(req.postDataJSON());
      return json(201, {
        id: "l-new",
        project_id: P1,
        task_id: TASK_ID,
        machine_id: "m-ok",
        requested_by_user_id: "u-e2e",
        harness_id: "claude-code",
        agent_stable_key: "review-helper",
        status: "requested",
        reason_code: "none",
        session_id: null,
        output_excerpt: null,
        created_at: "2026-10-01T10:00:00Z",
        updated_at: "2026-10-01T10:00:00Z",
        expires_at: "2026-10-01T10:15:00Z",
        version: 1,
        finished_at: null,
      });
    }
    if (url.includes("/task-launches")) return json(200, { items: [], limit: 100, offset: 0, total: 0 });
    if (method === "POST" && url.includes("/api/v1/resolutions")) return json(200, RESOLVED);
    if (url.includes("/api/v1/sessions")) return json(200, []);
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
  const captured: Captured = { idempotencyKeys: [], bodies: [] };
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
  const captured: Captured = { idempotencyKeys: [], bodies: [] };
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
