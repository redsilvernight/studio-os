/**
 * P13 — browser end-to-end acceptance of the dashboard (Library,
 * Configuration, Resolution Inspector) built in P12.
 *
 * The dashboard is a pure client of the canonical P7 HTTP surface: these
 * tests boot the real production bundle under `vite preview`, stub the API,
 * and assert the *rendered* product — not just a 200. The central property is
 * server authority: whatever `POST /resolutions` returns is what is displayed,
 * including a winner a naive frontend resolver would not have chosen.
 */
import { expect, test, type Page } from "@playwright/test";

const RUNTIME_ID = "11111111-1111-1111-1111-111111111111";
const AGENT_ID = "22222222-2222-2222-2222-222222222222";
const RULE_ID = "33333333-3333-3333-3333-333333333333";

const LIBRARY_RESOURCES = [
  {
    id: AGENT_ID,
    kind: "agent_definition",
    stable_key: "review-agent",
    scope: "studio",
    status: "active",
    active_version: 1,
    owner_user_id: null,
    project_id: null,
    created_by_user_id: null,
    version: 2,
    created_at: "2026-09-17T10:00:00Z",
    updated_at: "2026-09-17T10:00:00Z",
  },
  {
    id: RULE_ID,
    kind: "rule",
    stable_key: "coding-standard",
    scope: "studio",
    status: "active",
    active_version: 2,
    owner_user_id: null,
    project_id: null,
    created_by_user_id: null,
    version: 3,
    created_at: "2026-09-17T10:00:00Z",
    updated_at: "2026-09-17T10:00:00Z",
  },
];

const LIBRARY_VERSIONS = [
  {
    id: "44444444-4444-4444-4444-444444444444",
    resource_id: RULE_ID,
    version: 1,
    title: "Coding standard v1",
    description: null,
    content: { content_schema: "studio.library.rule/v1", text: "Always verify." },
    dependencies: [],
    created_by_user_id: null,
    created_at: "2026-09-17T10:00:00Z",
  },
  {
    id: "55555555-5555-5555-5555-555555555555",
    resource_id: RULE_ID,
    version: 2,
    title: "Coding standard v2",
    description: null,
    content: { content_schema: "studio.library.rule/v1", text: "Always verify twice." },
    dependencies: [],
    created_by_user_id: null,
    created_at: "2026-09-17T10:00:00Z",
  },
];

const RUNTIMES = [
  {
    id: RUNTIME_ID,
    owner_user_id: "66666666-6666-6666-6666-666666666666",
    machine_id: null,
    harness_ref: "harness_a",
    provider_ref: "provider_a",
    model_ref: "model_a",
    capabilities: { coding: true },
    capability_source: "declared",
    runtime_metadata: {},
    status: "active",
    version: 1,
    created_at: "2026-09-17T10:00:00Z",
    updated_at: "2026-09-17T10:00:00Z",
  },
];

const BINDINGS = [
  {
    id: "77777777-7777-7777-7777-777777777777",
    level: "user",
    owner_user_id: "66666666-6666-6666-6666-666666666666",
    project_id: null,
    target_kind: "agent_definition",
    target_stable_key: "review-agent",
    target: { runtime_id: RUNTIME_ID },
    created_at: "2026-09-17T10:00:00Z",
  },
];

