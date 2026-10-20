import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function openSkills(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const body = url.endsWith("/auth/token") ? { access_token: "e2e-token", token_type: "bearer" }
      : url.includes("/review-queue") ? { items: [] } : [];
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route("**/healthz", (route) => route.fulfill({ status: 200, contentType: "application/json", body: '{"status":"ok"}' }));
  await page.addInitScript(() => {
    localStorage.setItem("studio-os.onboarding.v1", JSON.stringify({ schema: 1, status: "completed", current: "termine" }));
    const calls: { command: string; payload: unknown }[] = [];
    (window as unknown as { skillsCalls: typeof calls }).skillsCalls = calls;
    let applied = false;
    const invoke = async (name: string, args?: { request?: { command: string; message_id: string; correlation_id: string; payload: unknown } }) => {
      if (name === "desktop_info") return { product: "Studi'OS Desktop", desktop_version: "0.1.0", mode: "desktop", protocol: "studio.local/v1", sidecar: { state: "not_started" } };
      if (name === "get_server_origin") return { configured: location.origin, applied: location.origin, restart_required: false };
      const req = args?.request;
      if (!req) throw new Error("Unexpected desktop command");
      calls.push({ command: req.command, payload: req.payload });
      const envelope = { protocol: "studio.local/v1", message_id: `daemon-${calls.length}`, request_id: req.message_id, correlation_id: req.correlation_id, sent_at: new Date().toISOString() };
      const answer = (payload: unknown) => ({ ...envelope, kind: "response", command: req.command, payload });
      if (req.command === "skills.status") return answer({ state: "conflicts", last_check: "2026-10-12T05:41:10Z", last_successful_sync: null, conflicts: applied ? [".agents/skills/graphify/SKILL.md"] : [".agents/skills/delegate/SKILL.md", ".agents/skills/graphify/SKILL.md"], auto_sync_enabled: true });
      if (req.command === "skills.preview") return answer({
        skills: ["delegate", "graphify"].map((stable_key, index) => ({
          stable_key, version: 3, preview_hash: String(index + 1).repeat(64),
          targets: [{ harness: "agents", state: applied && index === 0 ? "current" : "locally_modified" }, { harness: "assistant", state: "current" }],
          diff: `--- .agents/skills/${stable_key}/SKILL.md\n+++ Library\n@@ -1 +1 @@\n- description: Mes instructions locales\n+ description: Instructions partagées`,
        })), current: applied ? 3 : 2, missing: 0, outdated: 0, locally_modified: applied ? 1 : 2,
        diff: "", checked_at: "2026-10-12T05:41:10Z",
      });
      if (req.command === "skills.apply") {
        applied = true;
        return answer({ written: [".agents/skills/delegate/SKILL.md"], backups: ["backup/delegate/SKILL.md"], manifest_path: "manifest.json", updated: [".agents/skills/delegate/SKILL.md"], conflicts: [".agents/skills/graphify/SKILL.md"], applied_at: new Date().toISOString() });
      }
      return { ...envelope, kind: "error", error: { code: "not_supported", component: "daemon", message: "Unsupported test command", retryable: false, details: {} } };
    };
    (window as unknown as { __TAURI__: unknown }).__TAURI__ = { core: { invoke } };
  });
  await page.goto("/#/design-system");
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await page.getByTestId("skills-sync").click();
  await expect(page.locator('[data-skills-choice="skill:delegate"]')).toBeVisible();
}

test("skills choices are targeted, accessible and preserve dialog focus", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await openSkills(page);
  const dialog = page.getByRole("dialog", { name: "Synchronisation des skills" });
  await expect(dialog.locator("h2")).toBeFocused();
  await expect(page.locator("[data-skills-notice]")).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Appliquer les choix" })).toBeDisabled();
  const diff = dialog.locator('[data-skill="skill:delegate"] details');
  await expect(diff).not.toHaveAttribute("open");
  await diff.locator("summary").click();
  await expect(diff.locator("pre")).toContainText("Mes instructions locales");
  await expect(dialog.getByRole("button", { name: "Confirmer le remplacement" })).toHaveCount(0);
  const scan = await new AxeBuilder({ page }).include("#skills-sync-dialog").analyze();
  expect(scan.violations).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("skills-sync-desktop.png") });
  await dialog.getByLabel("Version à utiliser pour Skill delegate").selectOption("library");
  await dialog.getByRole("button", { name: "Appliquer 1 choix" }).click();
  await expect(dialog.getByRole("button", { name: "Confirmer le remplacement" })).toBeFocused();
  await expect(dialog.locator(".skills-sync-confirmation")).toContainText(".agents/skills/delegate/SKILL.md");
  await expect(dialog.locator(".skills-sync-confirmation")).not.toContainText("graphify");
  await expect(dialog.locator(".skills-sync-confirmation")).not.toContainText(".claude/skills/delegate/SKILL.md");
  await dialog.getByRole("button", { name: "Confirmer le remplacement" }).click();
  await expect(dialog.locator('[data-skill="skill:delegate"]')).toHaveCount(0);
  await expect(dialog.locator('[data-skill="skill:graphify"]')).toBeVisible();
  const applyCalls = await page.evaluate(() => (window as unknown as { skillsCalls: { command: string; payload: unknown }[] }).skillsCalls.filter((call) => call.command === "skills.apply"));
  expect(applyCalls).toEqual([{ command: "skills.apply", payload: { confirm: true, resolutions: [{ stable_key: "delegate", choice: "library", preview_hash: "1".repeat(64) }] } }]);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId("skills-sync")).toBeFocused();
  expect(errors).toEqual([]);
});

test("skills dialog reflows at mobile width with visible footer actions", async ({ page }, testInfo) => {
  await openSkills(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const dialog = page.getByRole("dialog", { name: "Synchronisation des skills" });
  await expect(dialog.getByLabel("Version à utiliser pour Skill delegate")).toBeVisible();
  await dialog.getByLabel("Version à utiliser pour Skill delegate").selectOption("local");
  const apply = dialog.getByRole("button", { name: "Appliquer 1 choix" });
  await expect(apply).toBeInViewport();
  const bounds = await dialog.boundingBox();
  expect(bounds?.width).toBeLessThanOrEqual(390);
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  const scan = await new AxeBuilder({ page }).include("#skills-sync-dialog").analyze();
  expect(scan.violations).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("skills-sync-mobile.png") });
});
