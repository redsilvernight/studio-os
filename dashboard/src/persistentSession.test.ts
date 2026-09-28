// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearToken, getToken } from "./auth";
import {
  acceptTokens,
  configurePersistentSession,
  endPersistentSession,
  persistentSessionAvailable,
  refreshSession,
  resumeSession,
} from "./persistentSession";
import type { SessionVault } from "./platform/types";

const realFetch = globalThis.fetch;

function memoryVault(initial: string | null = null, storeOk = true): SessionVault & { value: string | null } {
  const vault = {
    value: initial,
    load: vi.fn(async () => vault.value),
    store: vi.fn(async (secret: string) => {
      if (storeOk) vault.value = secret;
      return storeOk;
    }),
    clear: vi.fn(async () => {
      vault.value = null;
      return true;
    }),
  };
  return vault;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const GRANT = { access_token: "jwt-2", expires_in: 900, refresh_token: "rt-2" };

beforeEach(() => {
  clearToken();
  vi.useFakeTimers();
});
afterEach(() => {
  configurePersistentSession(null);
  globalThis.fetch = realFetch;
  vi.useRealTimers();
  clearToken();
});

describe("persistentSession", () => {
  it("web (no vault): never persistent, nothing to resume", async () => {
    configurePersistentSession(null);
    globalThis.fetch = vi.fn();
    expect(persistentSessionAvailable()).toBe(false);
    expect(await resumeSession()).toBe(false);
    expect(globalThis.fetch).not.toHaveBeenCalled();
    expect(await acceptTokens({ access_token: "jwt", refresh_token: "rt" })).toBe(true);
    expect(getToken()).toBe("jwt");
  });

  it("resumes from the vault and keeps the rotated token", async () => {
    const vault = memoryVault("rt-1");
    configurePersistentSession(vault);
    const fetch = vi.fn(async () => json(200, GRANT));
    globalThis.fetch = fetch as unknown as typeof globalThis.fetch;
    expect(await resumeSession()).toBe(true);
    expect(getToken()).toBe("jwt-2");
    expect(vault.value).toBe("rt-2");
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/auth\/refresh$/);
    expect(JSON.parse(String(init.body))).toEqual({ refresh_token: "rt-1" });
  });

  it("rotations are single-flight: a consumed token is never presented twice", async () => {
    configurePersistentSession(memoryVault("rt-1"));
    const fetch = vi.fn(async () => json(200, GRANT));
    globalThis.fetch = fetch as unknown as typeof globalThis.fetch;
    const outcomes = await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
    expect(outcomes).toEqual(["refreshed", "refreshed", "refreshed"]);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("a refused refresh forgets the token", async () => {
    const vault = memoryVault("rt-1");
    configurePersistentSession(vault);
    globalThis.fetch = vi.fn(async () => json(401, { detail: "invalid" })) as unknown as typeof globalThis.fetch;
    expect(await refreshSession()).toBe("refused");
    expect(vault.value).toBeNull();
    expect(getToken()).toBeNull();
  });

  it("an unreachable or busy server keeps the token for later", async () => {
    const vault = memoryVault("rt-1");
    configurePersistentSession(vault);
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("offline");
    }) as unknown as typeof globalThis.fetch;
    expect(await refreshSession()).toBe("unreachable");
    globalThis.fetch = vi.fn(async () => json(503, {})) as unknown as typeof globalThis.fetch;
    expect(await refreshSession()).toBe("unreachable");
    expect(vault.value).toBe("rt-1");
  });

  it("renews the JWT before it expires", async () => {
    const vault = memoryVault();
    configurePersistentSession(vault);
    const fetch = vi.fn(async () => json(200, { ...GRANT, access_token: "jwt-3", refresh_token: "rt-3" }));
    globalThis.fetch = fetch as unknown as typeof globalThis.fetch;
    await acceptTokens({ access_token: "jwt-1", expires_in: 900, refresh_token: "rt-1" });
    expect(vault.value).toBe("rt-1");
    await vi.advanceTimersByTimeAsync(839_000);
    expect(fetch).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(getToken()).toBe("jwt-3");
    expect(vault.value).toBe("rt-3");
  });

  it("a token the vault could not keep does not survive", async () => {
    const vault = memoryVault("rt-old", false);
    configurePersistentSession(vault);
    await acceptTokens(GRANT);
    expect(vault.clear).toHaveBeenCalled();
    expect(vault.value).toBeNull();
  });

  it("sign-out revokes the session then forgets it, even offline", async () => {
    const vault = memoryVault("rt-1");
    configurePersistentSession(vault);
    const fetch = vi.fn(async () => new Response(null, { status: 204 }));
    globalThis.fetch = fetch as unknown as typeof globalThis.fetch;
    await endPersistentSession();
    expect(vault.value).toBeNull();
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/auth\/logout$/);
    expect(JSON.parse(String(init.body))).toEqual({ refresh_token: "rt-1" });

    vault.value = "rt-2";
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("offline");
    }) as unknown as typeof globalThis.fetch;
    await endPersistentSession();
    expect(vault.value).toBeNull();
  });
});
