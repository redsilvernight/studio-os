import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import { createClaim, listClaims, newIdempotencyKey, releaseClaim, renewClaim } from "./claimsApi";

type Fake = Record<"GET" | "POST" | "DELETE", ReturnType<typeof vi.fn>>;
const fakeClient = (impl: Fake): StudioClient => impl as unknown as StudioClient;

const ok = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 200 } as Response,
});

const created = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 201 } as Response,
});

const noContent = (): { data?: undefined; error?: undefined; response: Response } => ({
  response: { ok: true, status: 204 } as Response,
});

const fail = (status: number, error: unknown): { data?: undefined; error: unknown; response: Response } => ({
  error,
  response: { ok: false, status } as Response,
});

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

describe("newIdempotencyKey", () => {
  it("generates a fresh UUID per attempt", () => {
    const a = newIdempotencyKey();
    const b = newIdempotencyKey();
    expect(a).toMatch(UUID_RE);
    expect(a).not.toBe(b);
  });
});

describe("listClaims", () => {
  it("filters by project server-side", async () => {
    const GET = vi.fn().mockResolvedValue(ok([]));
    await listClaims(fakeClient({ GET, POST: vi.fn(), DELETE: vi.fn() }), "proj-1");
    expect(GET).toHaveBeenCalledWith("/api/v1/claims", { params: { query: { project_id: "proj-1" } } });
  });
});

describe("createClaim", () => {
  const input = {
    project_id: "p",
    task_id: null,
    resource_path: "a/b.txt",
    resource_type: "file" as const,
    ttl_seconds: 3600,
  };

  it("sends the Idempotency-Key header with the body", async () => {
    const POST = vi.fn().mockResolvedValue(created({ id: "c1" }));
    await createClaim(fakeClient({ GET: vi.fn(), POST, DELETE: vi.fn() }), input, "key-1");
    expect(POST).toHaveBeenCalledWith("/api/v1/claims", {
      params: { header: { "Idempotency-Key": "key-1" } },
      body: input,
    });
  });

  it("resolves on 201 even for an overlapping path (soft-lock, never a client 409)", async () => {
    // Same path twice: the server decides (201 + conflict event), the client
    // must not pre-reject overlaps.
    const POST = vi.fn().mockResolvedValue(created({ id: "c2" }));
    const claim = await createClaim(fakeClient({ GET: vi.fn(), POST, DELETE: vi.fn() }), input);
    expect(claim.id).toBe("c2");
    expect(POST).toHaveBeenCalledTimes(1);
  });

  it("maps 403 for writers without ownership", async () => {
    const POST = vi.fn().mockResolvedValue(fail(403, { detail: { error_code: "forbidden" } }));
    await expect(createClaim(fakeClient({ GET: vi.fn(), POST, DELETE: vi.fn() }), input)).rejects.toMatchObject({
      status: 403,
      errorCode: "forbidden",
    });
  });
});

describe("renewClaim / releaseClaim", () => {
  it("renews through POST .../renew", async () => {
    const POST = vi.fn().mockResolvedValue(ok({ id: "c1" }));
    await renewClaim(fakeClient({ GET: vi.fn(), POST, DELETE: vi.fn() }), "c1");
    expect(POST).toHaveBeenCalledWith("/api/v1/claims/{claim_id}/renew", { params: { path: { claim_id: "c1" } } });
  });

  it("treats 204 as success with no body", async () => {
    const DELETE = vi.fn().mockResolvedValue(noContent());
    await expect(
      releaseClaim(fakeClient({ GET: vi.fn(), POST: vi.fn(), DELETE }), "c1"),
    ).resolves.toBeUndefined();
    expect(DELETE).toHaveBeenCalledWith("/api/v1/claims/{claim_id}", { params: { path: { claim_id: "c1" } } });
  });

  it("maps 404 on unknown claim", async () => {
    const DELETE = vi.fn().mockResolvedValue(fail(404, { detail: "claim not found" }));
    await expect(releaseClaim(fakeClient({ GET: vi.fn(), POST: vi.fn(), DELETE }), "nope")).rejects.toMatchObject({
      status: 404,
    });
  });
});
