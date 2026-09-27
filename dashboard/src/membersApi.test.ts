import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import { ApiError } from "./api";
import { grantMember, listMembers, revokeMember, searchUsers } from "./membersApi";

type Fake = Record<"GET" | "PUT" | "DELETE", ReturnType<typeof vi.fn>>;
const fakeClient = (impl: Partial<Fake>): StudioClient =>
  ({ GET: vi.fn(), PUT: vi.fn(), DELETE: vi.fn(), ...impl }) as unknown as StudioClient;

const reply = <T>(status: number, data?: T, error?: unknown) => ({
  data,
  error,
  response: { ok: status < 400, status } as Response,
});

const P = "11111111-2222-4333-8444-555555555555";
const U = "aaaaaaaa-0000-4111-8111-000000000001";
const member = { project_id: P, user_id: U, granted_by_user_id: null, created_at: "2026-09-25T10:00:00Z" };
const path = { params: { path: { project_id: P, user_id: U } } };

describe("searchUsers", () => {
  it("queries the admin directory with a bounded limit", async () => {
    const found = [{ id: U, display_name: "Dev", email: "dev@example.test" }];
    const GET = vi.fn().mockResolvedValue(reply(200, found));
    await expect(searchUsers(fakeClient({ GET }), "dev")).resolves.toEqual(found);
    expect(GET).toHaveBeenCalledWith("/api/v1/users", { params: { query: { q: "dev", limit: 20 } } });
  });

  it("surfaces the admin-only 403 as an ApiError", async () => {
    const GET = vi.fn().mockResolvedValue(reply(403, undefined, { detail: "forbidden" }));
    await expect(searchUsers(fakeClient({ GET }), "")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("listMembers", () => {
  it("reads the project's memberships", async () => {
    const GET = vi.fn().mockResolvedValue(reply(200, [member]));
    await expect(listMembers(fakeClient({ GET }), P)).resolves.toEqual([member]);
    expect(GET).toHaveBeenCalledWith("/api/v1/projects/{project_id}/members", {
      params: { path: { project_id: P } },
    });
  });

  it("surfaces the admin-only 403 as an ApiError", async () => {
    const GET = vi.fn().mockResolvedValue(reply(403, undefined, { detail: { error_code: "forbidden" } }));
    await expect(listMembers(fakeClient({ GET }), P)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("grantMember", () => {
  it("tells a new membership (201) from an existing one (200)", async () => {
    const created = vi.fn().mockResolvedValue(reply(201, member));
    await expect(grantMember(fakeClient({ PUT: created }), P, U)).resolves.toEqual({ member, created: true });
    expect(created).toHaveBeenCalledWith("/api/v1/projects/{project_id}/members/{user_id}", path);

    const existing = vi.fn().mockResolvedValue(reply(200, member));
    await expect(grantMember(fakeClient({ PUT: existing }), P, U)).resolves.toEqual({ member, created: false });
  });

  it("rejects an unknown project or user (404)", async () => {
    const PUT = vi.fn().mockResolvedValue(reply(404, undefined, { detail: { error_code: "not_found" } }));
    await expect(grantMember(fakeClient({ PUT }), P, U)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("revokeMember", () => {
  it("accepts the idempotent 204", async () => {
    const DELETE = vi.fn().mockResolvedValue(reply(204));
    await expect(revokeMember(fakeClient({ DELETE }), P, U)).resolves.toBeUndefined();
    expect(DELETE).toHaveBeenCalledWith("/api/v1/projects/{project_id}/members/{user_id}", path);
  });

  it("throws on a 403", async () => {
    const DELETE = vi.fn().mockResolvedValue(reply(403, undefined, { detail: { error_code: "forbidden" } }));
    await expect(revokeMember(fakeClient({ DELETE }), P, U)).rejects.toBeInstanceOf(ApiError);
  });
});
