import { expect, test, type Page } from "@playwright/test";

const projectId = "11111111-2222-4333-8444-555555555555";
const project = { id: projectId, slug: "retours", name: "Projet retours", description: "Un objectif lisible", archived: false, version: 1, created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z" };
const taskRows = (count: number, status: string) => Array.from({ length: count }, (_, index) => ({
  id: `${status}-${index}`, project_id: projectId, title: `${status} ${index}`, status, readable_id: null, description: null,
  claimed_by_machine_id: null, claimed_by_agent_id: null, version: 1, created_at: "2026-01-01T10:00:00Z", updated_at: "2026-01-01T10:00:00Z",
}));

async function fixture(page: Page, hash: string, role = "admin", coordination = false) {
  const rows = [...taskRows(650, "completed"), ...taskRows(225, "in_progress"), ...taskRows(5, "created")];
  const queries: URLSearchParams[] = [];
  const writes: { path: string; body: unknown }[] = [];
  const proposed = { id: "d-proposed", readable_id: "DEC-0010", project_id: projectId, task_id: "in_progress-224", title: "Une proposition précise", body: `${"Contexte complet et justification. ".repeat(60)}Fin de la décision.`, status: "proposed", proposed_by_type: "user", proposed_by_id: "user", created_at: "2026-10-20T09:00:00Z" };
  const decisions = [proposed, { ...proposed, id: "d-accepted", readable_id: "DEC-0009", title: "Ancienne référence", status: "accepted" }, { ...proposed, id: "d-replacement", readable_id: "DEC-0011", title: "Nouvelle référence", status: "accepted" }];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path.endsWith("/auth/token")) return json({ access_token: "e2e-token", token_type: "bearer" });
    if (path.endsWith("/auth/me")) return json({ user_id: "user", display_name: "E2E", email: "e2e@example.test", role, machine_id: "machine", machine_name: "Poste test", active: true });
    if (path.endsWith("/tasks") && request.method() === "GET") {
      queries.push(url.searchParams);
      const statuses = url.searchParams.getAll("status");
      const filtered = rows.filter((task) => statuses.length === 0 || statuses.includes(task.status));
      const offset = Number(url.searchParams.get("offset") ?? 0);
      return json(filtered.slice(offset, offset + Number(url.searchParams.get("limit") ?? 100)));
    }
    if (path.endsWith("/tasks") && request.method() === "POST") {
      writes.push({ path, body: request.postDataJSON() });
      return json({ ...rows[0], ...request.postDataJSON(), id: "new-task", status: "created" }, 201);
    }
    if (path.endsWith("/review-queue")) return json({ generated_at: "2026-10-20T10:00:00Z", items: proposed.status === "proposed" ? [{ kind: "decision_proposal", id: proposed.id, readable_id: proposed.readable_id, project_id: projectId, task_id: proposed.task_id, title: proposed.title, proposed_by_type: "user", requested_at: proposed.created_at }] : [] });
    if (path.endsWith("/decisions")) return json(decisions);
    if (/\/decisions\/[^/]+\/(accept|supersede)$/.test(path)) {
      writes.push({ path, body: request.postData() ? request.postDataJSON() : null });
      const item = decisions.find((decision) => path.includes(`/${decision.id}/`))!;
      item.status = path.endsWith("/accept") ? "accepted" : "superseded";
      return json(item);
    }
    if (path.endsWith(`/projects/${projectId}/state`)) return json({ project_id: projectId, active_tasks: [], active_claims: [], recent_events: [], active_sessions: [] });
    if (path.endsWith(`/projects/${projectId}/mission`)) return json({ project_id: projectId, window_hours: 24, runs: [], counts: { total: 0, by_verdict: {} }, truncated: false });
    if (path.endsWith("/events")) return json(coordination ? [{ event_id: "coordination-event", event_type: "coordination.blocked_by", project_id: projectId, task_id: "in_progress-224", server_timestamp: "2026-10-20T09:00:00Z", payload: { text: `Un blocage à traiter. ${"CheminSansEspace".repeat(35)}` } }] : []);
    if (path.endsWith("/usage/summary")) return json({ detail: "indisponible" }, 503);
    if (path.endsWith(`/projects/${projectId}`)) return json(project);
    if (path.endsWith("/projects")) return json([project]);
    return json([]);
  });
  await page.goto(`/${hash}`);
  await page.locator("#login-email").fill("e2e@example.test");
  await page.locator("#login-password").fill("e2e-secret");
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator(".app-sidebar")).toBeVisible();
  return { queries, writes, clearCoordination: () => { coordination = false; } };
}

