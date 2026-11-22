/**
 * R1-composants : chaque composant du lot 1 sur #/design-system, clair et
 * sombre — zéro violation axe, clavier du sélecteur, capture de référence
 * par composant (jointe au rapport Playwright, donc archivée par la CI).
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const COMPONENTS = ["entity", "avatar", "notice", "pagination", "segmented", "empty", "form", "markdown"] as const;

async function open(page: Page, theme: "light" | "dark"): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const json = (body: unknown): Promise<void> =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) return json({ access_token: "e2e-token", token_type: "bearer" });
    if (url.includes("/api/v1/review-queue")) return json({ items: [] });
    if (url.includes("/api/v1/transfers/consumption")) return json({ used_bytes: 0, remaining_bytes: 0, quota_bytes: 0 });
    return json([]);
  });
  await page.emulateMedia({ colorScheme: theme });
  await page.goto("/#/design-system");
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".ds-page-header h1")).toContainText("Design System");
}

for (const theme of ["light", "dark"] as const) {
  test(`lot 1 — axe et captures (${theme})`, async ({ page }, testInfo) => {
    await open(page, theme);
    for (const name of COMPONENTS) {
      const block = page.locator(`[data-ds-lot1="${name}"]`);
      await expect(block).toBeVisible();
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .include(`[data-ds-lot1="${name}"]`)
        .analyze();
      expect(
        results.violations.map((v) => `${v.id} ${v.nodes.map((n) => n.target.join(" ")).join(",")}`),
        `${name} (${theme})`,
      ).toEqual([]);
      await testInfo.attach(`${name}-${theme}`, { body: await block.screenshot(), contentType: "image/png" });
    }
  });
}

test("lot 1 — sélecteur d'entité au clavier", async ({ page }) => {
  await open(page, "light");
  const trigger = page.locator("#ds-demo-studio-trigger");
  await trigger.focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator("#ds-demo-studio-list")).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(trigger).toContainText("Studio Nord");
  await expect(trigger).toBeFocused();
});
