/**
 * P9 — Settings › Intégrations IA.
 *
 * Web mode (no Tauri shell): the page only says this is a Desktop feature.
 * Desktop mode: a mocked Tauri `invoke` plays the local bridge; every answer
 * goes through the Dashboard's real validation (`buildRequest`/`parseAnswer`).
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const WS = "11111111-2222-4333-8444-555555555555";
const CSP_RE = /content security policy|securitypolicyviolation/i;

async function apiStub(route: Route): Promise<void> {
  const url = route.request().url();
  const json = (status: number, body: unknown): Promise<void> =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  if (url.endsWith("/api/v1/auth/token")) return json(200, { access_token: "e2e-token", token_type: "bearer" });
  if (url.includes("/api/v1/review-queue")) return json(200, { items: [] });
  if (url.includes("/api/v1/transfers/consumption")) return json(200, { used_bytes: 0, remaining_bytes: 0, quota_bytes: 0 });
  if (url.endsWith("/api/v1/machines")) return json(404, { detail: "not found" });
  return json(200, []);
}

async function login(page: Page, hash: string): Promise<void> {
  await page.route("**/api/**", apiStub);
  await page.goto(`/${hash}`);
  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();
}

/** A local bridge in the page: the harness commands only, with a small state machine. */
async function installDesktop(page: Page, options: { rollbackConflict?: boolean } = {}): Promise<void> {
  await page.addInitScript(
    ({ ws, rollbackConflict }) => {
      const states: Record<string, string> = { "claude-code": "detected", opencode: "not_detected" };
      const log: string[] = [];
      (window as unknown as { __harnessLog: string[] }).__harnessLog = log;
      const status = (id: string) => ({
        adapter_id: id,
        harness_id: id,
        display_name: id === "claude-code" ? "Claude Code" : "OpenCode",
        state: states[id],
        detected_version: states[id] === "not_detected" ? null : "2.1.272",
        managed_files: states[id] === "configured" ? [".mcp.json"] : [],
        capabilities: [],
      });
      const error = (req: { message_id: string; correlation_id: string }, code: string, reason: string) => ({
        kind: "error",
        protocol: "studio.local/v1",
        message_id: "daemon-error",
        request_id: req.message_id,
        correlation_id: req.correlation_id,
        sent_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
        error: { code, component: "harness", message: "refused", retryable: false, correlation_id: null, details: { reason } },
      });
      const invoke = async (name: string, args?: { request?: { command: string; message_id: string; correlation_id: string; payload: Record<string, string> } }) => {
        if (name === "desktop_info") {
          return { product: "Studi'OS Desktop", desktop_version: "0.1.0", mode: "desktop", protocol: "studio.local/v1", sidecar: { state: "not_started" } };
        }
        if (name === "get_server_origin") return { configured: location.origin, applied: location.origin, restart_required: false };
        if (name !== "bridge_request" || !args?.request) throw new Error("unexpected " + name);
        const req = args.request;
        log.push(req.command);
        const answer = (payload: unknown) => ({
          kind: "response",
          protocol: "studio.local/v1",
          message_id: "daemon-" + log.length,
          request_id: req.message_id,
          correlation_id: req.correlation_id,
          sent_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
          command: req.command,
          payload,
        });
        if (req.command === "harness.detect") return answer({ harnesses: Object.keys(states).map(status) });
        if (req.command === "harness.preview") {
          return answer({
            plan_id: "plan-e2e",
            plan_hash: "a".repeat(64),
            workspace_id: ws,
            adapter_id: req.payload["adapter_id"],
            created_at: "2026-09-22T10:00:00Z",
            expires_at: "2026-09-22T10:10:00Z",
            changes: [{ change_id: "c1", kind: "create", target: ".mcp.json", summary: "Ajoute le serveur studio-os" }],
            requires_confirmation: true,
          });
        }
        if (req.command === "harness.apply") {
          states["claude-code"] = "configured";
          return answer({ plan_id: "plan-e2e", state: "configured", applied: ["c1"], rollback_id: "rb-" + "a".repeat(32) });
        }
        if (req.command === "harness.rollback") {
          if (rollbackConflict) return error(req, "invalid_request", "rollback_conflict");
          states["claude-code"] = "detected";
          return answer({ rollback_id: "rb-" + "a".repeat(32), state: "detected", restored: [".mcp.json"] });
        }
        return error(req, "not_supported", "unsupported");
      };
      (window as unknown as { __TAURI__: unknown }).__TAURI__ = { core: { invoke } };
    },
    { ws: WS, rollbackConflict: options.rollbackConflict ?? false },
  );
}

