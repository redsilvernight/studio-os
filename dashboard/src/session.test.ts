import { afterEach, describe, expect, it, vi } from "vitest";
import { observedFetch, setApiObserver } from "./apiEvents";
import { clearToken, hasToken, setToken } from "./auth";
import { SESSION_ENDED_NOTICE, createSessionEndHandler } from "./session";

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  setApiObserver(null);
  clearToken();
});

describe("createSessionEndHandler", () => {
  it("signs out once with an explicit notice, whatever the number of refused calls", async () => {
    const backToLogin = vi.fn();
    setApiObserver({ unauthorized: createSessionEndHandler(backToLogin) });
    globalThis.fetch = vi.fn(async () => new Response("", { status: 401 })) as unknown as typeof fetch;
    setToken("jwt");
    const signedIn = { headers: { Authorization: "Bearer jwt" } };

    await Promise.all([
      observedFetch("https://x.example/a", signedIn),
      observedFetch("https://x.example/b", signedIn),
      observedFetch("https://x.example/c", signedIn),
    ]);

    expect(hasToken()).toBe(false);
    expect(backToLogin).toHaveBeenCalledTimes(1);
    expect(backToLogin).toHaveBeenCalledWith(SESSION_ENDED_NOTICE);
  });

  it("does nothing once signed out", () => {
    const backToLogin = vi.fn();
    createSessionEndHandler(backToLogin)();
    expect(backToLogin).not.toHaveBeenCalled();
  });
});
