/**
 * P06-regression-rollout — non-régression de la V2 et retour arrière.
 *
 * - Fonctions expertes : chaque destination de la navigation d'avant la V2
 *   (baseline.md, « Mesures communes ») reste atteignable en ≤ 2 interactions
 *   depuis la navigation simple, et par la palette Ctrl K.
 * - Liens profonds : chaque variante de route (y compris l'alias #/admin)
 *   s'ouvre sans « Page introuvable » ni erreur console / CSP.
 * - Activation progressive : le mode de navigation « complet » déploie toutes
 *   les destinations, se mémorise sur le poste et se quitte sans perte — même
 *   route, même contenu de page, aucun secret stocké.
 */
import { expect, test, type Page } from "@playwright/test";
import { expectClean, go, login, newCaptured, P1, T1, LIB_ID, watchErrors } from "./support/ui16-stub";

/** Destinations de la navigation d'avant la V2 (baseline.md) et leur route actuelle. */
const LEGACY_DESTINATIONS = [
  { was: "Accueil", href: "#/" },
  { was: "Projets", href: "#/projects" },
  { was: "Tâches", href: "#/tasks" },
  { was: "Agents IA", href: "#/agents" },
  { was: "Bibliothèque", href: "#/library" },
  { was: "Décisions / À examiner", href: "#/decisions" },
  { was: "Graphes", href: "#/graphs/knowledge" },
  { was: "Transferts", href: "#/transfers" },
  { was: "Machines", href: "#/machines" },
  { was: "Comptes", href: "#/accounts" },
  { was: "Inspecteur", href: "#/inspector" },
  { was: "Paramètres", href: "#/configuration/runtimes" },
  { was: "Dossiers (Desktop)", href: "#/workspaces" },
] as const;

const NAV_MODE_KEY = "studio-os.nav-mode";

async function expectRealPage(page: Page): Promise<void> {
  await expect(page.locator("#view")).not.toContainText("Page introuvable");
  await expect(page.locator("#view h1, #view h2").first()).toBeVisible();
}

for (const target of LEGACY_DESTINATIONS) {
  test(`expert function « ${target.was} » reachable in ≤ 2 clicks from the simple navigation`, async ({ page }) => {
    const watch = watchErrors(page);
    await page.setViewportSize({ width: 1600, height: 900 });
    await login(page, target.href === "#/" ? "#/projects" : "#/", newCaptured());

    const link = page.locator(`.app-sidebar a[href="${target.href}"]`);
    let clicks = 0;
    if (!(await link.isVisible())) {
      // Groupe replié : un clic pour le déplier (Administration / Outils experts).
      await link.locator("xpath=ancestor::details[1]/summary").click();
      clicks += 1;
    }
    await expect(link).toBeVisible();
    await link.click();
    clicks += 1;
    expect(clicks).toBeLessThanOrEqual(2);
    await expect(page).toHaveURL(new RegExp(`${target.href.replace(/[/#]/g, (c) => `\\${c}`)}$`));
    await expectRealPage(page);
    expectClean(watch, [/graph|knowledge/i]);
  });
}

test("every legacy destination is also listed in the Ctrl K palette", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await login(page, "#/", newCaptured());
  await page.keyboard.press("Control+k");
  const hrefs = await page.locator("#app-palette-list [data-href]").evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-href")),
  );
  for (const target of LEGACY_DESTINATIONS) expect(hrefs, target.was).toContain(target.href);
});

const DEEP_LINKS = [
  "#/projects",
  `#/projects/${P1}`,
  `#/projects/${P1}/roadmap`,
  `#/projects/${P1}/tasks`,
  `#/projects/${P1}/claims`,
  `#/projects/${P1}/activity`,
  `#/projects/${P1}/decisions`,
  `#/projects/${P1}/members`,
  `#/projects/${P1}/ai-integration`,
  "#/tasks",
  `#/tasks/${T1}`,
  "#/agents",
  "#/machines",
  "#/accounts",
  "#/administration",
  "#/admin",
  "#/decisions",
  "#/transfers",
  "#/library",
  "#/library/rules",
  "#/library/skills",
  `#/library/skills/${LIB_ID}`,
  "#/configuration",
  "#/configuration/runtimes",
  "#/configuration/bindings",
  "#/configuration/application",
  "#/configuration/integrations",
  "#/configuration/project",
  "#/configuration/project/locks",
  "#/workspaces",
  "#/inspector",
  "#/graphs/knowledge",
  "#/graphs/code",
  "#/graphs/project",
  "#/design-system",
] as const;

