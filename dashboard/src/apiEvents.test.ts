import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearToken, setToken } from "./auth";
import { observedFetch, setApiObserver } from "./apiEvents";

const realFetch = globalThis.fetch;

function stubFetch(impl: () => Promise<Response>): void {
  globalThis.fetch = vi.fn(impl) as unknown as typeof fetch;
}

beforeEach(() => clearToken());
afterEach(() => {
  globalThis.fetch = realFetch;
  setApiObserver(null);
  clearToken();
});

describe("observedFetch", () => {
  it("is a transparent fetch with no observer (web build)", async () => {
    stubFetch(async () => new Response("ok", { status: 200 }));
    const res = await observedFetch("https://x.example/a");
    expect(res.status).toBe(200);
    stubFetch(async () => {
      throw new TypeError("offline");
    });
    await expect(observedFetch("https://x.example/a")).rejects.toThrow("offline");
  });

  it("reports reachable on any HTTP answer, even an error status", async () => {
    const seen: string[] = [];
    setApiObserver({ reachable: () => seen.push("reachable"), networkError: () => seen.push("net") });
    stubFetch(async () => new Response("", { status: 500 }));
    expect((await observedFetch("https://x.example/a")).status).toBe(500);
    expect(seen).toEqual(["reachable"]);
  });

  it("reports a network error and still rejects", async () => {
    const seen: string[] = [];
    setApiObserver({ reachable: () => seen.push("reachable"), networkError: () => seen.push("net") });
    stubFetch(async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(observedFetch("https://x.example/a")).rejects.toThrow("Failed to fetch");
    expect(seen).toEqual(["net"]);
  });

  it("reports an expired session only for a signed-in 401", async () => {
    const seen: string[] = [];
    setApiObserver({ unauthorized: () => seen.push("401") });
    stubFetch(async () => new Response("", { status: 401 }));
    await observedFetch("https://x.example/a");
    expect(seen).toEqual([]);
    setToken("t");
    await observedFetch("https://x.example/a");
    expect(seen).toEqual(["401"]);
  });

  it("refuses a request the observer rejects: no network call, no reachable signal", async () => {
    const seen: string[] = [];
    setApiObserver({
      refuse: (url) => !/^https?:\/\//.test(url),
      reachable: () => seen.push("reachable"),
      networkError: () => seen.push("net"),
    });
    stubFetch(async () => new Response("ok", { status: 200 }));
    await expect(observedFetch("/api/v1/projects")).rejects.toBeInstanceOf(TypeError);
    expect(globalThis.fetch).not.toHaveBeenCalled();
    expect(seen).toEqual(["net"]);
    expect((await observedFetch("https://x.example/a")).status).toBe(200);
    expect(seen).toEqual(["net", "reachable"]);
  });
});
