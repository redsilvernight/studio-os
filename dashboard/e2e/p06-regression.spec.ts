/**
 * P06-regression-rollout — non-régression de la V2 et retour arrière.
 *
 * - Fonctions expertes : chaque destination de la navigation d'avant la V2
 *   (baseline.md, « Mesures communes ») reste atteignable en ≤ 2 interactions
 *   depuis la coque Atelier — lien direct ou famille sous Réglages. La palette
 *   Ctrl K reflète désormais les 10 entrées de la coque, pas les routes
 *   historiques ; l'accès rapide passe par Réglages.
 * - Liens profonds : chaque variante de route (y compris l'alias #/reglages)
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
  { was: "Projets", href: "#/projets", via: "sidebar" },
  { was: "Tâches", href: "#/taches", via: "sidebar" },
  { was: "Équipe IA", href: "#/equipe-ia", via: "sidebar" },
  { was: "Savoir-faire", href: "#/connaissances/savoir-faire", via: "sidebar" },
  { was: "Décisions / À examiner", href: "#/a-valider", via: "sidebar" },
  { was: "Graphes", href: "#/connaissances/notes", via: "sidebar" },
];

const ADMIN_TARGETS: readonly LegacyTarget[] = [
  { was: "Transferts", href: "#/fichiers", via: "admin" },
  { was: "Machines", href: "#/reglages/appareils", via: "admin" },
  { was: "Comptes", href: "#/reglages/equipe-acces", via: "admin" },
  { was: "Paramètres", href: "#/reglages/moteurs", via: "admin" },
  { was: "Dossiers (Desktop)", href: "#/reglages/dossiers", via: "admin" },
];

const INSPECTOR_TARGET: LegacyTarget = { was: "Inspecteur", href: "#/reglages/avance/inspecteur", via: "admin" };

/** La palette reflète les entrées de la coque, pas les routes expertes. */
const PALETTE_TARGETS: readonly LegacyTarget[] = [
  ...SIDEBAR_TARGETS,
  { was: "Réglages", href: "#/reglages", via: "sidebar" },
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
  await page.locator('.app-sidebar a[href="#/reglages"]').click();
  await expect(page.locator("#view h1")).toContainText("Réglages");
  await page.locator(`#view .admin-fams a[href="${target.href}"]`).click();
  return 2;
}

async function expectLegacyReachable(page: Page, target: LegacyTarget): Promise<void> {
  const watch = watchErrors(page);
  await page.setViewportSize({ width: 1600, height: 900 });
  await login(page, target.href === "#/" ? "#/projets" : "#/", newCaptured());

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
  await expect(options.first()).toHaveAttribute("data-href", "#/reglages");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/reglages$/);
  await expect(page.locator("#view .admin-fams a[href='#/fichiers']")).toBeVisible();
});

const DEEP_LINKS = [
  "#/projets",
  `#/projets/${P1}`,
  `#/projets/${P1}/plan`,
  `#/projets/${P1}/taches`,
  `#/projets/${P1}/reservations`,
  `#/projets/${P1}/activite`,
  `#/projets/${P1}/decisions`,
  `#/projets/${P1}/equipe`,
  `#/projets/${P1}/integration-ia`,
  "#/taches",
  `#/taches/${T1}`,
  "#/equipe-ia",
  "#/reglages/appareils",
  "#/reglages/equipe-acces",
  "#/reglages",
  "#/a-valider",
  "#/fichiers",
  "#/connaissances/savoir-faire",
  "#/connaissances/savoir-faire/rules",
  "#/connaissances/savoir-faire/skills",
  `#/connaissances/savoir-faire/skills/${LIB_ID}`,
  "#/reglages/moteurs",
  "#/reglages/moteurs/affectations",
  "#/reglages/application",
  "#/reglages/connexions-ia",
  "#/reglages/avance/projet",
  "#/reglages/avance/projet/locks",
  "#/reglages/dossiers",
  "#/reglages/avance/inspecteur",
  "#/connaissances/carte",
  "#/reglages/avance/design-system",
] as const;

test("every route variant opens as a real page (deep links kept)", async ({ page }) => {
  const watch = watchErrors(page);
  await page.setViewportSize({ width: 1600, height: 900 });
  await login(page, "#/", newCaptured());
  for (const hash of DEEP_LINKS) {
    await go(page, hash);
    await expect(page.locator("#view"), hash).not.toContainText("Page introuvable");
  }
  // Anciennes adresses (favoris, liens partagés) : réécrites puis ouvertes.
  for (const [old, next] of [
    [`#/projects/${P1}/claims`, `#/projets/${P1}/reservations`],
    ["#/administration", "#/reglages"],
    ["#/configuration/runtimes", "#/reglages/moteurs"],
    ["#/graphs/knowledge", "#/connaissances/carte"],
  ] as const) {
    await page.evaluate((hash) => (location.hash = hash), old);
    await expect.poll(() => page.evaluate(() => location.hash), old).toBe(next);
    await expect(page.locator("#view"), old).not.toContainText("Page introuvable");
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
  await go(page, "#/reglages");

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
  await expect(page).toHaveURL(/#\/reglages$/);
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
  for (const href of ["#/", "#/projets", "#/taches", "#/a-valider", "#/equipe-ia", "#/connaissances/savoir-faire", "#/connaissances/notes"]) {
    const link = page.locator(`.app-sidebar a[href="${href}"]`);
    await link.scrollIntoViewIfNeeded();
    await expect(link).toBeVisible();
  }
  await expect(page.locator('section.app-navgroup--admin a[href="#/reglages"]')).toBeVisible();
});
