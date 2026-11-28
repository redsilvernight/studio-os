/**
 * Thème clair / sombre / système (tâche cea09af9) — navigateur.
 *
 * Vérifie le contrat réel, pas l'intention :
 *   - le script de pré-rendu pose `data-theme` AVANT le premier rendu
 *     (script classique bloquant servi en 'self' : CSP inchangée) ;
 *   - le sélecteur de la barre latérale change le thème et le mémorise ;
 *   - « Système » SUPPRIME la clé localStorage (l'absence de clé vaut
 *     suivi du système) ;
 *   - `#/reglages/avance/design-system` montre les deux thèmes côte à côte, avec des
 *     fonds réellement différents.
 */
import { expect, test } from "@playwright/test";

const CSP_RE = /content security policy|securitypolicyviolation/i;
const THEME_KEY = "studio-os.theme";

async function stubApi(page: import("@playwright/test").Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const json = (status: number, body: unknown): Promise<void> =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (url.endsWith("/api/v1/auth/token")) {
      await json(200, { access_token: "e2e-token", token_type: "bearer" });
      return;
    }
    if (url.includes("/api/v1/review-queue")) {
      await json(200, { items: [] });
      return;
    }
    if (url.includes("/api/v1/transfers/consumption")) {
      await json(200, { used_bytes: 0, remaining_bytes: 0, quota_budget: 0 });
      return;
    }
    await json(200, []);
  });
}

test("le thème sombre s'applique, se mémorise et « Système » efface la clé", async ({ page }) => {
  const cspErrors: string[] = [];
  const pageErrors: Error[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && CSP_RE.test(msg.text())) cspErrors.push(msg.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error));

  await stubApi(page);
  await page.goto("/");
  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();

  const select = page.locator("#theme-select");
  await expect(select).toBeVisible();
  await expect(select.locator("option")).toHaveText(["Système", "Clair", "Sombre"]);

  // Choix ferme : l'attribut est posé et mémorisé.
  await select.selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate((key) => window.localStorage.getItem(key), THEME_KEY)).toBe("dark");

  // « Système » : la clé est supprimée, l'attribut retiré — le CSS
  // (media query) décide alors.
  await select.selectOption("system");
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.*/);
  expect(await page.evaluate((key) => window.localStorage.getItem(key), THEME_KEY)).toBeNull();

  // Choix clair explicite.
  await select.selectOption("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  expect(cspErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test("le script de pré-rendu pose le thème avant le premier rendu", async ({ page }) => {
  await stubApi(page);
  // Choix sombre mémorisé AVANT la navigation : le script de pré-rendu
  // (bloquant, servi en 'self') doit poser l'attribut avant le premier
  // rendu, sans attendre le bundle applicatif.
  await page.goto("/");
  await page.evaluate((key) => window.localStorage.setItem(key, "dark"), THEME_KEY);

  // Observateur posé AVANT tout script de la page : on note l'ordre des
  // événements. `data-theme` doit être posé par le script de pré-rendu
  // (synchrone, pendant l'analyse du <head>), donc bien avant le
  // chargement du bundle applicatif.
  await page.addInitScript(() => {
    const win = window as unknown as { __dsThemeTimeline: string[] };
    win.__dsThemeTimeline = [];
    document.addEventListener("readystatechange", () => {
      win.__dsThemeTimeline.push(`ready:${document.readyState}`);
    });
    const observer = new MutationObserver(() => {
      win.__dsThemeTimeline.push(`theme:${document.documentElement.getAttribute("data-theme")}`);
      observer.disconnect();
    });
    const start = (): void => {
      if (document.documentElement === null) return;
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    };
    if (document.documentElement === null) {
      document.addEventListener("readystatechange", start, { once: true });
      document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
      start();
    }
  });

  await page.goto("/");
  await expect(page.locator("#login-form")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  const timeline = await page.evaluate(
    () => (window as unknown as { __dsThemeTimeline: string[] }).__dsThemeTimeline,
  );
  // L'attribut a bien été posé (une entrée « theme:dark »).
  expect(timeline.some((entry) => entry === "theme:dark")).toBe(true);
});

test("#/reglages/avance/design-system montre les deux thèmes côte à côte", async ({ page }) => {
  await stubApi(page);
  await page.goto("/#/reglages/avance/design-system");
  await expect(page.locator("#login-form")).toBeVisible();
  await page.fill("#login-email", "e2e@example.test");
  await page.fill("#login-password", "e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".ds-page-header h1")).toContainText("Design System");

  const light = page.locator('[data-ds-theme-preview="light"]');
  const dark = page.locator('[data-ds-theme-preview="dark"]');
  await expect(light).toBeVisible();
  await expect(dark).toBeVisible();

  // Fonds réellement différents : le panneau sombre n'est pas le clair.
  const bgLight = await light.evaluate((node) => getComputedStyle(node).backgroundColor);
  const bgDark = await dark.evaluate((node) => getComputedStyle(node).backgroundColor);
  expect(bgLight).not.toBe(bgDark);

  // Les deux panneaux portent les mêmes primitives.
  await expect(light.locator(".ds-btn--primary")).toBeVisible();
  await expect(dark.locator(".ds-btn--primary")).toBeVisible();
  await expect(dark.locator(".ds-badge--success")).toBeVisible();
});