test("Kanban exhaustif, terminées sur demande et actions alignées dans le projet", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const { queries, writes } = await fixture(page, `#/projects/${projectId}/tasks`);
  await expect(page.locator("#view")).not.toContainText("même présentation");
  const create = page.locator("#task-new");
  const scopes = page.locator(".tasks-scope-tabs");
  await expect(create).toBeVisible();
  const [buttonBox, scopeBox] = await Promise.all([create.boundingBox(), scopes.boundingBox()]);
  expect(Math.abs(buttonBox!.y - scopeBox!.y)).toBeLessThan(8);
  await page.screenshot({ path: testInfo.outputPath("tasks-1280.png") });
  await scopes.locator('[data-scope="all"]').click();
  await expect(page.locator(".task-row")).toHaveCount(105);
  await page.locator('[data-view="board"]').click();
  await expect(page.locator('[data-column="IN PROGRESS"] .task-col-title')).toContainText("100+");
  expect(queries.some((query) => query.getAll("status").includes("completed"))).toBe(false);
  await page.locator("[data-more]").click();
  await expect(page.locator("[data-card]")).toHaveCount(205);
  await page.locator("[data-more]").click();
  await expect(page.locator("[data-card]")).toHaveCount(230);
  await expect(page.getByRole("link", { name: "in_progress 224", exact: true })).toBeVisible();
  expect(queries.some((query) => query.get("offset") === "200")).toBe(true);
  await page.locator("[data-completed]").click();
  await expect(page.locator("[data-card]")).toHaveCount(330);
  expect(queries.at(-1)?.getAll("status")).toEqual(["completed"]);
  await page.setViewportSize({ width: 375, height: 812 });
  if ((await page.locator("#nav-open").getAttribute("aria-expanded")) === "true") await page.locator("#nav-close").click();
  await create.click();
  await page.locator("#task-title").fill("Nouvelle tâche dans le bon projet");
  await page.locator("#task-create-submit").click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]?.body).toMatchObject({ project_id: projectId });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("tasks-375.png") });
});

test("résumés projet cohérents : texte long, état vide et erreur restent lisibles", async ({ page }, testInfo) => {
  const state = await fixture(page, `#/projects/${projectId}`, "admin", true);
  await expect(page.locator(".workspace-summary-card")).toHaveCount(3);
  await expect(page.locator("[data-coordination-intent]")).toContainText("Un blocage à traiter");
  await expect(page.locator("[data-coordination-intent] a")).toHaveAttribute("href", "#/tasks/in_progress-224");
  await expect(page.locator("[data-usage-unavailable]")).toContainText("Consommation indisponible");
  await page.setViewportSize({ width: 375, height: 812 });
  if ((await page.locator("#nav-open").getAttribute("aria-expanded")) === "true") await page.locator("#nav-close").click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("project-summary-375.png"), fullPage: true });
  state.clearCoordination();
  await page.locator('[data-ws-tab="tasks"]').click();
  await page.locator('[data-ws-tab="overview"]').click();
  await expect(page.getByLabel("Coordination à traiter")).toContainText("Rien à traiter");
});

test("décision complète : écarter une proposition et lier un remplacement distinct", async ({ page }) => {
  const { writes } = await fixture(page, "#/decisions");
  await expect(page.locator(".review-hero h2")).toHaveText("Une proposition précise");
  await expect(page.locator(".review-hero .decision-item-body")).toContainText("Fin de la décision.");
  await expect(page.locator(".review-hero [data-decision-accept]")).toBeEnabled();
  await page.locator(".review-hero [data-decision-supersede]").click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({ path: "/api/v1/decisions/d-proposed/supersede", body: null });
  await page.getByRole("tab", { name: "Historique des décisions" }).click();
  await page.locator('[data-decision-supersede="d-accepted"]').click();
  await expect(page.locator("#replace-decision-modal")).toBeVisible();
  await page.locator("#decision-replacement").selectOption("d-replacement");
  await page.getByRole("button", { name: "Confirmer le remplacement" }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]?.body).toEqual({ superseded_by: "d-replacement" });
});

test("décisions : droits développeur conservés sur toutes les actions", async ({ page }) => {
  await fixture(page, "#/decisions", "developer");
  await expect(page.locator(".review-hero [data-decision-accept]")).toBeDisabled();
  await expect(page.locator(".review-hero [data-decision-supersede]")).toBeDisabled();
  await expect(page.locator(".review-hero")).toContainText("Réservé au rôle admin");
});
