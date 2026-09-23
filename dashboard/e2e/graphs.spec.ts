import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { login, newCaptured, globalOverflow } from "./support/ui16-stub";

async function waitForView(page: any, kind: string) {
  const titles: Record<string, string> = { knowledge: "Graphe de connaissances", code: "Graphe de code", project: "Graphe du projet" };
  await expect(page.locator("h1", { hasText: titles[kind] })).toBeVisible();
  await expect(page.locator(`.graph-tabs a[href="#/graphs/${kind}"]`)).toHaveAttribute("aria-current", "page");
}

test("web source unavailable, Knowledge/Code/Project navigation, provenance and keyboard", async ({ page }) => {
  await login(page, "#/graphs/knowledge", newCaptured());
  await expect(page.locator("[data-source-status]")).toContainText("Disponible dans Studi");
  await page.getByLabel("Source affichée").selectOption("small");
  await expect(page.locator(".graph-node")).toHaveCount(4);
  await page.locator(".graph-results button").first().focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Détails du nœud")).toContainText("Introduction");
  await page.getByLabel("Rechercher un nœud").fill("Combat");
  await expect(page.locator(".graph-node")).toHaveCount(1);
  await page.getByRole("link", { name: "Graphe de code", exact: true }).click();
  await waitForView(page, "code");
  await page.getByLabel("Source affichée").selectOption("small");
  await expect(page.locator(".graph-node")).toHaveCount(4);
  await page.getByRole("link", { name: "Graphe du projet", exact: true }).click();
  await waitForView(page, "project");
  await page.getByLabel("Source affichée").selectOption("small");
  await expect(page.locator(".graph-node")).toHaveCount(8);
  await expect(page.locator(".graph-viewer line")).toHaveCount(8);
  const axe = await new AxeBuilder({ page }).include("#view").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(axe.violations).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await globalOverflow(page)).toBeLessThanOrEqual(1);
});

for (const [size, last] of [["small", "main"], ["medium", "00999"], ["large", "29999"]] as const) {
  test(`graph performance ${size}: opening, search, selection, interaction and memory`, async ({ page }, testInfo) => {
    await login(page, "#/graphs/code", newCaptured());
    const timings: Record<string, number> = {};
    let start = Date.now();
    await page.getByLabel("Source affichée").selectOption(size);
    await expect(page.locator(".graph-node").first()).toBeVisible();
    timings.open_ms = Date.now() - start;
    start = Date.now();
    await page.getByLabel("Rechercher dans les sources", { exact: true }).fill(last);
    await page.getByRole("button", { name: "Rechercher dans les sources", exact: true }).click();
    await expect(page.locator("[data-source-results]")).toContainText(last);
    timings.search_ms = Date.now() - start;
    start = Date.now();
    await page.locator(".graph-results button").first().click();
    await expect(page.locator(".graph-details h3")).toBeVisible();
    timings.select_ms = Date.now() - start;
    start = Date.now();
    await page.getByRole("button", { name: "Zoom +", exact: true }).click();
    await expect(page.locator(".graph-viewer svg > g")).toHaveAttribute("transform", /scale\(1.25\)/);
    timings.interaction_ms = Date.now() - start;
    const metrics = await page.evaluate(() => ({
      dom_nodes: document.querySelectorAll(".graph-viewer *").length,
      drawn_nodes: document.querySelectorAll(".graph-node").length,
      heap_bytes: (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize ?? null,
    }));
    expect(metrics.drawn_nodes).toBeLessThanOrEqual(80);
    expect(metrics.dom_nodes).toBeLessThan(1500);
    for (const ms of Object.values(timings)) expect(ms).toBeLessThan(5000);
    if (metrics.heap_bytes !== null) expect(metrics.heap_bytes).toBeLessThan(150 * 1024 * 1024);
    console.log(`P8_PERF ${JSON.stringify({ size, ...timings, ...metrics })}`);
    await testInfo.attach(`performance-${size}`, { body: JSON.stringify({ size, ...timings, ...metrics }, null, 2), contentType: "application/json" });
  });
}
