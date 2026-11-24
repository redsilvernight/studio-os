/**
 * P06-regression-rollout — non-régression de la V2 et retour arrière.
 *
 * - Fonctions expertes : chaque destination de la navigation d'avant la V2
 *   (baseline.md, « Mesures communes ») reste atteignable en ≤ 2 interactions
 *   depuis la coque Atelier — lien direct ou famille sous Réglages. La palette
 *   Ctrl K reflète désormais les 10 entrées de la coque, pas les routes
 *   historiques ; l'accès rapide passe par Réglages.
 * - Liens profonds : chaque variante de route (y compris l'alias #/admin)
 *   s'ouvre sans « Page introuvable » ni erreur console / CSP.
 * - Activation progressive : le mode de navigation « complet » se mémorise sur
 *   le poste et se quitte sans perte — même coque, même route, même contenu de
 *   page, aucun secret stocké.
 */
import { expect, test, type Page } from "@playwright/test";
import { expectClean, go, login, newCaptured, P1, T1, LIB_ID, watchErrors } from "./support/ui16-stub";

interface LegacyTarget {
  was: string;
  href: string;
  /** Lien direct de la coque Atelier, ou famille de la page Réglages. */
  via: "sidebar" | "admin";
}

/** Destinations de la navigation d'avant la V2 (baseline.md) et leur route actuelle. */
const SIDEBAR_TARGETS: readonly LegacyTarget[] = [
  { was: "Accueil", href: "#/", via: "sidebar" },
  { was: "Projets", href: "#/projects", via: "sidebar" },
  { was: "Tâches", href: "#/tasks", via: "sidebar" },
  { was: "Équipe IA", href: "#/agents", via: "sidebar" },
  { was: "Savoir-faire", href: "#/library", via: "sidebar" },
  { was: "Décisions / À examiner", href: "#/decisions", via: "sidebar" },
  { was: "Graphes", href: "#/vault", via: "sidebar" },
];

const ADMIN_TARGETS: readonly LegacyTarget[] = [
  { was: "Transferts", href: "#/transfers", via: "admin" },
  { was: "Machines", href: "#/machines", via: "admin" },
  { was: "Comptes", href: "#/accounts", via: "admin" },
  { was: "Paramètres", href: "#/configuration/runtimes", via: "admin" },
  { was: "Dossiers (Desktop)", href: "#/workspaces", via: "admin" },
];

const INSPECTOR_TARGET: LegacyTarget = { was: "Inspecteur", href: "#/inspector", via: "admin" };

/** La palette reflète les entrées de la coque, pas les routes expertes. */
const PALETTE_TARGETS: readonly LegacyTarget[] = [
  ...SIDEBAR_TARGETS,
  { was: "Réglages", href: "#/administration", via: "sidebar" },
  { was: "Abonnement", href: "#/abonnement", via: "sidebar" },
  { was: "Aide", href: "#/aide", via: "sidebar" },
];

const UI_MODE_KEY = "studio-os.ui-mode";

async function expectRealPage(page: Page): Promise<void> {
  await expect(page.locator("#view")).not.toContainText("Page introuvable");
  await expect(page.locator("#view h1, #view h2").first()).toBeVisible();
}

/** Nombre de clics réellement nécessaires depuis la navigation simple. */
async function reachLegacyTarget(page: Page, target: LegacyTarget): Promise<number> {
  const sidebarLink = page.locator(`.app-sidebar a[href="${target.href}"]`);
  if (await sidebarLink.count() > 0) {
    await expect(sidebarLink).toBeVisible();
    await sidebarLink.click();
    return 1;
  }
  // Coque Atelier : une entrée Réglages, puis la famille dans la page.
  await page.locator('.app-sidebar a[href="#/administration"]').click();
  await expect(page.locator("#view h1")).toContainText("Réglages");
  await page.locator(`#view .admin-fams a[href="${target.href}"]`).click();
  return 2;
}

async function expectLegacyReachable(page: Page, target: LegacyTarget): Promise<void> {
  const watch = watchErrors(page);
  await page.setViewportSize({ width: 1600, height: 900 });
  await login(page, target.href === "#/" ? "#/projects" : "#/", newCaptured());

  const clicks = await reachLegacyTarget(page, target);
  expect(clicks).toBeLessThanOrEqual(2);
  await expect(page).toHaveURL(new RegExp(`${target.href.replace(/[/#]/g, (c) => `\\${c}`)}$`));
  await expectRealPage(page);
  expectClean(watch, [/graph|knowledge/i]);
}

