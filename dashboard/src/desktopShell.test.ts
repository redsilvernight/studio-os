// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearToken, setToken } from "./auth";
import { apiBaseUrl } from "./api";
import { observedFetch } from "./apiEvents";
import {
  currentStatus,
  getDesktopShell,
  paintShellStatus,
  prepareDesktop,
  resetDesktopShellForTests,
  setDesktopHooks,
} from "./desktopShell";
import type { BridgeAnswer } from "./platform/contracts";
import { fakeDesktop, notSupported } from "./testSupport/fakeDesktop";
import { webPlatform } from "./platform/web";
import { getServerOriginOverride } from "./runtimeConfig";

const realFetch = globalThis.fetch;
const stubFetch = (impl: (url: string) => Promise<Response>): void => {
  globalThis.fetch = vi.fn((input: RequestInfo | URL) => impl(String(input))) as unknown as typeof fetch;
};
const ORIGIN = { configured: "https://s.example.com", applied: "https://s.example.com", restart_required: false };
const flush = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
};

beforeEach(() => {
  document.body.innerHTML = '<header class="app-topbar"><span id="token-state"></span></header>';
  clearToken();
});
afterEach(() => {
  resetDesktopShellForTests();
  globalThis.fetch = realFetch;
  clearToken();
});

describe("prepareDesktop", () => {
  it("does nothing in web mode: no shell, no override, no observer", async () => {
    expect(await prepareDesktop(webPlatform)).toBeNull();
    expect(getDesktopShell()).toBeNull();
    expect(getServerOriginOverride()).toBeNull();
    paintShellStatus(document);
    expect(document.querySelector("#shell-status")).toBeNull();
  });

  it("uses the origin this process allowed, not one that is merely saved", async () => {
    stubFetch(async () => new Response("ok", { status: 200 }));
    await prepareDesktop(
      fakeDesktop({}, { configured: "https://new.example.com", applied: "https://old.example.com", restart_required: true }),
    );
    expect(getServerOriginOverride()).toBe("https://old.example.com");
    expect(apiBaseUrl()).toBe("https://old.example.com");
  });

  it("probes /healthz on the effective origin and shows Connecté", async () => {
    const urls: string[] = [];
    stubFetch(async (url) => {
      urls.push(url);
      return new Response("ok", { status: 200 });
    });
    const shell = await prepareDesktop(
      fakeDesktop({}, { configured: "https://studio.example.com", applied: "https://studio.example.com", restart_required: false }),
    );
    await flush();
    expect(urls[0]).toBe("https://studio.example.com/healthz");
    expect(shell?.monitor.snapshot().state).toBe("connected");
    paintShellStatus(document);
    const pill = document.querySelector("#shell-status");
    expect(pill?.textContent).toContain("Connecté");
    expect(document.querySelector(".app-topbar")?.firstElementChild).toBe(pill);
  });

  it("shows « Serveur injoignable » for a network failure, then recovers without restart", async () => {
    stubFetch(async () => {
      throw new TypeError("Failed to fetch");
    });
    const shell = await prepareDesktop(fakeDesktop({}, ORIGIN));
    await flush();
    expect(currentStatus()?.reason).toBe("server_unreachable");
    stubFetch(async () => new Response("ok", { status: 200 }));
    await shell!.monitor.check();
    expect(currentStatus()?.reason).toBe("connected");
  });

  it("rerenders the view when the server comes back", async () => {
    stubFetch(async () => {
      throw new TypeError("offline");
    });
    const shell = await prepareDesktop(fakeDesktop({}, ORIGIN));
    await flush();
    const rerender = vi.fn();
    setDesktopHooks({ rerender, authExpired: vi.fn() });
    stubFetch(async () => new Response("ok", { status: 200 }));
    await shell!.monitor.check();
    expect(rerender).toHaveBeenCalledTimes(1);
  });

  it("sends the user back to sign-in when a signed-in call is refused (401)", async () => {
    stubFetch(async () => new Response("ok", { status: 200 }));
    await prepareDesktop(fakeDesktop({}, ORIGIN));
    await flush();
    const authExpired = vi.fn();
    setDesktopHooks({ rerender: vi.fn(), authExpired });
    setToken("t");
    stubFetch(async () => new Response("", { status: 401 }));
    await observedFetch("https://x.example/api");
    expect(authExpired).toHaveBeenCalledTimes(1);
    expect(currentStatus()?.reason).toBe("auth_expired");
  });

  it("shows the local assistant as unavailable when the P1 status says so", async () => {
    stubFetch(async () => new Response("ok", { status: 200 }));
    const unavailable = { ok: false, error: { code: "daemon_unavailable" } } as unknown as BridgeAnswer;
    const seen: unknown[] = [];
    await prepareDesktop(
      fakeDesktop(
        {
          request: async (command, payload) => {
            seen.push([command, payload]);
            return unavailable;
          },
        },
        { configured: "https://studio.example.com", applied: "https://studio.example.com", restart_required: false },
      ),
    );
    await flush();
    expect(currentStatus()?.reason).toBe("daemon_unavailable");
    expect(seen[0]).toEqual([
      "daemon.status",
      { action: "status", profile: { profile_id: "default", server_origin: "https://studio.example.com" } },
    ]);
  });

  it("without a server address: unreachable, no request at all, daemon not asked", async () => {
    const spy = vi.fn(async () => new Response("ok", { status: 200 }));
    globalThis.fetch = spy as unknown as typeof fetch;
    const request = vi.fn(async () => notSupported);
    await prepareDesktop(fakeDesktop({ request }));
    await flush();
    expect(spy).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
    expect(currentStatus()?.reason).toBe("server_unreachable");
  });

  it("without a server address: refuses even a Request already resolved against the Desktop origin", async () => {
    const spy = vi.fn(async () => new Response("ok", { status: 200 }));
    globalThis.fetch = spy as unknown as typeof fetch;
    await prepareDesktop(fakeDesktop());
    await flush();
    spy.mockClear();
    // openapi-fetch hands over a Request: a relative path is already absolute
    // (http://tauri.localhost/...) by then, so the URL alone proves nothing.
    await expect(observedFetch(new Request("http://tauri.localhost/api/v1/projects"))).rejects.toBeInstanceOf(TypeError);
    expect(spy).not.toHaveBeenCalled();
    expect(currentStatus()?.reason).toBe("server_unreachable");
  });

  it("does not ask the daemon while no server origin is effective", async () => {
    stubFetch(async () => new Response("ok", { status: 200 }));
    const request = vi.fn(async () => notSupported);
    await prepareDesktop(fakeDesktop({ request }));
    await flush();
    expect(request).not.toHaveBeenCalled();
  });

  it("flags an incompatible shell/protocol and stays usable", async () => {
    stubFetch(async () => new Response("ok", { status: 200 }));
    const shell = await prepareDesktop(
      fakeDesktop({
        desktopInfo: async () => {
          throw new Error("Desktop speaks studio.local/v2 but this Dashboard expects studio.local/v1");
        },
      }),
    );
    await flush();
    expect(shell?.compatibility).toBe("incompatible");
    expect(currentStatus()?.reason).toBe("protocol_incompatible");
  });

  it("shows a restart-required state when a saved origin is not applied yet", async () => {
    stubFetch(async () => new Response("ok", { status: 200 }));
    await prepareDesktop(fakeDesktop({}, { configured: "https://b.example.com", applied: "https://s.example.com", restart_required: true }));
    await flush();
    expect(currentStatus()?.reason).toBe("restart_required");
  });
});