function resolvedAgent(level: string, source: string) {
  return {
    agent: {
      resource_id: AGENT_ID,
      kind: "agent_definition",
      stable_key: "review-agent",
      scope: "studio",
      version: 1,
      version_origin: "active",
      deprecated: false,
      title: "Review agent",
      content: { content_schema: "studio.library.agent_definition/v1", summary: "Reviews" },
      provenance: {
        source: "active_pointer",
        resource_id: AGENT_ID,
        stable_key: "review-agent",
        scope: "studio",
        version: 1,
        version_origin: "active",
        locked: false,
        relation: null,
        binding_level: null,
        via: null,
      },
    },
    rules: [
      {
        resource_id: RULE_ID,
        stable_key: "coding-standard",
        scope: "studio",
        version: 2,
        version_origin: "active",
        deprecated: false,
        title: "Coding standard",
        content: { content_schema: "studio.library.rule/v1", text: "Always verify." },
        paths: [
          {
            relation: "applies_rule",
            via_kind: "agent_definition",
            via_resource_id: AGENT_ID,
            via_stable_key: "review-agent",
            via_version: 1,
          },
        ],
      },
    ],
    skills: [],
    model_profile: null,
    requirements: {},
    composed_agents: [],
    workflows: [],
    runtime: {
      target: {
        runtime_id: RUNTIME_ID,
        machine_id: null,
        harness_ref: "harness_a",
        provider_ref: "provider_a",
        model_ref: "model_a",
        capabilities: { coding: true },
      },
      level,
      matched_kind: "agent_definition",
      matched_stable_key: "review-agent",
      compatible: true,
      unsatisfied: [],
      provenance: {
        source,
        resource_id: null,
        stable_key: null,
        scope: null,
        version: null,
        version_origin: null,
        locked: false,
        relation: null,
        binding_level: level,
        via: "agent_definition:review-agent",
      },
    },
  };
}

interface StubOptions {
  resolution?: { status: number; body: unknown };
  captured?: { body?: unknown };
  capturedLibrary?: { body?: unknown };
  capturedBinding?: { body?: unknown };
}

async function stubApi(page: Page, options: StubOptions = {}): Promise<void> {
  await page.route("**/healthz", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = request.url();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (url.endsWith("/api/v1/auth/token")) {
      await json(200, { access_token: "e2e-token", token_type: "bearer" });
      return;
    }
    if (url.includes("/api/v1/resolutions")) {
      if (options.captured !== undefined) {
        options.captured.body = request.postDataJSON();
      }
      const resolution = options.resolution ?? {
        status: 200,
        body: resolvedAgent("user", "runtime_binding"),
      };
      await json(resolution.status, resolution.body);
      return;
    }
    if (url.includes("/api/v1/library-locks")) {
      await json(200, []);
      return;
    }
    if (url.includes("/api/v1/library") && request.method() === "POST") {
      if (options.capturedLibrary !== undefined) {
        options.capturedLibrary.body = request.postDataJSON();
      }
      const body = request.postDataJSON() as { kind?: string; stable_key?: string };
      await json(201, {
        ...LIBRARY_RESOURCES[0],
        id: "99999999-9999-9999-9999-999999999999",
        kind: body.kind ?? "rule",
        stable_key: body.stable_key ?? "new-resource",
      });
      return;
    }
    if (url.includes("/api/v1/runtime-bindings") && request.method() === "POST") {
      if (options.capturedBinding !== undefined) {
        options.capturedBinding.body = request.postDataJSON();
      }
      await json(201, BINDINGS[0]);
      return;
    }
    if (url.includes("/api/v1/library/") && url.includes("/versions")) {
      await json(200, LIBRARY_VERSIONS);
      return;
    }
    if (url.match(/\/api\/v1\/library\/[^/?]+$/)) {
      const id = url.split("/").pop();
      await json(200, LIBRARY_RESOURCES.find((r) => r.id === id) ?? LIBRARY_RESOURCES[0]);
      return;
    }
    if (url.includes("/api/v1/library")) {
      await json(200, LIBRARY_RESOURCES);
      return;
    }
    if (url.includes("/api/v1/runtime-bindings")) {
      await json(200, BINDINGS);
      return;
    }
    if (url.includes("/api/v1/runtimes")) {
      await json(200, RUNTIMES);
      return;
    }
    if (url.includes("/api/v1/review-queue")) {
      await json(200, { items: [] });
      return;
    }
    if (url.includes("/api/v1/transfers/consumption")) {
      await json(200, { used_bytes: 0, remaining_bytes: 0, quota_bytes: 0 });
      return;
    }
    await json(200, []);
  });
}

async function bootAuthedDashboard(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();
  await page.waitForLoadState("networkidle");
}

function watchPageErrors(page: Page): Error[] {
  const errors: Error[] = [];
  page.on("pageerror", (error) => errors.push(error));
  return errors;
}

