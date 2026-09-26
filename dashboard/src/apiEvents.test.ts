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

  it("reports an expired session only for a 401 on the current token", async () => {
    const seen: string[] = [];
    const bearer = (token: string): RequestInit => ({ headers: { Authorization: `Bearer ${token}` } });
    setApiObserver({ unauthorized: () => seen.push("401") });
    stubFetch(async () => new Response("", { status: 401 }));
    await observedFetch("https://x.example/a", bearer("t"));
    expect(seen).toEqual([]);
    setToken("t");
    await observedFetch("https://x.example/login");
    expect(seen).toEqual([]);
    await observedFetch("https://x.example/a", bearer("old"));
    expect(seen).toEqual([]);
    await observedFetch("https://x.example/a", bearer("t"));
    await observedFetch(new Request("https://x.example/b", bearer("t")));
    expect(seen).toEqual(["401", "401"]);
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

  it("surfaces the C1 advisory header on a successful answer", async () => {
    const seen: string[] = [];
    setApiObserver({ clientUpdate: (latest) => seen.push(latest) });
    stubFetch(
      async () =>
        new Response("", {
          status: 200,
          headers: { "x-studio-client-update": "recommended", "x-studio-client-latest": "0.2.0" },
        }),
    );
    await observedFetch("https://x.example/api/v1/projects");
    expect(seen).toEqual(["0.2.0"]);
  });

  it("parses a 426 into an upgrade-required signal without consuming the body", async () => {
    const seen: unknown[] = [];
    setApiObserver({ upgradeRequired: (info) => seen.push(info) });
    stubFetch(
      async () =>
        new Response(
          JSON.stringify({
            detail: {
              error_code: "client_upgrade_required",
              client: "dashboard",
              client_version: "0.0.9",
              minimum_supported: "0.1.0",
              latest: "0.2.0",
              message: "Trop ancien.",
            },
          }),
          { status: 426, headers: { "content-type": "application/json" } },
        ),
    );
    const response = await observedFetch("https://x.example/api/v1/projects");
    expect(response.status).toBe(426);
    expect(seen).toHaveLength(1);
    expect((seen[0] as { client: string }).client).toBe("dashboard");
    // The caller can still read the body: the signal used a clone.
    expect((await response.json()).detail.error_code).toBe("client_upgrade_required");
  });
});
