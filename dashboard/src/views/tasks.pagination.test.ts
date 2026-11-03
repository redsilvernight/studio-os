// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import type { Task } from "../tasksApi";
import { renderTasksInto } from "./tasks";

const projectId = "11111111-2222-4333-8444-555555555555";
const tasks = (count: number, status: Task["status"]): Task[] => Array.from({ length: count }, (_, index) => ({
  id: `${status}-${index}`, project_id: projectId, title: `${status} ${index}`, status,
  readable_id: null, description: null, version: 1, claimed_by_machine_id: null,
  claimed_by_agent_id: null, created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z",
}));

function mount(data: Task[], failMore = false) {
  const requests: { status: string[]; limit: number; offset: number }[] = [];
  const GET = vi.fn(async (_path: string, options: { params: { query: { status: string[]; limit: number; offset: number } } }) => {
    const query = options.params.query;
    requests.push(query);
    if (failMore && query.offset === 100) {
      failMore = false;
      throw new Error("réseau interrompu");
    }
    return { data: data.filter((task) => query.status.includes(task.status)).slice(query.offset, query.offset + query.limit), response: new Response(null, { status: 200 }) };
  });
  const root = document.createElement("div");
  document.body.append(root);
  return { root, requests, client: { GET } as unknown as StudioClient };
}

const click = (root: HTMLElement, selector: string) => root.querySelector<HTMLButtonElement>(selector)!.click();

afterEach(() => { document.body.innerHTML = ""; });

describe("pagination des tâches actives", () => {
  it("accède aux actives anciennes au-delà de 100, puis charge les terminées explicitement", async () => {
    const { root, client, requests } = mount([...tasks(600, "completed"), ...tasks(225, "in_progress"), ...tasks(5, "created")]);
    await renderTasksInto(root, { client, authed: true, projectId, scopeLabel: "Projet" });
    click(root, '.tasks-scope-tabs [data-scope="all"]');
    await vi.waitFor(() => expect(root.querySelectorAll(".task-row")).toHaveLength(105));
    expect(requests.every((query) => query.status.includes("completed") === false)).toBe(true);
    expect(requests.slice(-2).map((query) => query.status)).toEqual([["in_progress", "blocked"], ["created"]]);
    click(root, '[data-view="board"]');
    expect(root.querySelector('[data-column="IN PROGRESS"]')?.textContent).toContain("100+");
    expect(root.querySelector('[data-column="DONE"]')?.textContent).toContain("Chargées à la demande");
    click(root, "[data-more]");
    await vi.waitFor(() => expect(root.querySelectorAll("[data-card]")).toHaveLength(205));
    expect(requests.at(-1)?.offset).toBe(100);
    click(root, "[data-more]");
    await vi.waitFor(() => expect(root.querySelectorAll("[data-card]")).toHaveLength(230));
    expect(root.querySelector("[data-more]")).toBeNull();
    expect(root.querySelector('[data-column="IN PROGRESS"]')?.textContent).toContain("(225)");
    click(root, "[data-completed]");
    await vi.waitFor(() => expect(root.querySelectorAll("[data-card]")).toHaveLength(330));
    expect(requests.at(-1)).toMatchObject({ status: ["completed"], limit: 100, offset: 0 });
    expect(requests.every((query) => query.limit <= 100)).toBe(true);
  });

  it("conserve les tâches et le curseur lorsque la page suivante échoue", async () => {
    const { root, client, requests } = mount(tasks(125, "blocked"), true);
    await renderTasksInto(root, { client, authed: true, projectId, scopeLabel: "Projet" });
    click(root, '.tasks-scope-tabs [data-scope="all"]');
    await vi.waitFor(() => expect(root.querySelectorAll(".task-row")).toHaveLength(100));
    click(root, "[data-more]");
    await vi.waitFor(() => expect(root.textContent).toContain("Les tâches déjà chargées sont conservées"));
    expect(root.querySelectorAll(".task-row")).toHaveLength(100);
    click(root, "[data-more]");
    await vi.waitFor(() => expect(root.querySelectorAll(".task-row")).toHaveLength(125));
    expect(requests.slice(-2).map((query) => query.offset)).toEqual([100, 100]);
  });
});