/** Hash-only navigation: a full `page.goto` would drop the memory-only token. */
async function goHash(page: Page, hash: string): Promise<void> {
  await page.evaluate((value) => {
    window.location.hash = value;
  }, hash);
}

test("library and configuration screens render canonical data", async ({ page }) => {
  const errors = watchPageErrors(page);
  await stubApi(page);
  await bootAuthedDashboard(page);

  await goHash(page, "#/library/rules");
  await expect(page.locator("#view")).toContainText("coding-standard");
  await expect(page.locator("#view")).toContainText("v2");

  await goHash(page, `#/library/rules/${RULE_ID}`);
  await expect(page.locator("#view")).toContainText("Coding standard v2");
  await expect(page.locator("#view")).toContainText("Always verify twice.");

  await goHash(page, "#/configuration/runtimes");
  await expect(page.locator("#view")).toContainText("provider_a");
  await expect(page.locator("#view")).toContainText("harness_a");
  await expect(page.locator("#view")).toContainText("model_a");

  await goHash(page, "#/configuration/bindings");
  await expect(page.locator("#view")).toContainText("review-agent");

  await goHash(page, "#/configuration/project");
  await expect(page.locator("#view")).not.toBeEmpty();

  expect(errors).toEqual([]);
});

test("inspector displays the server's winning level, not a local guess", async ({ page }) => {
  const errors = watchPageErrors(page);
  await stubApi(page, {
    resolution: { status: 200, body: resolvedAgent("project_override", "runtime_binding") },
  });
  await bootAuthedDashboard(page);

  await goHash(page, "#/inspector/review-agent");
  const result = page.locator("[data-result]");
  await expect(result).toContainText("review-agent");
  await expect(result).toContainText("project override");
  await expect(result).toContainText("Provider :");
  await expect(result).toContainText("provider_a");
  await expect(result).toContainText("Model :");
  await expect(result).toContainText("model_a");
  await expect(result).toContainText("Quel binding a gagné");
  await expect(result).toContainText("project override");

  expect(errors).toEqual([]);
});

test("inspector session override wins, is sent ephemerally and does not persist", async ({
  page,
}) => {
  const errors = watchPageErrors(page);
  const captured: { body?: unknown } = {};
  await stubApi(page, {
    resolution: { status: 200, body: resolvedAgent("session", "session_override") },
    captured,
  });
  await bootAuthedDashboard(page);

  await goHash(page, "#/inspector");
  await page.fill("input[name=stable_key]", "review-agent");
  await page.locator("summary", { hasText: "Remplacement de session éphémère" }).click();
  await page.check("input[name=enable_override]");
  await page.fill("input[name=override_stable_key]", "review-agent");
  await page.fill("input[name=override_model_ref]", "session-model");
  await page.locator("form[data-resolve] button[type=submit]").click();

  await expect(page.locator("[data-result]")).toContainText("session (ephemeral)");
  await expect(page.locator("[data-result]")).toContainText("temporary session override");
  await expect(page.locator("[data-msg]")).toContainText("Résolution terminée");

  const body = captured.body as {
    stable_key?: string;
    session_overrides?: { target_kind: string; target_stable_key: string }[];
  };
  expect(body.stable_key).toBe("review-agent");
  expect(body.session_overrides).toHaveLength(1);
  expect(body.session_overrides?.[0]?.target_kind).toBe("agent_definition");
  expect(body.session_overrides?.[0]?.target_stable_key).toBe("review-agent");

  expect(errors).toEqual([]);
});

test("inspector renders runtime_incompatible with the selected binding and no fallback", async ({
  page,
}) => {
  const errors = watchPageErrors(page);
  await stubApi(page, {
    resolution: {
      status: 422,
      body: {
        detail: {
          error_code: "runtime_incompatible",
          level: "project_override",
          matched_kind: "agent_definition",
          matched_stable_key: "review-agent",
          unsatisfied: ["coding: required"],
        },
      },
    },
  });
  await bootAuthedDashboard(page);

  await goHash(page, "#/inspector/review-agent");
  const failure = page.locator(".ds-notice--danger");
  await expect(failure).toContainText("runtime_incompatible");
  await expect(failure).toContainText("Binding sélectionné : project override");
  await expect(failure).toContainText("Exigences non satisfaites : coding: required");
  await expect(failure).toContainText("Aucun repli automatique");

  expect(errors).toEqual([]);
});

