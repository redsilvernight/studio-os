import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const HOOK_ID = "33333333-3333-4333-8333-333333333333";
const CREATED_ID = "44444444-4444-4444-8444-444444444444";
const SCRIPT = "<script>window.hookExecuted = true</script>";

async function boot(page: Page, conflict = false) {
  const writes: { path: string; body: Record<string, unknown>; key?: string }[] = [];
  const resource = {
    id: HOOK_ID, kind: "hook", stable_key: "before-tool", scope: "studio",
    status: "active", active_version: 1, version: 3,
    owner_user_id: null, project_id: null, created_by_user_id: null,
    created_at: "2026-10-11T10:00:00Z", updated_at: "2026-10-11T10:00:00Z",
  };
  const content = {
    content_schema: "studio.library.hook/v1", event: "pre_tool", mode: "advisory",
    timeout_seconds: 30, matcher: "Read", description: "Vérifie les outils",
    scripts: [{ os: "windows", shell: "pwsh", body: SCRIPT }, { os: "linux", shell: "bash", body: "echo linux" }],
  };
  const versions = [1, 2].map((version) => ({
    id: `55555555-5555-4555-8555-55555555555${version}`,
    resource_id: HOOK_ID, version, title: `Hook outils v${version}`,
    description: null, content, dependencies: [], created_by_user_id: null,
    created_at: "2026-10-11T10:00:00Z",
  }));
  await page.route("**/healthz", (route) => route.fulfill({ status: 200, json: {} }));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (status: number, data: unknown) => route.fulfill({ status, json: data });
    if (path.endsWith("/auth/token")) return json(200, { access_token: "e2e-token", token_type: "bearer" });
    if (path.endsWith("/auth/me")) return json(200, { id: CREATED_ID, email: "e2e@example.test", display_name: "Test", role: "admin", active: true });
    if (request.method() === "POST" && path.startsWith("/api/v1/library")) {
      const body = request.postDataJSON() as Record<string, unknown>;
      writes.push({ path, body, key: request.headers()["idempotency-key"] });
      if (path.endsWith("/activate")) {
        if (conflict) return json(409, { detail: { error_code: "version_conflict", server_version: 4 } });
        resource.active_version = Number(body["version"]);
        resource.version++;
        return json(200, resource);
      }
      if (path.endsWith("/deprecate")) {
        resource.status = "deprecated";
        resource.version++;
        return json(200, resource);
      }
      if (path.endsWith("/versions")) {
        const created = { ...versions[0]!, ...body, version: 3 };
        versions.push(created);
        return json(201, created);
      }
      return json(201, { ...resource, id: CREATED_ID, stable_key: body["stable_key"] });
    }
    if (path === "/api/v1/library") {
      const kind = new URL(request.url()).searchParams.get("kind");
      if (kind === "agent_definition") return json(200, [{ ...resource, id: CREATED_ID, kind, stable_key: "review-agent" }]);
      if (kind === "workflow") return json(200, []);
      return json(200, [resource]);
    }
    if (path === `/api/v1/library/${CREATED_ID}/versions`) return json(200, [{ ...versions[0], dependencies: [{ kind: "hook", stable_key: resource.stable_key, version: 1, relation: "uses_hook" }] }]);
    if (path === `/api/v1/library/${HOOK_ID}/versions`) return json(200, versions);
    if (path === `/api/v1/library/${HOOK_ID}` || path === `/api/v1/library/${CREATED_ID}`) return json(200, resource);
    if (path.endsWith("/review-queue")) return json(200, { items: [] });
    return json(200, []);
  });
  await page.goto("/");
  await page.locator("#login-email").fill("e2e@example.test");
  await page.locator("#login-password").fill("e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();
  await page.evaluate(() => { location.hash = "#/library"; });
  return writes;
}

