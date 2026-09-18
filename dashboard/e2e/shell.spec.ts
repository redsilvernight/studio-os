/**
 * UI-2 AppShell browser tests (DEC-0079): sidebar navigation,
 * aria-current, skip-link, mobile drawer (open/Escape/focus restore),
 * no fake search or notifications, internal demo route absent from the
 * nav but reachable, explicit 404, and the async render-race regression
 * (slow overview must never repaint a newer route).
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;

function apiStub(slowReviewQueueMs = 0) {
  return async (route: Route) => {
    const url = route.request().url();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) {
      await json(200, { access_token: "e2e-token", token_type: "bearer" });
      return;
    }
    if (url.includes("/api/v1/review-queue")) {
      if (slowReviewQueueMs > 0) await new Promise((resolve) => setTimeout(resolve, slowReviewQueueMs));
      await json(200, { items: [] });
      return;
    }
    if (url.includes("/api/v1/transfers/consumption")) {
      await json(200, { used_bytes: 0, remaining_bytes: 0, quota_bytes: 0 });
      return;
    }
    if (url.endsWith("/api/v1/machines")) {
      await json(404, { detail: "not found" });
      return;
    }
    await json(200, []);
  };
}

async function login(page: Page, startHash: string, slowReviewQueueMs = 0): Promise<void> {
  await page.route("**/api/**", apiStub(slowReviewQueueMs));
  await page.goto(`/${startHash}`);
  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();
}

test.describe("appshell", () => {
  test("navigates with aria-current and honest labels", async ({ page }) => {
    const cspErrors: string[] = [];
    const pageErrors: Error[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && CSP_RE.test(msg.text())) cspErrors.push(msg.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error));

    await login(page, "#/tasks");
    await expect(page.locator('.app-sidebar a[href="#/tasks"]')).toHaveAttribute("aria-current", "page");
    await expect(page.locator(".app-sidebar")).toContainText("Agents IA");
    await expect(page.locator(".app-sidebar")).toContainText("Bientôt");
    await expect(page.locator(".app-sidebar")).not.toContainText("Design System");
    await expect(page.locator("header.app-topbar")).not.toContainText("Rechercher");

    await page.locator('.app-sidebar a[href="#/projects"]').click();
    await expect(page.locator('.app-sidebar a[href="#/projects"]')).toHaveAttribute("aria-current", "page");
    await expect(page.locator("#view")).toContainText("Projets");

    expect(cspErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
  });

  test("skip-link focuses main content without touching the route (no render race)", async ({
    page,
  }) => {
    const pageErrors: Error[] = [];
    page.on("pageerror", (error) => pageErrors.push(error));

    await login(page, "#/tasks");
    await expect(page.locator("#view")).toContainText("Tâches");
    await expect(page).toHaveURL(/#\/tasks$/);

    // Marque le nœud #view courant : tout render() parasite le remplacerait
    // (staging.replaceWith), donc l'identité du nœud prouve l'absence de rendu.
    await page.evaluate(() => {
      const view = document.getElementById("view");
      if (view === null) throw new Error("#view missing");
      (window as unknown as { __skipLinkView?: Element }).__skipLinkView = view;
    });

    const expectStableSkip = async (): Promise<void> => {
      // Focus sur le contenu principal courant.
      await expect(page.locator("#view")).toBeFocused();
      // Route/hash inchangés : aucune navigation "#view" ne doit avoir lieu.
      await expect(page).toHaveURL(/#\/tasks$/);
      // Aucun render parasite : le nœud #view est toujours le même
      // (tout render() le remplacerait via staging.replaceWith).
      const sameNode = await page.evaluate(
        () =>
          document.getElementById("view") ===
          (window as unknown as { __skipLinkView?: Element }).__skipLinkView,
      );
      expect(sameNode).toBe(true);
      // Le contenu reste celui de la route courante, pas un 404 "#view".
      await expect(page.locator("#view")).toContainText("Tâches");
    };

    // Premier arrêt Tab naturel depuis le chargement : le skip-link.
    await page.keyboard.press("Tab");
    await expect(page.locator(".ds-skip-link")).toBeFocused();
    // Activation clavier : le skip-link intercepte (preventDefault) et
    // déplace le focus sur le contenu principal courant.
    await page.keyboard.press("Enter");
    await expectStableSkip();

    // Stabilité répétée : le point de départ séquentiel restant après #view,
    // les activations suivantes refocalisent le skip-link avant l'appui clavier.
    for (let i = 0; i < 4; i++) {
      await page.locator(".ds-skip-link").focus();
      await page.keyboard.press("Enter");
      await expectStableSkip();
    }
    expect(pageErrors).toEqual([]);
  });

  test("unknown hash shows an explicit 404 with a way home", async ({ page }) => {
    await login(page, "#/nope");
    await expect(page.locator("#view")).toContainText("Page introuvable");
    await page.locator('#view a[href="#/"]').click();
    await expect(page.locator('.app-sidebar a[href="#/"]')).toHaveAttribute("aria-current", "page");
  });

  test("slow overview never repaints a newer route (race regression, DEC-0079 §2)", async ({
    page,
  }) => {
    const pageErrors: Error[] = [];
    page.on("pageerror", (error) => pageErrors.push(error));

    // Overview starts with a slow review-queue; navigate away immediately.
    await page.route("**/api/**", apiStub(1500));
    await page.goto("/#/");
    await expect(page.locator("#login-form")).toBeVisible();
    await page.fill("#login-email", "e2e@example.test");
    await page.fill("#login-password", "e2e-secret");
    await page.locator("#login-form button[type=submit]").click();
    await expect(page.locator(".app-sidebar")).toBeVisible();
    await page.evaluate(() => {
      window.location.hash = "#/machines";
    });
    // Let the stale overview request resolve long after the navigation.
    await page.waitForTimeout(2500);
    await expect(page.locator("#view")).toContainText("Machines");
    await expect(page.locator("#view")).not.toContainText("À examiner");
    expect(pageErrors).toEqual([]);
  });
});

test.describe("appshell drawer", () => {
  test.use({ viewport: { width: 375, height: 700 } });

  test("opens, traps nothing, closes on Escape with focus restored", async ({ page }) => {
    const pageErrors: Error[] = [];
    page.on("pageerror", (error) => pageErrors.push(error));

    await login(page, "#/tasks");
    const menuButton = page.locator("#nav-open");
    await expect(menuButton).toBeVisible();
    await expect(page.locator("#app-sidebar")).not.toHaveClass(/open/);

    await menuButton.click();
    await expect(page.locator("#app-sidebar")).toHaveClass(/open/);
    await expect(menuButton).toHaveAttribute("aria-expanded", "true");
    await expect(page.locator("#app-scrim")).toBeVisible();
    await expect(page.locator('.app-sidebar a[href="#/"]')).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(page.locator("#app-sidebar")).not.toHaveClass(/open/);
    await expect(menuButton).toHaveAttribute("aria-expanded", "false");
    await expect(menuButton).toBeFocused();
    expect(pageErrors).toEqual([]);
  });
});