test("inspector masks a 404 without leaking ownership", async ({ page }) => {
  const errors = watchPageErrors(page);
  await stubApi(page, {
    resolution: { status: 404, body: { detail: { error_code: "definition_not_found" } } },
  });
  await bootAuthedDashboard(page);

  await goHash(page, "#/inspector/review-agent");
  const failure = page.locator(".ds-notice--danger");
  await expect(failure).toContainText("Non trouvé");
  await expect(failure).toContainText("ne révèle jamais laquelle");
  await expect(failure).not.toContainText(/\bown/i);

  expect(errors).toEqual([]);
});

test("inspector shows the canonical Compatible verdict with requirements and capabilities", async ({ page }) => {
  const errors = watchPageErrors(page);
  await stubApi(page, { resolution: { status: 200, body: resolvedAgent("project_override", "runtime_binding") } });
  await bootAuthedDashboard(page);

  await goHash(page, "#/inspector/review-agent");
  const result = page.locator("[data-result]");
  await expect(result).toContainText("Exigences (ModelProfile)");
  await expect(result).toContainText("Capacités runtime (déclarées)");
  await expect(result).toContainText("Compatible");

  expect(errors).toEqual([]);
});

test("inspector never shows Compatible when no runtime was selected (unknown != compatible)", async ({ page }) => {
  const errors = watchPageErrors(page);
  const body = { ...resolvedAgent("user", "runtime_binding"), runtime: null };
  await stubApi(page, { resolution: { status: 200, body } });
  await bootAuthedDashboard(page);

  await goHash(page, "#/inspector/review-agent");
  const result = page.locator("[data-result]");
  await expect(result).toContainText("Aucun binding runtime sélectionné");
  await expect(result).toContainText("résultat valide");
  await expect(result).not.toContainText("Compatible");

  expect(errors).toEqual([]);
});

