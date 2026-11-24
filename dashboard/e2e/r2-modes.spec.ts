import { expect, test } from "@playwright/test";
import { go, LIB_ID, login, newCaptured, P1, T1, UUID_RE, watchErrors, expectClean } from "./support/ui16-stub";

/** Colonne « Aujourd'hui » du lexique (PDF Atelier p.16) : interdite en mode Simple. */
const LEGACY = [
  "Accueil", "Agents IA", "Roadmap", "Réservation", "Handoff", "Vault", "Atlas", "Bibliothèque", "Library",
  "Verrou", "Clé stable", "Jeton machine", "Heartbeat", "Runtime", "Harnais", "Liaison", "Binding", "MCP",
  "Inspecteur de résolution", "Espace de travail", "Daemon", "Administration", "Configuration", "Override",
  "Navigation complète",
];
/** Mots courants en minuscule (« configuration » d'un réglage…) : seule la forme titre est interdite. */
const EXACT = new Set(["Configuration", "Administration", "Library"]);
const ROUTES = [
  "#/", "#/projects", `#/projects/${P1}`, `#/projects/${P1}/tasks`, `#/projects/${P1}/claims`, `#/projects/${P1}/activity`,
  `#/projects/${P1}/decisions`, "#/tasks", `#/tasks/${T1}`, "#/agents", "#/agents/ag-claude", "#/library", "#/library/rules",
  `#/library/rules/${LIB_ID}`, "#/decisions", "#/machines", "#/accounts", "#/administration", "#/transfers", "#/inspector",
  "#/configuration/runtimes", "#/configuration/runtimes/rt1", "#/configuration/bindings", "#/configuration/project",
];

test("R2-modes : mode Simple, aucun terme de l'ancien lexique sur les routes", async ({ page }) => {
  test.setTimeout(180_000);
  const watch = watchErrors(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page, "#/", newCaptured());
  const hits = new Set<string>();
  for (const hash of ROUTES) {
    if (hash !== "#/") await go(page, hash);
    const text = await page.locator("body").innerText();
    for (const line of text.split("\n")) {
      for (const term of LEGACY) if (EXACT.has(term) ? line.includes(term) : line.toLowerCase().includes(term.toLowerCase())) hits.add(`${term} | ${line.trim().slice(0, 110)}`);
    }
  }
  expect([...hits].sort()).toEqual([]);
  expectClean(watch);
});

test("R2-modes : mode Expert annote les termes, ouvre les détails techniques, Simple les referme", async ({ page }) => {
  const watch = watchErrors(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page, "#/", newCaptured());
  await go(page, "#/configuration/runtimes/rt1");
  const closed = page.locator("details.settings-technical:not([open])");
  expect(await closed.count()).toBeGreaterThan(0);
  await page.evaluate(() => {
    localStorage.setItem("studio-os.ui-mode", "expert");
    document.dispatchEvent(new CustomEvent("ui-mode-change", { detail: "expert" }));
  });
  expect(await page.locator("details.settings-technical:not([open])").count()).toBe(0);
  await go(page, "#/tasks");
  await go(page, "#/library");
  expect(await page.locator("#view [data-lx-tech]").count()).toBeGreaterThan(0);
  await go(page, "#/configuration/runtimes/rt1");
  await page.evaluate(() => {
    localStorage.setItem("studio-os.ui-mode", "simple");
    document.dispatchEvent(new CustomEvent("ui-mode-change", { detail: "simple" }));
  });
  expect(await page.locator("details.settings-technical[open]").count()).toBe(0);
  expect(await page.locator("[data-lx-tech]").count()).toBe(0);
  expectClean(watch);
});
