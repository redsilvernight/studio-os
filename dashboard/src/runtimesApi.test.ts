import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import { getRuntime, listRuntimes, registerRuntime, revokeRuntime, updateRuntime } from "./runtimesApi";

type Fake = Record<"GET" | "POST" | "PATCH", ReturnType<typeof vi.fn>>;
const fakeClient = (impl: Fake): StudioClient => impl as unknown as StudioClient;
const emptyFake = (): Fake => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() });

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

describe("listRuntimes", () => {
  it("sends include_revoked only when asked", async () => {
    const GET = vi.fn().mockResolvedValue(ok([]));
    await listRuntimes(fakeClient({ ...emptyFake(), GET }));
    expect(GET).toHaveBeenLastCalledWith("/api/v1/runtimes", { params: { query: {} } });
    await listRuntimes(fakeClient({ ...emptyFake(), GET }), { includeRevoked: true });
    expect(GET).toHaveBeenLastCalledWith("/api/v1/runtimes", { params: { query: { include_revoked: true } } });
  });
});

describe("registerRuntime", () => {
  it("keeps refs open strings and sends an Idempotency-Key", async () => {
    const POST = vi.fn().mockResolvedValue(created({ id: "rt1" }));
    const body = {
      machine_id: null,
      harness_ref: "some-harness",
      provider_ref: "some-provider",
      model_ref: "some-model",
      capabilities: { coding: true, tools: ["shell"], local: false },
      capability_source: "declared" as const,
      runtime_metadata: {},
    };
    await registerRuntime(fakeClient({ ...emptyFake(), POST }), body, "k1");
    expect(POST).toHaveBeenCalledWith("/api/v1/runtimes", {
      params: { header: { "Idempotency-Key": "k1" } },
      body,
    });
  });
});

describe("updateRuntime", () => {
  it("nests the patch and expected_version, never flattening the contract", async () => {
    const PATCH = vi.fn().mockResolvedValue(ok({ id: "rt1", version: 2 }));
    const input = { update: { harness_ref: "h2", detach_machine: false }, expected_version: 1 };
    await updateRuntime(fakeClient({ ...emptyFake(), PATCH }), "rt1", input, "k2");
    expect(PATCH).toHaveBeenCalledWith("/api/v1/runtimes/{runtime_id}", {
      params: { path: { runtime_id: "rt1" }, header: { "Idempotency-Key": "k2" } },
      body: input,
    });
  });

  it("surfaces 409 version_conflict with the live server version", async () => {
    const PATCH = vi.fn().mockResolvedValue(fail(409, { detail: { error_code: "version_conflict", server_version: 9 } }));
    await expect(
      updateRuntime(fakeClient({ ...emptyFake(), PATCH }), "rt1", { update: { detach_machine: false }, expected_version: 3 }),
    ).rejects.toMatchObject({ errorCode: "version_conflict", serverVersion: 9 });
  });

  it("surfaces a rejected secret-looking metadata key (422)", async () => {
    const PATCH = vi.fn().mockResolvedValue(fail(422, { detail: { error_code: "invalid_runtime" } }));
    await expect(
      updateRuntime(fakeClient({ ...emptyFake(), PATCH }), "rt1", { update: { detach_machine: false }, expected_version: 1 }),
    ).rejects.toMatchObject({ status: 422, errorCode: "invalid_runtime" });
  });
});

describe("getRuntime / revokeRuntime", () => {
  it("reads and revokes by id", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ id: "rt1" }));
    await getRuntime(fakeClient({ ...emptyFake(), GET }), "rt1");
    expect(GET).toHaveBeenCalledWith("/api/v1/runtimes/{runtime_id}", { params: { path: { runtime_id: "rt1" } } });

    const POST = vi.fn().mockResolvedValue(ok({ id: "rt1", status: "revoked" }));
    await revokeRuntime(fakeClient({ ...emptyFake(), POST }), "rt1");
    expect(POST).toHaveBeenCalledWith("/api/v1/runtimes/{runtime_id}/revoke", {
      params: { path: { runtime_id: "rt1" } },
    });
  });

  it("maps a masked 404 for another user's runtime", async () => {
    const GET = vi.fn().mockResolvedValue(fail(404, { detail: "runtime not found" }));
    await expect(getRuntime(fakeClient({ ...emptyFake(), GET }), "nope")).rejects.toMatchObject({ status: 404 });
  });
});
