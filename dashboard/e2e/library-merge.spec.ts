import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import type { LibraryMergeData } from "../src/views/libraryMerge";

const RESOURCE_ID = "11111111-1111-4111-8111-111111111111";

function mergeFixture(): LibraryMergeData {
  return {
    inputs: {
      base: "ligne une\nligne deux\nligne trois\n",
      ours: "ligne une\nligne deux (moi)\nligne trois\n",
      theirs: "ligne une\nligne deux\nligne trois (commun)\n",
    },
    result: {
      content:
        "ligne une\nligne deux (moi)\nligne trois (commun)\n<<<<<<< ours\ncommun (moi)\n=======\ncommun (eux)\n>>>>>>> theirs\n",
      conflicts: [
        {
          start_line: 4,
          base_start: 3,
          base_end: 4,
          base: "commun\n",
          ours: "commun (moi)\n",
          theirs: "commun (eux)\n",
        },
      ],
    },
  };
}

async function bootDetail(page: Page, previewStatus = 200): Promise<void> {
  const resource = {
    id: RESOURCE_ID, kind: "rule", stable_key: "coding-standard", scope: "user",
    status: "active", active_version: 1, version: 2,
    owner_user_id: null, project_id: null, created_by_user_id: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z",
    base_update_available: true, base_active_version: 4,
  };
  const versions = [{
    id: "22222222-2222-4222-8222-222222222222", resource_id: RESOURCE_ID, version: 1,
    title: "Standard v1", description: null,
    content: { content_schema: "studio.library.rule/v1", text: "Règle de test" },
    dependencies: [], created_by_user_id: null, created_at: "2026-01-01T00:00:00Z",
  }];
  await page.route("**/healthz", (route) => route.fulfill({ status: 200, json: {} }));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (status: number, data: unknown) => route.fulfill({ status, json: data });
    if (path.endsWith("/auth/token")) return json(200, { access_token: "e2e-token", token_type: "bearer" });
    if (path.endsWith("/auth/me")) return json(200, { id: "user", email: "e2e@example.test", display_name: "Test", role: "admin", active: true });
    if (path === `/api/v1/library/${RESOURCE_ID}/versions`) return json(200, versions);
    if (path === `/api/v1/library/${RESOURCE_ID}`) return json(200, resource);
    if (path === `/api/v1/library/${RESOURCE_ID}/merge-preview`) {
      return json(previewStatus, previewStatus === 200 ? mergeFixture() : { detail: "library resource not found" });
    }
    if (path === "/api/v1/library") return json(200, [resource]);
    if (path === "/api/v1/library-locks") return json(200, []);
    return json(200, []);
  });
  await page.goto("/");
  await page.locator("#login-email").fill("e2e@example.test");
  await page.locator("#login-password").fill("e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();
  await page.evaluate((hash) => { location.hash = hash; }, `#/library/rules/${RESOURCE_ID}`);
}

test("détail : affiche une erreur si l’aperçu est indisponible", async ({ page }) => {
  await bootDetail(page, 404);
  await expect(page.getByRole("alert").filter({ hasText: "Comparaison indisponible" })).toBeVisible();
});

test("détail : récupère l’aperçu et permet de parcourir les trois volets au clavier", async ({ page }) => {
  await bootDetail(page);
  const base = page.getByRole("region", { name: /^Base commune/ });
  const ours = page.getByRole("region", { name: /^Ma version/ });
  const theirs = page.getByRole("region", { name: /^Nouveau commun/ });
  await expect(base).toContainText("ligne deux");
  await expect(ours).toContainText("ligne deux (moi)");
  await expect(theirs).toContainText("ligne trois (commun)");
  await base.focus();
  await page.keyboard.press("Tab");
  await expect(ours).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(theirs).toBeFocused();
  await expect(page.getByRole("region", { name: /^Aperçu du résultat/ })).toContainText("ligne deux (moi)");
  await expect(page.getByRole("heading", { name: "Conflit 1 — ligne 4" })).toBeVisible();
  await page.getByRole("button", { name: "Voir dans l'aperçu" }).click();
  await expect(page.locator("#library-merge-conflict-1")).toBeFocused();
  await expect(page).toHaveURL(new RegExp(`#/library/rules/${RESOURCE_ID}$`));
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).include("main").analyze();
  expect(axe.violations.filter((v) => v.impact === "critical" || v.impact === "serious")).toEqual([]);
});
