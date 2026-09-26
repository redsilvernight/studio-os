import { afterEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import { clearToken, setToken } from "./auth";
import { fetchIdentity, isAdminIdentity, resetIdentityCache } from "./identityApi";

const identity = {
  user_id: "u1",
  display_name: "Ada",
  email: "ada@example.test",
  role: "admin",
  machine_id: "m1",
};

function clientReturning(result: { ok: boolean; data?: unknown }): {
  client: StudioClient;
  GET: ReturnType<typeof vi.fn>;
} {
  const GET = vi.fn().mockResolvedValue({
    data: result.data,
    response: { ok: result.ok, status: result.ok ? 200 : 401 } as Response,
  });
  return { client: { GET } as unknown as StudioClient, GET };
}

afterEach(() => {
  clearToken();
  resetIdentityCache();
});

describe("fetchIdentity", () => {
  it("reads /auth/me once per token", async () => {
    setToken("jwt-1");
    const { client, GET } = clientReturning({ ok: true, data: identity });

    expect(await fetchIdentity(client)).toEqual(identity);
    expect(await isAdminIdentity(client)).toBe(true);
    expect(GET).toHaveBeenCalledTimes(1);
    expect(GET).toHaveBeenCalledWith("/api/v1/auth/me");

    setToken("jwt-2");
    await fetchIdentity(client);
    expect(GET).toHaveBeenCalledTimes(2);
  });

  it("returns null without a token or on an error response", async () => {
    const { client, GET } = clientReturning({ ok: false });
    expect(await fetchIdentity(client)).toBeNull();
    expect(GET).not.toHaveBeenCalled();

    setToken("jwt-1");
    expect(await isAdminIdentity(client)).toBe(false);
  });

  it("never grants admin to a non-admin role", async () => {
    setToken("jwt-1");
    const { client } = clientReturning({ ok: true, data: { ...identity, role: "developer" } });
    expect(await isAdminIdentity(client)).toBe(false);
  });
});
