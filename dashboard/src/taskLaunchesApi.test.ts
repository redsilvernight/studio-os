import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import {
  cancelTaskLaunch,
  createTaskLaunch,
  getEligibleMachines,
  getTaskLaunch,
  listTaskLaunches,
  type TaskLaunch,
} from "./taskLaunchesApi";

type Fake = { GET: ReturnType<typeof vi.fn>; POST: ReturnType<typeof vi.fn> };
const fakeClient = (impl: Partial<Fake>): StudioClient =>
  ({ GET: vi.fn(), POST: vi.fn(), ...impl }) as unknown as StudioClient;

const ok = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 200 } as Response,
});
const fail = (status: number, error: unknown): { data?: undefined; error: unknown; response: Response } => ({
  error,
  response: { ok: false, status } as Response,
});

describe("getEligibleMachines", () => {
  it("GET the task's eligibility without a harness filter by default", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ task_id: "t1", project_id: "p1", machines: [] }));
    const result = await getEligibleMachines(fakeClient({ GET }), "t1");
    expect(GET).toHaveBeenCalledWith("/api/v1/tasks/{task_id}/eligible-machines", {
      params: { path: { task_id: "t1" } },
    });
    expect(result.machines).toEqual([]);
  });

  it("adds the harness_id query only when one is given", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ task_id: "t1", project_id: "p1", machines: [] }));
    await getEligibleMachines(fakeClient({ GET }), "t1", "claude-code");
    expect(GET).toHaveBeenCalledWith("/api/v1/tasks/{task_id}/eligible-machines", {
      params: { path: { task_id: "t1" }, query: { harness_id: "claude-code" } },
    });
  });
});

describe("listTaskLaunches", () => {
  it("GET the project page and unwraps items", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ items: [{ id: "l1" }], limit: 100, offset: 0 }));
    const launches = await listTaskLaunches(fakeClient({ GET }), "p1");
    expect(GET).toHaveBeenCalledWith("/api/v1/projects/{project_id}/task-launches", {
      params: { path: { project_id: "p1" }, query: { limit: 100, offset: 0 } },
    });
    expect(launches).toEqual([{ id: "l1" }]);
  });

  it("transmets la preuve de protocole portée par la vue projet", async () => {
    const GET = vi.fn().mockResolvedValue(
      ok({
        items: [
          { id: "l1", status: "succeeded", protocol: { status: "unverified", session_id: null, task_status: null } },
          { id: "l2", status: "failed", protocol: { status: "handed_off", session_id: "s2", task_status: "blocked" } },
        ],
        limit: 100,
        offset: 0,
      }),
    );
    const launches = await listTaskLaunches(fakeClient({ GET }), "p1");
    expect(launches[0]?.protocol?.status).toBe("unverified");
    expect(launches[1]?.protocol?.task_status).toBe("blocked");
  });

  it("tolère un serveur qui n'envoie pas encore `protocol`", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ items: [{ id: "l1", status: "succeeded" }], limit: 100, offset: 0 }));
    const launches = await listTaskLaunches(fakeClient({ GET }), "p1");
    expect(launches[0]?.protocol).toBeUndefined();
  });
});

describe("createTaskLaunch", () => {
  it("POSTs the typed body with the caller's Idempotency-Key", async () => {
    const POST = vi.fn().mockResolvedValue(ok({ id: "l1", status: "requested" }));
    const created = await createTaskLaunch(
      fakeClient({ POST }),
      "p1",
      { task_id: "t1", machine_id: "m1", harness_id: "claude-code", expires_in_seconds: 900 },
      "idem-1",
    );
    expect(POST).toHaveBeenCalledWith("/api/v1/projects/{project_id}/task-launches", {
      params: { path: { project_id: "p1" }, header: { "Idempotency-Key": "idem-1" } },
      body: { task_id: "t1", machine_id: "m1", harness_id: "claude-code", expires_in_seconds: 900 },
    });
    expect(created.status).toBe("requested");
  });

  it("maps a 403 as a structured ApiError", async () => {
    const POST = vi.fn().mockResolvedValue(fail(403, { detail: { error_code: "forbidden" } }));
    await expect(
      createTaskLaunch(
        fakeClient({ POST }),
        "p1",
        { task_id: "t1", machine_id: "m1", harness_id: "claude-code", expires_in_seconds: 900 },
        "idem-1",
      ),
    ).rejects.toMatchObject({ status: 403, errorCode: "forbidden" });
  });
});

describe("getTaskLaunch / cancelTaskLaunch", () => {
  it("GET one launch by id", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ id: "l1", status: "running" }));
    const launch = await getTaskLaunch(fakeClient({ GET }), "l1");
    expect(GET).toHaveBeenCalledWith("/api/v1/task-launches/{launch_id}", { params: { path: { launch_id: "l1" } } });
    expect(launch.status).toBe("running");
  });

  it("la lecture par id reste sans `protocol`", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ id: "l1", status: "succeeded" }));
    const launch = (await getTaskLaunch(fakeClient({ GET }), "l1")) as TaskLaunch & { protocol?: unknown };
    expect(launch.protocol).toBeUndefined();
  });

  it("POST cancel with the current version", async () => {
    const POST = vi.fn().mockResolvedValue(ok({ id: "l1", status: "cancelled" }));
    await cancelTaskLaunch(fakeClient({ POST }), "l1", 3);
    expect(POST).toHaveBeenCalledWith("/api/v1/task-launches/{launch_id}/cancel", {
      params: { path: { launch_id: "l1" } },
      body: { expected_version: 3 },
    });
  });
});