test("every route variant opens as a real page (deep links kept)", async ({ page }) => {
  const watch = watchErrors(page);
  await page.setViewportSize({ width: 1600, height: 900 });
  await login(page, "#/", newCaptured());
  for (const hash of DEEP_LINKS) {
    await go(page, hash);
    await expect(page.locator("#view"), hash).not.toContainText("Page introuvable");
  }
  // Un hash inconnu reste une 404 explicite (jamais un repli silencieux).
  await go(page, "#/ancienne-page-disparue");
  await expect(page.locator("#view")).toContainText("Page introuvable");
  expectClean(watch, [/graph|knowledge|inspector/i]);
});

test("complete navigation mode: all destinations visible, remembered, reversible without loss", async ({ page }) => {
  const watch = watchErrors(page);
  await page.setViewportSize({ width: 1600, height: 900 });
  await login(page, "#/", newCaptured());
  await go(page, "#/tasks");

  const toggle = page.getByTestId("nav-mode-toggle");
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator("details.app-navgroup--secondary").first()).not.toHaveAttribute("open", "");
  // Les tâches arrivent après l'en-tête : attendre le contenu avant de le figer.
  await expect(page.locator("#view")).toContainText("Refonte de l'écran titre");
  const before = (await page.locator("#view").textContent()) ?? "";

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(toggle).toBeFocused();
  // Aucune destination n'exige d'ouvrir un groupe, et toutes sont là.
  await expect(page.locator(".app-sidebar details")).toHaveCount(0);
  for (const target of LEGACY_DESTINATIONS) {
    await expect(page.locator(`.app-sidebar a[href="${target.href}"]`), target.was).toBeVisible();
  }
  // Même route, même contenu : le mode ne touche ni l'URL ni les données.
  await expect(page).toHaveURL(/#\/tasks$/);
  await expect(page.locator("#view")).toHaveText(before);
  // Toujours un seul statut de connexion (C4), dans les deux modes.
  await expect(page.getByTestId("connection-status")).toHaveCount(1);
  // Le mode est mémorisé sur le poste ; aucun jeton ni secret n'y est écrit.
  const stored = await page.evaluate(() => ({ ...localStorage, ...Object.fromEntries(Object.entries(sessionStorage)) }));
  expect(stored[NAV_MODE_KEY]).toBe("complete");
  expect(JSON.stringify(stored)).not.toMatch(/e2e-token|e2e-secret|access_token|password|jeton/i);

  // Navigation en mode complet : un clic suffit pour une destination experte.
  await page.locator('.app-sidebar a[href="#/inspector"]').click();
  await expect(page).toHaveURL(/#\/inspector$/);
  await expectRealPage(page);

  // Retour arrière : mode simple restauré, groupes de nouveau repliés.
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".app-sidebar details")).toHaveCount(2);
  expect(await page.evaluate((key) => localStorage.getItem(key), NAV_MODE_KEY)).toBe("simple");
  await expect(page).toHaveURL(/#\/inspector$/);
  expectClean(watch, [/graph|knowledge|inspector/i]);
});

test("complete navigation mode survives a reload and rail widths stay usable", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.addInitScript((key) => localStorage.setItem(key, "complete"), NAV_MODE_KEY);
  await login(page, "#/", newCaptured());
  await expect(page.getByTestId("nav-mode-toggle")).toHaveAttribute("aria-pressed", "true");
  // Rail d'icônes : la liste complète défile dans la barre, la page ne déborde pas.
  const overflow = await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth));
  expect(overflow).toBe(0);
  await page.locator('.app-sidebar a[href="#/transfers"]').scrollIntoViewIfNeeded();
  await expect(page.locator('.app-sidebar a[href="#/transfers"]')).toBeVisible();
});