const harnessCalls = (page: Page): Promise<string[]> =>
  page.evaluate(() => (window as unknown as { __harnessLog: string[] }).__harnessLog.filter((c) => c.startsWith("harness.")));

test.describe("integrations (web)", () => {
  test("states this is a Studi'OS Desktop feature, with no error and no bridge", async ({ page }) => {
    const cspErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && CSP_RE.test(msg.text())) cspErrors.push(msg.text());
    });
    await login(page, "#/configuration/integrations");
    await expect(page.getByTestId("integrations-web")).toContainText("Fonction de Studi'OS Desktop");
    await expect(page.locator("[data-harness]")).toHaveCount(0);
    await expect(page.locator("main [role=alert]")).toHaveCount(0);
    await expect(page.locator('a.tab[aria-current="page"]')).toHaveText("Intégrations IA");
    expect(cspErrors).toEqual([]);
  });
});

test.describe("integrations (Desktop)", () => {
  test("preview, apply, then restore — nothing is shown applied before it succeeded", async ({ page }) => {
    await installDesktop(page);
    await login(page, `#/configuration/integrations/${WS}`);
    const claude = page.locator('[data-harness="claude-code"]');
    await expect(claude).toContainText("Installé · non configuré");
    await expect(claude).toContainText("2.1.272");
    await expect(page.locator('[data-harness="opencode"]')).toContainText("Non installé");

    await claude.locator("[data-action=preview]").click();
    await expect(page.getByTestId("plan")).toContainText("Création");
    await expect(page.getByTestId("plan")).toContainText(".mcp.json");
    expect(await harnessCalls(page)).not.toContain("harness.apply");
    await expect(page.getByTestId("notice")).toHaveCount(0);

    await page.locator("[data-action=apply-plan]").click();
    await expect(page.getByTestId("notice")).toContainText("Configuration appliquée");
    await expect(claude).toContainText("Configuré");
    await expect(claude.locator("[data-action=preview]")).toHaveText("Reconfigurer");

    await claude.locator("[data-action=restore]").click();
    await expect(page.getByTestId("restore-confirm")).toBeVisible();
    await page.locator("[data-action=confirm-restore]").click();
    await expect(page.getByTestId("notice")).toContainText("restaurée");
    await expect(claude).toContainText("Installé · non configuré");
    expect(await harnessCalls(page)).toEqual(expect.arrayContaining(["harness.preview", "harness.apply", "harness.rollback"]));
  });

  test("a rollback conflict is reported and nothing is claimed restored", async ({ page }) => {
    await installDesktop(page, { rollbackConflict: true });
    await login(page, `#/configuration/integrations/${WS}`);
    const claude = page.locator('[data-harness="claude-code"]');
    await claude.locator("[data-action=preview]").click();
    await page.locator("[data-action=apply-plan]").click();
    await expect(claude).toContainText("Configuré");
    await claude.locator("[data-action=restore]").click();
    await page.locator("[data-action=confirm-restore]").click();
    await expect(page.getByTestId("error")).toContainText("restauration est refusée");
    await expect(page.getByTestId("notice")).toHaveCount(0);
    await expect(claude).toContainText("Configuré");
  });

  test("asks for a workspace id when none is in the route", async ({ page }) => {
    await installDesktop(page);
    await login(page, "#/configuration/integrations");
    await expect(page.getByTestId("workspace-form")).toBeVisible();
    await page.fill("#workspace-id-input", WS);
    await page.locator("[data-testid=workspace-form] button[type=submit]").click();
    await expect(page.locator('[data-harness="claude-code"]')).toBeVisible();
  });
});
