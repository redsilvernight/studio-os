import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import { createProject, createTask, decodeJwtSubject, isUuid } from "./creationsApi";

type Fake = Record<"POST", ReturnType<typeof vi.fn>>;
const fakeClient = (impl: Fake): StudioClient => impl as unknown as StudioClient;

const created = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 201 } as Response,
});

describe("createProject", () => {
  it("sends the Idempotency-Key header and the body", async () => {
    const POST = vi.fn().mockResolvedValue(created({ id: "p1", slug: "s" }));
    await createProject(fakeClient({ POST }), { slug: "s", name: "N", description: null }, "key-1");
    expect(POST).toHaveBeenCalledWith("/api/v1/projects", {
      params: { header: { "Idempotency-Key": "key-1" } },
      body: { slug: "s", name: "N", description: null },
    });
  });
});

describe("createTask", () => {
  it("posts to /tasks with the project id", async () => {
    const POST = vi.fn().mockResolvedValue(created({ id: "t1" }));
    await createTask(fakeClient({ POST }), { project_id: "p1", title: "T", description: null }, "key-2");
    expect(POST).toHaveBeenCalledWith("/api/v1/tasks", {
      params: { header: { "Idempotency-Key": "key-2" } },
      body: { project_id: "p1", title: "T", description: null },
    });
  });
});

function jwtWith(payload: Record<string, unknown>): string {
  const encoded = btoa(JSON.stringify(payload)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `header.${encoded}.signature`;
}

describe("decodeJwtSubject", () => {
  it("reads the user id out of a dashboard JWT", () => {
    const sub = "11111111-2222-4333-8444-555555555555";
    expect(decodeJwtSubject(jwtWith({ sub, role: "admin" }))).toBe(sub);
  });

  it("returns null for an opaque machine token or a malformed JWT", () => {
    expect(decodeJwtSubject("opaque-machine-token")).toBeNull();
    expect(decodeJwtSubject("a.b.c")).toBeNull();
    expect(decodeJwtSubject(null)).toBeNull();
    expect(decodeJwtSubject(jwtWith({ role: "admin" }))).toBeNull();
  });
});


describe("isUuid", () => {
  it("accepts UUIDs and rejects anything else", () => {
    expect(isUuid("11111111-2222-4333-8444-555555555555")).toBe(true);
    expect(isUuid(" 11111111-2222-4333-8444-555555555555 ")).toBe(true);
    expect(isUuid("not-a-uuid")).toBe(false);
    expect(isUuid("")).toBe(false);
  });
});
