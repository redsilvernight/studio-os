/**
 * P11 — l'assistant de configuration reste une fonction Desktop : en web, la
 * route #/bienvenue explique que la configuration locale vit dans
 * l'application, sans jamais toucher au pont local, au sélecteur de dossier
 * ou au démon.
 */
import { expect, test } from "@playwright/test";
import { go, login, newCaptured, watchErrors, expectClean } from "./support/ui16-stub";

test("P11 web: #/bienvenue stays standalone, no local surface", async ({ page }) => {
  const captured = newCaptured();
  const watch = watchErrors(page);
  await login(page, "#/", captured);
  await go(page, "#/bienvenue");
  const guard = page.locator('[data-testid="onboarding-web"]');
  await expect(guard).toBeVisible();
  await expect(guard).toContainText("Studi'OS Desktop");
  // No local picker, no folder form, no daemon call surface.
  await expect(page.locator("#workspace-id-input")).toHaveCount(0);
  await expect(page.locator('[data-testid="workspace-form"]')).toHaveCount(0);
  await expect(page.locator('[data-testid="onboarding-step"]')).toHaveCount(0);
  expectClean(watch);
});

test("P11 web: unknown onboarding sub-routes stay explicit 404s", async ({ page }) => {
  const captured = newCaptured();
  const watch = watchErrors(page);
  await login(page, "#/", captured);
  await go(page, "#/bienvenue/extra");
  await expect(page.locator("#view")).toContainText("Page introuvable");
  expectClean(watch);
});