for (const target of [...SIDEBAR_TARGETS, ...ADMIN_TARGETS]) {
  test(`expert function « ${target.was} » reachable in ≤ 2 clicks from the simple navigation`, async ({ page }) => {
    await expectLegacyReachable(page, target);
  });
}

test("expert function « Inspecteur » reachable in ≤ 2 clicks from the simple navigation", async ({ page }) => {
  await expectLegacyReachable(page, INSPECTOR_TARGET);
});

test("Ctrl K palette lists the shell destinations and reaches expert families via Réglages", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await login(page, "#/", newCaptured());
  await page.keyboard.press("Control+k");
  const hrefs = await page.locator("#app-palette-list [data-href]").evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-href")),
  );
  expect([...hrefs].sort()).toEqual(PALETTE_TARGETS.map((target) => target.href).sort());
  for (const target of ADMIN_TARGETS) expect(hrefs, target.was).not.toContain(target.href);

  // Accès rapide conservé : la palette ouvre Réglages, d'où partent les familles.
  await page.locator("#app-palette-input").fill("réglages");
  const options = page.locator("#app-palette-list [role=option]");
  await expect(options).toHaveCount(1);
  await expect(options.first()).toHaveAttribute("data-href", "#/administration");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/administration$/);
  await expect(page.locator("#view .admin-fams a[href='#/transfers']")).toBeVisible();
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
  // Atlas avant les anciennes URL : `#/graphs/*` est réécrit en `#/vault/atlas`.
  "#/vault/atlas",
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

test("expert mode: switch in Réglages, remembered, adds nothing that moves the Simple shell", async ({ page }) => {
  const watch = watchErrors(page);
  await page.setViewportSize({ width: 1600, height: 900 });
  await login(page, "#/", newCaptured());
  await go(page, "#/administration");

  const navHrefs = (): Promise<(string | null)[]> =>
    page.locator(".app-sidebar a.app-navlink").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("href")));
  const toggle = page.locator("[data-ui-mode-toggle]");
  await expect(page.getByTestId("nav-mode-toggle")).toHaveCount(0);
  await expect(toggle).not.toBeChecked();
  await expect(page.locator("html")).toHaveAttribute("data-ui-mode", "simple");
  const linksBefore = await navHrefs();

  await toggle.check();
  await expect(page.locator("html")).toHaveAttribute("data-ui-mode", "expert");
  expect(await navHrefs()).toEqual(linksBefore);
  for (const target of PALETTE_TARGETS) {
    await expect(page.locator(`.app-sidebar a[href="${target.href}"]`), target.was).toBeVisible();
  }
  await expect(page).toHaveURL(/#\/administration$/);
  await expect(page.getByTestId("connection-status")).toHaveCount(1);
  // Mémorisé sur le poste ; aucun jeton ni secret n'y est écrit.
  const stored = await page.evaluate(() => ({ ...localStorage, ...Object.fromEntries(Object.entries(sessionStorage)) }));
  expect(stored[UI_MODE_KEY]).toBe("expert");
  expect(JSON.stringify(stored)).not.toMatch(/e2e-token|e2e-secret|access_token|password|jeton/i);

  // Palette : « mode expert » propose le retour au mode Simple.
  await page.keyboard.press("Control+k");
  await page.locator("#app-palette-input").fill("mode simple");
  await page.keyboard.press("Enter");
  await expect(page.locator("html")).toHaveAttribute("data-ui-mode", "simple");
  expect(await page.evaluate((key) => localStorage.getItem(key), UI_MODE_KEY)).toBe("simple");
  expect(await navHrefs()).toEqual(linksBefore);
  expectClean(watch, [/graph|knowledge|inspector/i]);
});

test("expert mode survives a reload and rail widths stay usable", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.addInitScript((key) => localStorage.setItem(key, "expert"), UI_MODE_KEY);
  await login(page, "#/", newCaptured());
  await expect(page.locator("html")).toHaveAttribute("data-ui-mode", "expert");
  // Rail d'icônes : les entrées de la coque restent accessibles, la page ne déborde pas.
  const overflow = await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth));
  expect(overflow).toBe(0);
  await expect(page.locator(".app-sidebar a.app-navlink")).toHaveCount(PALETTE_TARGETS.length);
  for (const href of ["#/", "#/projects", "#/tasks", "#/decisions", "#/agents", "#/library", "#/vault"]) {
    const link = page.locator(`.app-sidebar a[href="${href}"]`);
    await link.scrollIntoViewIfNeeded();
    await expect(link).toBeVisible();
  }
  await expect(page.locator('section.app-navgroup--admin a[href="#/administration"]')).toBeVisible();
});
