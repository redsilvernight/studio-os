import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import type { StudioClient } from "./api";
import { claimTask, getTask, listTasks, patchTask, releaseTask } from "./tasksApi";

type Fake = Record<"GET" | "PATCH" | "POST", ReturnType<typeof vi.fn>>;
const fakeClient = (impl: Fake): StudioClient => impl as unknown as StudioClient;

const ok = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 200 } as Response,
});

const fail = (status: number, error: unknown): { data?: undefined; error: unknown; response: Response } => ({
  error,
  response: { ok: false, status } as Response,
});

describe("listTasks", () => {
  it("sends project_id, limit and offset as query", async () => {
    const GET = vi.fn().mockResolvedValue(ok([]));
    await listTasks(fakeClient({ GET, PATCH: vi.fn(), POST: vi.fn() }), {
      projectId: "p1",
      limit: 50,
      offset: 100,
    });
    expect(GET).toHaveBeenCalledWith("/api/v1/tasks", {
      params: { query: { project_id: "p1", limit: 50, offset: 100 } },
    });
  });
});

describe("patchTask", () => {
  it("sends If-Match-Version with the known version and the patch body", async () => {
    const PATCH = vi.fn().mockResolvedValue(ok({ id: "t", version: 4 }));
    await patchTask(fakeClient({ GET: vi.fn(), PATCH, POST: vi.fn() }), "t", { status: "blocked" }, 3);
    expect(PATCH).toHaveBeenCalledWith("/api/v1/tasks/{task_id}", {
      params: { path: { task_id: "t" }, header: { "If-Match-Version": 3 } },
      body: { status: "blocked" },
    });
  });

  it("surfaces 409 version_conflict with server_version and never auto-retries", async () => {
    const PATCH = vi
      .fn()
      .mockResolvedValue(fail(409, { detail: { error_code: "version_conflict", server_version: 9 } }));
    const promise = patchTask(fakeClient({ GET: vi.fn(), PATCH, POST: vi.fn() }), "t", { title: "x" }, 3);
    await expect(promise).rejects.toMatchObject({ errorCode: "version_conflict", serverVersion: 9 });
    expect(PATCH).toHaveBeenCalledTimes(1);
  });

  it("maps 422 validation errors", async () => {
    const PATCH = vi.fn().mockResolvedValue(fail(422, { detail: "If-Match-Version missing" }));
    await expect(
      patchTask(fakeClient({ GET: vi.fn(), PATCH, POST: vi.fn() }), "t", { title: "x" }, 1),
    ).rejects.toMatchObject({ status: 422 });
  });
});

describe("claimTask / releaseTask", () => {
  it("claims through POST .../claim and surfaces already_claimed", async () => {
    const POST = vi.fn().mockResolvedValue(fail(409, { detail: { error_code: "already_claimed" } }));
    await expect(claimTask(fakeClient({ GET: vi.fn(), PATCH: vi.fn(), POST }), "t")).rejects.toMatchObject({
      errorCode: "already_claimed",
    });
    expect(POST).toHaveBeenCalledWith("/api/v1/tasks/{task_id}/claim", { params: { path: { task_id: "t" } } });
  });

  it("returns the server payload verbatim on release (no invented status change)", async () => {
    const serverTask = { id: "t", status: "in_progress", version: 6, claimed_by_machine_id: null };
    const POST = vi.fn().mockResolvedValue(ok(serverTask));
    const released = await releaseTask(fakeClient({ GET: vi.fn(), PATCH: vi.fn(), POST }), "t");
    expect(released.status).toBe("in_progress");
    expect(released.claimed_by_machine_id).toBeNull();
  });

  it("getTask maps 404", async () => {
    const GET = vi.fn().mockResolvedValue(fail(404, { detail: "task not found" }));
    await expect(getTask(fakeClient({ GET, PATCH: vi.fn(), POST: vi.fn() }), "missing")).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});
