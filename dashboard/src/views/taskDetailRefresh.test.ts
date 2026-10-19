// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import { renderTaskDetail } from "./taskDetail";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

it("Actualiser l'état recharge la tâche, le protocole, les sessions et le handoff", async () => {
  let handedOff = false;
  const task = { id: "task", project_id: "project", title: "Tâche initiale", status: "in_progress", version: 1,
    description: "", claimed_by_machine_id: null, claimed_by_agent_id: null,
    created_at: "2026-10-14T10:00:00Z", updated_at: "2026-10-14T10:00:00Z" };
  const launch = () => ({ id: "launch", task_id: task.id, project_id: task.project_id, machine_id: "machine",
    harness_id: "opencode", status: handedOff ? "succeeded" : "running", session_id: "session",
    requested_by_user_id: "user", reason_code: "none", version: 1,
    protocol: { status: handedOff ? "handed_off" : "unverified", task_status: handedOff ? "completed" : "in_progress" },
    created_at: "2026-10-14T10:00:00Z", updated_at: "2026-10-14T10:00:00Z" });
  const get = vi.fn(async (path: string) => {
    let data: unknown;
    if (path === "/api/v1/tasks/{task_id}") data = { ...task, title: handedOff ? "Tâche actualisée" : task.title, status: handedOff ? "completed" : task.status };
    else if (path === "/api/v1/sessions") data = [{ id: "session", machine_id: "machine", started_at: "2026-10-14T10:00:00Z", ended_at: handedOff ? "2026-10-14T10:05:00Z" : null }];
    else if (path === "/api/v1/ai-work") data = handedOff ? [{ id: "work", status: "completed", summary: "Handoff actualisé", started_at: "2026-10-14T10:00:00Z" }] : [];
    else if (path.includes("eligible-machines")) data = { machines: [] };
    else if (path === "/api/v1/projects/{project_id}/task-launches") data = { items: [launch()] };
    else if (path === "/api/v1/task-launches/{launch_id}") data = launch();
    else if (path.includes("usage") || path.includes("snapshot")) return { response: new Response(null, { status: 404 }) };
    else data = [];
    return { data, response: new Response(null, { status: 200 }) };
  });
  const client = { GET: get } as unknown as StudioClient;
  const root = document.createElement("div");
  document.body.append(root);
  await renderTaskDetail(root, { client, authed: true, identity: null }, task.id);
  const mechanics = root.querySelector<HTMLDetailsElement>("#task-mecanique")!;
  mechanics.open = true;
  expect(root.querySelector("#task-ai-work")?.textContent).not.toContain("Handoff actualisé");
  handedOff = true;
  root.querySelector<HTMLButtonElement>("[data-action=launch-refresh]")!.click();
  await vi.waitFor(() => expect(root.querySelector("h1")?.textContent).toBe("Tâche actualisée"));
  expect(root.querySelector("#task-ai-work")?.textContent).toContain("Handoff actualisé");
  expect(root.querySelector("#task-sessions")?.textContent).toContain("Terminée");
  expect(root.querySelector("[data-testid=launch-latest]")?.textContent).not.toContain("Protocole non vérifié");
  expect(root.querySelector<HTMLDetailsElement>("#task-mecanique")?.open).toBe(true);
  expect(document.activeElement).toBe(root.querySelector("[data-action=launch-refresh]"));
});
