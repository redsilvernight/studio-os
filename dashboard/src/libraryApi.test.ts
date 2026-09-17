import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import { ApiError } from "./api";
import {
  activateLibraryVersion,
  createLibraryLock,
  createLibraryResource,
  createLibraryVersion,
  deprecateLibraryResource,
  getLibraryResource,
  listLibraryLocks,
  listLibraryResources,
  listLibraryVersions,
  releaseLibraryLock,
} from "./libraryApi";

type Fake = Record<"GET" | "POST" | "DELETE", ReturnType<typeof vi.fn>>;
const fakeClient = (impl: Fake): StudioClient => impl as unknown as StudioClient;
const emptyFake = (): Fake => ({ GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn() });

const ok = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 200 } as Response,
});
const created = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 201 } as Response,
});
const fail = (status: number, error: unknown): { data?: undefined; error: unknown; response: Response } => ({
  error,
  response: { ok: false, status } as Response,
});

describe("listLibraryResources", () => {
  it("sends kind/scope/project/limit/offset as query", async () => {
    const GET = vi.fn().mockResolvedValue(ok([]));
    await listLibraryResources(fakeClient({ ...emptyFake(), GET }), {
      kind: "workflow",
      scope: "project",
      projectId: "p1",
      limit: 10,
      offset: 5,
    });
    expect(GET).toHaveBeenCalledWith("/api/v1/library", {
      params: { query: { kind: "workflow", scope: "project", project_id: "p1", limit: 10, offset: 5 } },
    });
  });

  it("omits unset filters", async () => {
    const GET = vi.fn().mockResolvedValue(ok([]));
    await listLibraryResources(fakeClient({ ...emptyFake(), GET }));
    expect(GET).toHaveBeenCalledWith("/api/v1/library", { params: { query: {} } });
  });
});

describe("getLibraryResource / listLibraryVersions", () => {
  it("reads by canonical UUID", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ id: "r1" }));
    await getLibraryResource(fakeClient({ ...emptyFake(), GET }), "r1");
    expect(GET).toHaveBeenCalledWith("/api/v1/library/{resource_id}", { params: { path: { resource_id: "r1" } } });
  });

  it("lists versions oldest-first route", async () => {
    const GET = vi.fn().mockResolvedValue(ok([]));
    await listLibraryVersions(fakeClient({ ...emptyFake(), GET }), "r1");
    expect(GET).toHaveBeenCalledWith("/api/v1/library/{resource_id}/versions", {
      params: { path: { resource_id: "r1" } },
    });
  });
});

describe("createLibraryResource", () => {
  const input = {
    kind: "rule" as const,
    stable_key: "coding-standard",
    scope: "studio" as const,
    title: "Coding standard",
    content: { content_schema: "studio.library.rule/v1", text: "x" },
    dependencies: [],
  };

  it("sends the Idempotency-Key header with the typed body", async () => {
    const POST = vi.fn().mockResolvedValue(created({ id: "r1" }));
    await createLibraryResource(fakeClient({ ...emptyFake(), POST }), input, "key-1");
    expect(POST).toHaveBeenCalledWith("/api/v1/library", {
      params: { header: { "Idempotency-Key": "key-1" } },
      body: input,
    });
  });

  it("surfaces invalid_content 422", async () => {
    const POST = vi.fn().mockResolvedValue(fail(422, { detail: { error_code: "invalid_content" } }));
    await expect(createLibraryResource(fakeClient({ ...emptyFake(), POST }), input, "k")).rejects.toMatchObject({
      status: 422,
      errorCode: "invalid_content",
    });
  });
});

describe("createLibraryVersion / activate / deprecate", () => {
  it("posts a new draft version with an Idempotency-Key", async () => {
    const POST = vi.fn().mockResolvedValue(created({ version: 2 }));
    const body = { title: "v2", content: {}, dependencies: [] };
    await createLibraryVersion(fakeClient({ ...emptyFake(), POST }), "r1", body, "key-2");
    expect(POST).toHaveBeenCalledWith("/api/v1/library/{resource_id}/versions", {
      params: { path: { resource_id: "r1" }, header: { "Idempotency-Key": "key-2" } },
      body,
    });
  });

  it("activates an explicit version with the optimistic revision", async () => {
    const POST = vi.fn().mockResolvedValue(ok({ id: "r1", active_version: 3 }));
    await activateLibraryVersion(fakeClient({ ...emptyFake(), POST }), "r1", { version: 3, expected_resource_version: 4 }, "k");
    expect(POST).toHaveBeenCalledWith("/api/v1/library/{resource_id}/activate", {
      params: { path: { resource_id: "r1" }, header: { "Idempotency-Key": "k" } },
      body: { version: 3, expected_resource_version: 4 },
    });
  });

  it("keeps 409 version_conflict structured and never retries", async () => {
    const POST = vi.fn().mockResolvedValue(fail(409, { detail: { error_code: "version_conflict", server_version: 7 } }));
    await expect(
      activateLibraryVersion(fakeClient({ ...emptyFake(), POST }), "r1", { version: 1, expected_resource_version: 1 }),
    ).rejects.toMatchObject({ errorCode: "version_conflict", serverVersion: 7 });
    expect(POST).toHaveBeenCalledTimes(1);
  });

  it("deprecates instead of deleting", async () => {
    const POST = vi.fn().mockResolvedValue(ok({ id: "r1", status: "deprecated" }));
    await deprecateLibraryResource(fakeClient({ ...emptyFake(), POST }), "r1", { expected_resource_version: 2 }, "k");
    expect(POST).toHaveBeenCalledWith("/api/v1/library/{resource_id}/deprecate", {
      params: { path: { resource_id: "r1" }, header: { "Idempotency-Key": "k" } },
      body: { expected_resource_version: 2 },
    });
  });
});

describe("locks", () => {
  it("lists locks filtered by project", async () => {
    const GET = vi.fn().mockResolvedValue(ok([]));
    await listLibraryLocks(fakeClient({ ...emptyFake(), GET }), "p1");
    expect(GET).toHaveBeenCalledWith("/api/v1/library-locks", { params: { query: { project_id: "p1" } } });
  });

  it("sets a lock on the canonical resource UUID", async () => {
    const POST = vi.fn().mockResolvedValue(created({ id: "l1" }));
    const body = { project_id: "p1", resource_id: "r1", locked_version: 3 };
    await createLibraryLock(fakeClient({ ...emptyFake(), POST }), body, "k");
    expect(POST).toHaveBeenCalledWith("/api/v1/library-locks", {
      params: { header: { "Idempotency-Key": "k" } },
      body,
    });
  });

  it("releases a lock via DELETE", async () => {
    const DELETE = vi.fn().mockResolvedValue(ok({ id: "l1" }));
    await releaseLibraryLock(fakeClient({ ...emptyFake(), DELETE }), "l1");
    expect(DELETE).toHaveBeenCalledWith("/api/v1/library-locks/{lock_id}", { params: { path: { lock_id: "l1" } } });
  });

  it("maps a masked 404 as a plain ApiError (no oracle)", async () => {
    const DELETE = vi.fn().mockResolvedValue(fail(404, { detail: "library lock not found" }));
    await expect(releaseLibraryLock(fakeClient({ ...emptyFake(), DELETE }), "nope")).rejects.toBeInstanceOf(ApiError);
  });
});