test("inspector deep link from the Library prefills and resolves", async ({ page }) => {
  const errors = watchPageErrors(page);
  await stubApi(page, { resolution: { status: 200, body: resolvedAgent("user", "runtime_binding") } });
  await bootAuthedDashboard(page);

  await goHash(page, `#/library/agent-definitions/${AGENT_ID}`);
  await expect(page.locator("#view")).toContainText("review-agent");
  await page.getByRole("link", { name: "Inspecter la résolution" }).click();

  await expect(page).toHaveURL(/#\/inspector\/review-agent$/);
  await expect(page.locator("input[name=stable_key]")).toHaveValue("review-agent");
  await expect(page.locator("[data-result]")).toContainText("review-agent");

  expect(errors).toEqual([]);
});

test("inspector is keyboard operable and survives back/forward", async ({ page }) => {
  const errors = watchPageErrors(page);
  await stubApi(page, { resolution: { status: 200, body: resolvedAgent("user", "runtime_binding") } });
  await bootAuthedDashboard(page);

  await goHash(page, "#/inspector");
  const input = page.locator("input[name=stable_key]");
  await input.fill("review-agent");
  await input.press("Enter");
  await expect(page.locator("[data-result]")).toContainText("review-agent");

  await goHash(page, `#/inspector/review-agent`);
  await expect(page.locator("[data-result]")).toContainText("review-agent");
  await goHash(page, "#/agents");
  await page.goBack();
  await expect(page).toHaveURL(/#\/inspector\/review-agent$/);
  await expect(page.locator("[data-result]")).toContainText("review-agent");

  expect(errors).toEqual([]);
});

test("inspector mobile 375: stacked layout, no global overflow, raw JSON secondary", async ({ page }) => {
  const errors = watchPageErrors(page);
  await stubApi(page, { resolution: { status: 200, body: resolvedAgent("user", "runtime_binding") } });
  await bootAuthedDashboard(page);
  await page.setViewportSize({ width: 375, height: 720 });

  await goHash(page, "#/inspector/review-agent");
  await expect(page.locator("[data-result]")).toContainText("review-agent");

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);

  const raw = page.locator(".inspector-raw");
  await expect(raw).toBeVisible();
  await expect(raw.locator("pre.code")).toBeHidden();
  await raw.locator("summary").click();
  await expect(raw.locator("pre.code")).toBeVisible();

  expect(errors).toEqual([]);
});

test("inspector never exposes secrets, even in the raw JSON drawer", async ({ page }) => {
  const errors = watchPageErrors(page);
  await stubApi(page, { resolution: { status: 200, body: resolvedAgent("user", "runtime_binding") } });
  await bootAuthedDashboard(page);

  await goHash(page, "#/inspector/review-agent");
  await expect(page.locator("[data-result]")).toContainText("review-agent");
  await page.locator(".inspector-raw summary").click();

  const text = ((await page.locator("[data-result]").textContent()) ?? "").toLowerCase();
  for (const forbidden of ["token", "secret", "password", "authorization", "bearer", "credential", "api_key"]) {
    expect(text).not.toContain(forbidden);
  }

  expect(errors).toEqual([]);
});

test("library creation reads the scope select (D1 regression)", async ({ page }) => {
  const errors = watchPageErrors(page);
  const capturedLibrary: { body?: unknown } = {};
  await stubApi(page, { capturedLibrary });
  await bootAuthedDashboard(page);

  await goHash(page, "#/library/rules");
  await page.locator("#library-new").click();
  await expect(page.locator("form[data-create]")).toBeVisible();
  await page.fill("form[data-create] input[name=stable_key]", "e2e-created-rule");
  await page.selectOption("form[data-create] select[name=scope]", "user");
  await page.fill("form[data-create] input[name=title]", "Created by e2e");
  await page.fill("form[data-create] textarea[name=text]", "Body of the created rule.");
  await page.locator("form[data-create] button[type=submit]").click();

  await expect
    .poll(() => (capturedLibrary.body as { scope?: string } | undefined)?.scope)
    .toBe("user");
  const body = capturedLibrary.body as { stable_key?: string; scope?: string; kind?: string };
  expect(body.stable_key).toBe("e2e-created-rule");
  expect(body.scope).toBe("user");
  expect(body.kind).toBe("rule");

  expect(errors).toEqual([]);
});

test("binding creation reads the level and target_kind selects (D1 regression)", async ({
  page,
}) => {
  const errors = watchPageErrors(page);
  const capturedBinding: { body?: unknown } = {};
  await stubApi(page, { capturedBinding });
  await bootAuthedDashboard(page);

  await goHash(page, "#/configuration/bindings");
  await page.locator("summary", { hasText: "Nouveau binding" }).click();
  await expect(page.locator("form[data-binding-create]")).toBeVisible();
  await page.selectOption("form[data-binding-create] select[name=level]", "project_default");
  await page.fill(
    "form[data-binding-create] input[name=project_id]",
    "88888888-8888-8888-8888-888888888888",
  );
  await page.selectOption(
    "form[data-binding-create] select[name=target_kind]",
    "model_profile",
  );
  await page.fill("form[data-binding-create] input[name=target_stable_key]", "review-profile");
  await page
    .locator("form[data-binding-create] summary", { hasText: "Ou ancres inline" })
    .click();
  await page.fill("form[data-binding-create] input[name=model_ref]", "model_a");
  await page.locator("form[data-binding-create] button[type=submit]").click();

  await expect
    .poll(() => (capturedBinding.body as { level?: string } | undefined)?.level)
    .toBe("project_default");
  const body = capturedBinding.body as {
    level?: string;
    target_kind?: string;
    target_stable_key?: string;
  };
  expect(body.level).toBe("project_default");
  expect(body.target_kind).toBe("model_profile");
  expect(body.target_stable_key).toBe("review-profile");

  expect(errors).toEqual([]);
});
