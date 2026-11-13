/**
 * P62a-ui-3panes — Comparaison trois volets : repli honnête dans le détail
 * (aucune route API de fusion) + volets et aperçu passés à axe au clavier.
 *
 * Les volets affichent des données fournies (ici une fixture miroir du
 * moteur Python `merge_texts`) : aucune route API n'est inventée.
 */
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
          startLine: 4,
          baseStart: 3,
          baseEnd: 4,
          base: "commun\n",
          ours: "commun (moi)\n",
          theirs: "commun (eux)\n",
        },
      ],
    },
  };
}

async function bootDetail(page: Page): Promise<void> {
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

test("détail override périmé : repli de fusion honnête, axe propre", async ({ page }) => {
  await bootDetail(page);
  await expect(page.getByRole("heading", { name: "Comparaison trois volets" })).toBeVisible();
  await expect(page.locator('[data-library-merge="unavailable"]')).toContainText("Comparaison indisponible");
  await expect(page.locator('[data-library-merge="unavailable"]')).toContainText("Aucune route API de fusion");
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).include("main").analyze();
  expect(axe.violations.filter((v) => v.impact === "critical" || v.impact === "serious")).toEqual([]);
});

test("trois volets fournis : Tab dans l'ordre, rôles/labels, axe sans critique/sérieuse", async ({ page }) => {
  // Import dynamique après le global Vite : le builder partagé avec
  // l'appli (même balisage testé que celui affiché en production).
  (globalThis as Record<string, unknown>).__STUDIO_CLIENT_VERSION__ = "e2e-test";
  const { libraryMergeHtml } = await import("../src/views/libraryMerge");
  const html = libraryMergeHtml(mergeFixture());
  await page.setContent(
    `<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>Comparaison</title></head>` +
    `<body><main>${html}</main></body></html>`,
  );
  // Tab : base → ma version → nouveau commun (régions focalisables nommées).
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  const labels: (string | null)[] = [];
  for (let i = 0; i < 3; i++) {
    await page.keyboard.press("Tab");
    labels.push(await page.evaluate(() => (document.activeElement as HTMLElement | null)?.getAttribute("aria-label") ?? null));
  }
  expect(labels[0]).toMatch(/^Base commune/);
  expect(labels[1]).toMatch(/^Ma version/);
  expect(labels[2]).toMatch(/^Nouveau commun/);
  // Rôles et aperçu visibles, sans script exécutable.
  await expect(page.getByRole("region", { name: /^Base commune/ })).toBeVisible();
  await expect(page.getByRole("region", { name: /^Aperçu du résultat/ })).toContainText("ligne deux (moi)");
  await expect(page.getByRole("heading", { name: "Conflit 1 — ligne 4" })).toBeVisible();
  expect(await page.evaluate(() => "mergeExecuted" in window)).toBe(false);
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).include("main").analyze();
  expect(axe.violations.filter((v) => v.impact === "critical" || v.impact === "serious")).toEqual([]);
});
