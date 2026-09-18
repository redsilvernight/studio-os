/**
 * UI-1 Design System browser test (DEC-0078): the internal
 * `#/design-system` route renders every primitive family, keyboard
 * contracts hold (skip-link, tabs arrows, dialog Escape + focus
 * return, toast live region), with zero CSP violations and zero
 * page errors.
 */
import { expect, test } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;

test("design-system primitives render and behave (keyboard + live region)", async ({ page }) => {
  const cspErrors: string[] = [];
  const pageErrors: Error[] = [];

  page.on("console", (msg) => {
    if (msg.type() === "error" && CSP_RE.test(msg.text())) cspErrors.push(msg.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error));

  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.endsWith("/api/v1/auth/token")) {
      await json(200, { access_token: "e2e-token", token_type: "bearer" });
      return;
    }
    // Same shapes as e2e/csp.spec.ts: the shell first renders the
    // dashboard (review-queue expects {items}, transfers expects an
    // object) before the hash switches to #/design-system.
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

  // Start directly on the internal hash: after login the shell renders
  // this route immediately, so the dashboard overview (async) never
  // paints over the demo mid-test (pre-existing shell race, all routes).
  await page.goto("/#/design-system");
  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("nav.nav")).toBeVisible();

  // The demo route is internal: no nav entry, direct hash only.
  await expect(page.locator("nav.nav")).not.toContainText("Design System");
  await expect(page.locator(".ds-page-header h1")).toContainText("Design System");
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");

  // Skip-link: first Tab stop, revealed on focus.
  await page.keyboard.press("Tab");
  const skip = page.locator(".ds-skip-link:focus-visible, .ds-skip-link:focus");
  await expect(skip).toBeFocused();

  // Tabs: click + arrow-key navigation.
  const boardTab = page.getByRole("tab", { name: "Tableau" });
  await boardTab.click();
  await expect(page.locator("#ds-demo-panel-board")).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Calendrier" })).toBeFocused();
  await expect(page.locator("#ds-demo-panel-calendrier")).toBeVisible();

  // Modal: open, Escape closes, focus returns to the trigger.
  const openModal = page.locator("#ds-open-modal");
  await openModal.click();
  await expect(page.locator("#ds-demo-modal")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#ds-demo-modal")).toBeHidden();
  await expect(openModal).toBeFocused();

  // Drawer: open then close via its action button.
  await page.locator("#ds-open-drawer").click();
  await expect(page.locator("#ds-demo-drawer")).toBeVisible();
  await page.locator("#ds-demo-drawer [data-ds-close]").click();
  await expect(page.locator("#ds-demo-drawer")).toBeHidden();

  // Toast: announced in the shell live region, dismissible.
  await page.locator("#ds-toast-success").click();
  const toast = page.locator('#ds-toast-region .ds-toast:has-text("La tâche a été créée.")');
  await expect(toast).toBeVisible();
  await expect(page.locator("#ds-toast-region")).toHaveAttribute("aria-live", "polite");
  await toast.getByRole("button", { name: "Fermer la notification" }).click();
  await expect(toast).toBeHidden();

  expect(cspErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
