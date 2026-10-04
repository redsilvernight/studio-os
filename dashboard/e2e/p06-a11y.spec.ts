/**
 * P06 — Accessibilité : clavier, focus, axe (contraste inclus) et zoom 200 % sur les pages principales.
 *
 * Chaque défaut fait échouer le test de sa page : aucun défaut n'est seulement journalisé.
 * Zoom 200 % simulé par un viewport 720×450 (écran 1440×900) ; le contenu sous la ligne de flottaison
 * reste atteignable par défilement vertical, seul le débordement horizontal est un défaut (WCAG 1.4.10).
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { login, newCaptured, P1, T1, watchErrors, expectClean, globalOverflow } from "./support/ui16-stub";

const ROUTES_A11Y = [
  { name: "Accueil", hash: "#/" },
  { name: "Projets", hash: "#/projects" },
  { name: "Travail", hash: "#/tasks" },
  { name: "Fiche tâche", hash: `#/tasks/${T1}` },
  { name: "À valider", hash: "#/decisions" },
  { name: "Agents", hash: "#/agents" },
  { name: "Roadmap", hash: `#/projects/${P1}/roadmap` },
] as const;

const ZOOM_VIEWPORT = { width: 720, height: 450 };
const DESKTOP_VIEWPORT = { width: 1440, height: 900 };
const MAX_TABS = 80;

/** Parcourt la page au clavier (Tab) et signale focus invisible, absence de progression et piège de focus. */
async function tabThroughPage(page: Page): Promise<string[]> {
  const problems: string[] = [];
  const seen = new Set<string>();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());

  for (let i = 0; i < MAX_TABS; i++) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const cs = getComputedStyle(el);
      const outline = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
      const shadow = cs.boxShadow !== "none" && cs.boxShadow !== "";
      const rect = el.getBoundingClientRect();
      const label = (el.getAttribute("aria-label") || el.textContent || el.id || "").trim().slice(0, 40);
      return {
        key: `${el.tagName.toLowerCase()}#${el.id}.${el.className}|${label}|${Math.round(rect.x)},${Math.round(rect.y)}`,
        desc: `<${el.tagName.toLowerCase()}${el.id ? ` id="${el.id}"` : ""}> « ${label} »`,
        visibleFocus: outline || shadow,
        onScreen: rect.width > 0 && rect.height > 0,
      };
    });
    if (info === null) break; // le focus a quitté le document : cycle complet, pas de piège
    if (seen.has(info.key)) break; // retour au premier élément : cycle complet
    seen.add(info.key);
    if (info.onScreen && !info.visibleFocus) problems.push(`focus non visible : ${info.desc}`);
  }
  if (seen.size === 0) problems.push("Tab ne met le focus sur aucun contrôle");
  return problems;
}

/** Palette Ctrl K : ouverture, focus piégé dans la palette, Échap, retour du focus au déclencheur. */
async function checkPalette(page: Page): Promise<string[]> {
  const problems: string[] = [];
  const trigger = page.locator("#palette-open");
  await trigger.focus();
  await page.keyboard.press("Enter");
  const palette = page.locator("#app-palette");
  await expect(palette).toBeVisible({ timeout: 3000 });
  await expect(page.locator("#app-palette-input")).toBeFocused();

  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(() => document.getElementById("app-palette")?.contains(document.activeElement) ?? false);
    if (!inside) {
      problems.push("palette : Tab fait sortir le focus de la boîte de dialogue");
      break;
    }
  }
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  if (!(await trigger.evaluate((el) => el === document.activeElement))) {
    problems.push("palette : le focus ne revient pas au déclencheur après Échap");
  }
  return problems;
}

async function axeBlocking(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .include("body")
    .analyze();
  return results.violations
    .filter((v) => v.impact === "critical" || v.impact === "serious" || v.id === "color-contrast")
    .flatMap((v) => v.nodes.map((n) => `${v.id} (${v.impact}) ${n.target.join(" ")}`));
}

/** Zoom 200 % : pas de défilement horizontal de page ; chaque action primaire tient dans la largeur une fois atteinte. */
async function zoomProblems(page: Page): Promise<string[]> {
  const problems: string[] = [];
  await page.setViewportSize(ZOOM_VIEWPORT);
  await page.waitForTimeout(300);

  const overflow = await globalOverflow(page);
  if (overflow > 0) problems.push(`défilement horizontal de ${overflow}px à ${ZOOM_VIEWPORT.width}×${ZOOM_VIEWPORT.height}`);

  const actions = page.locator(".ds-btn--primary:not([disabled]), button[data-claim]:not([disabled])");
  const count = await actions.count();
  for (let i = 0; i < count; i++) {
    const action = actions.nth(i);
    if (!(await action.isVisible().catch(() => false))) continue;
    await action.scrollIntoViewIfNeeded();
    const box = await action.boundingBox();
    if (box && (box.x < 0 || box.x + box.width > ZOOM_VIEWPORT.width + 1)) {
      const label = ((await action.textContent()) ?? "").trim().slice(0, 40);
      problems.push(`action primaire « ${label} » coupée horizontalement (x=${Math.round(box.x)}, largeur=${Math.round(box.width)})`);
    }
  }
  return problems;
}

test.describe.configure({ retries: 0 });

test.describe("P06 Accessibilité — pages principales", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize(DESKTOP_VIEWPORT);
  });

  for (const { name, hash } of ROUTES_A11Y) {
    test.describe(`${name} (${hash})`, () => {
      test("clavier : parcours Tab, focus visible, pas de piège, palette", async ({ page }) => {
        const watch = watchErrors(page);
        await login(page, hash, newCaptured());
        const problems = [...(await tabThroughPage(page)), ...(await checkPalette(page))];
        expect(problems, name).toEqual([]);
        expectClean(watch);
      });

      test("axe-core : aucune violation serious/critical ni de contraste", async ({ page }) => {
        const watch = watchErrors(page);
        await login(page, hash, newCaptured());
        expect(await axeBlocking(page), name).toEqual([]);
        expectClean(watch);
      });

      test("zoom 200 % (720×450) : pas de défilement horizontal, actions primaires atteignables", async ({ page }) => {
        const watch = watchErrors(page);
        await login(page, hash, newCaptured());
        expect(await zoomProblems(page), name).toEqual([]);
        expectClean(watch);
      });
    });
  }
});