async function detail(page: Page) {
  await page.getByRole("link", { name: /Hooks/ }).first().click();
  await expect(page).toHaveURL(/#\/library\/hooks$/);
  await expect(page.locator(".library-item")).toContainText("pre_tool");
  await expect(page.locator(".library-item")).toContainText("advisory");
  await page.getByRole("link", { name: "before-tool" }).click();
  await expect(page).toHaveURL(new RegExp(`#/library/hooks/${HOOK_ID}$`));
  await expect(page.getByRole("heading", { name: "Hook outils v1", exact: true })).toBeVisible();
}

test("hooks: liste, scripts inertes, historique, accessibilité et mobile", async ({ page }) => {
  await boot(page);
  await detail(page);
  const reading = page.getByRole("region", { name: "Contenu actuel" });
  await expect(reading).toContainText(SCRIPT);
  await expect(reading).toContainText("echo linux");
  await expect(reading.locator("script")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Historique des versions" })).toContainText("Hook outils v2");
  expect(await page.evaluate(() => "hookExecuted" in window)).toBe(false);
  await page.getByRole("button", { name: "Voir les dépendances entrantes" }).click();
  const dependencies = page.getByRole("region", { name: "Dépendances entrantes", exact: true });
  await expect(dependencies).toContainText("review-agent");
  await expect(dependencies).toContainText("uses_hook");
  expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

test("hooks: activation canonique avec révision et clé d'idempotence", async ({ page }) => {
  const writes = await boot(page);
  await detail(page);
  const form = page.locator("[data-activate]");
  await form.locator("input[name=version]").fill("2");
  await form.getByRole("button", { name: "Activer", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Hook outils v2", exact: true })).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({ path: `/api/v1/library/${HOOK_ID}/activate`, body: { version: 2, expected_resource_version: 3 } });
  expect(writes[0]!.key).toBeTruthy();
  expect(await page.evaluate(() => "hookExecuted" in window)).toBe(false);
});

test("hooks: conflit d'activation visible et version active conservée", async ({ page }) => {
  const writes = await boot(page, true);
  await detail(page);
  const form = page.locator("[data-activate]");
  await form.locator("input[name=version]").fill("2");
  await form.getByRole("button", { name: "Activer", exact: true }).click();
  await expect(form.locator("[data-msg]")).not.toBeEmpty();
  await expect(page.getByRole("heading", { name: "Hook outils v1", exact: true })).toBeVisible();
  expect(writes).toHaveLength(1);
});

test("hooks: création d'une version puis dépréciation", async ({ page }) => {
  const writes = await boot(page);
  await detail(page);
  await page.getByRole("button", { name: "+ Nouvelle version" }).click();
  const dialog = page.getByRole("dialog", { name: "Nouvelle version" });
  await dialog.locator("input[name=version_title]").fill("Hook outils v3");
  await dialog.locator("select[name=event]").selectOption("post_tool");
  await dialog.locator("select[name=mode]").selectOption("advisory");
  await dialog.locator("select[name=hook_script_0_os]").selectOption("windows");
  await dialog.locator("select[name=hook_script_0_shell]").selectOption("pwsh");
  await dialog.locator("textarea[name=hook_script_0_body]").fill("Write-Output 'v3'");
  await dialog.getByRole("button", { name: "Créer la version", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("region", { name: "Historique des versions" })).toContainText("Hook outils v3");
  expect(writes[0]).toMatchObject({ path: `/api/v1/library/${HOOK_ID}/versions`, body: { title: "Hook outils v3", content: { content_schema: "studio.library.hook/v1", event: "post_tool" } } });
  expect(writes[0]!.key).toBeTruthy();
  page.once("dialog", (confirmation) => confirmation.accept());
  await page.locator("[data-deprecate]").getByRole("button", { name: "Déprécier", exact: true }).click();
  await expect(page.locator(".library-badges")).toContainText("Déprécié");
  expect(writes[1]).toMatchObject({ path: `/api/v1/library/${HOOK_ID}/deprecate`, body: { expected_resource_version: 3 } });
  expect(writes[1]!.key).toBeTruthy();
});

test("hooks: formulaire accessible au clavier, ajout, retrait et retour du focus", async ({ page }) => {
  await boot(page);
  await detail(page);
  const trigger = page.getByRole("button", { name: "+ Nouvelle version" });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Nouvelle version" });
  await expect(dialog.locator("input[name=version_title]")).toBeFocused();
  const add = dialog.getByRole("button", { name: "Ajouter un script", exact: true });
  await add.focus();
  await page.keyboard.press("Enter");
  await expect(dialog.locator("textarea[name=hook_script_1_body]")).toBeFocused();
  const remove = dialog.getByRole("button", { name: "Retirer le script 2", exact: true });
  await remove.focus();
  await page.keyboard.press("Enter");
  await expect(add).toBeFocused();
  await expect(dialog.locator("[data-hook-script-index]")).toHaveCount(1);
  for (let i = 0; i < 7; i++) await add.click();
  await expect(add).toBeDisabled();
  await expect(dialog.locator("[data-hook-script-index]")).toHaveCount(8);
  expect((await new AxeBuilder({ page }).include("[role=dialog]").analyze()).violations).toEqual([]);
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await dialog.getByRole("button", { name: "Annuler", exact: true }).focus();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test("hooks: création d'une ressource depuis sa catégorie", async ({ page }) => {
  const writes = await boot(page);
  await page.getByRole("link", { name: /Hooks/ }).first().click();
  await page.getByRole("button", { name: "Créer un élément", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("input[name=stable_key]").fill("after-edit");
  await dialog.locator("input[name=title]").fill("Après édition");
  await dialog.locator("textarea[name=hook_script_0_body]").fill("Write-Output 'edit'");
  await dialog.getByRole("button", { name: "Créer", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({ path: "/api/v1/library", body: { kind: "hook", stable_key: "after-edit", content: { content_schema: "studio.library.hook/v1" } } });
  expect(writes[0]!.key).toBeTruthy();
});
