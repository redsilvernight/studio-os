// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import { renderTaskDetail } from "./taskDetail";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

it.each(["", "coding", "architecture-read-only"])("transmet le profil choisi %s sans élargir l'autorisation de production", async (profileKey) => {
  const task = { id: "task", project_id: "project", title: "Profil", status: "created", version: 1,
    description: "", claimed_by_machine_id: null, claimed_by_agent_id: null,
    created_at: "2026-10-28T10:00:00Z", updated_at: "2026-10-28T10:00:00Z" };
  const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
  const get = vi.fn(async (path: string) => {
    if (path === "/api/v1/tasks/{task_id}") return ok(task);
    if (path.includes("eligible-machines")) return ok({ machines: [{ machine_id: "machine", display_name: "Poste", eligible: true, status: "online", free_slots: 1,
      harnesses: [{ harness_id: "claude-code", detected: true, configured: true }] }] });
    if (path === "/api/v1/library") return ok([{ stable_key: "review-helper", deprecated: false }]);
    if (path === "/api/v1/projects/{project_id}/task-launches") return ok({ items: [] });
    if (path.includes("usage") || path.includes("snapshot")) return { response: new Response(null, { status: 404 }) };
    return ok([]);
  });
  const post = vi.fn(async () => ({ response: new Response(null, { status: 403 }) }));
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  const root = document.createElement("div");
  document.body.append(root);
  await renderTaskDetail(root, { client: { GET: get, POST: post } as unknown as StudioClient, authed: true, identity: null }, task.id);
  const choose = (id: string, value: string) => {
    const select = root.querySelector<HTMLSelectElement>(`#${id}`)!;
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  };
  choose("launch-machine", "machine");
  choose("launch-harness", "claude-code");
  const production = root.querySelector<HTMLInputElement>("#launch-production")!;
  production.checked = true;
  production.dispatchEvent(new Event("change", { bubbles: true }));
  choose("launch-profile", profileKey);
  expect(root.querySelector<HTMLInputElement>("#launch-production")!.checked).toBe(false);
  if (profileKey) expect(root.querySelector<HTMLButtonElement>("[data-action=launch-submit]")!.disabled).toBe(true);
  choose("launch-agent", "review-helper");
  root.querySelector<HTMLButtonElement>("[data-action=launch-submit]")!.click();
  await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));
  const call = post.mock.calls[0] as unknown as [string, { body: Record<string, unknown> }];
  expect(call[0]).toBe("/api/v1/projects/{project_id}/task-launches");
  expect(call[1].body.allow_production).toBe(false);
  expect(call[1].body.agent_stable_key).toBe("review-helper");
  if (profileKey) expect(call[1].body.profile_key).toBe(profileKey);
  else expect(call[1].body).not.toHaveProperty("profile_key");
  expect(confirm).toHaveBeenCalledTimes(1);
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
