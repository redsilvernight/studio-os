// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearToken, setToken } from "./auth";
import { apiBaseUrl } from "./api";
import { observedFetch } from "./apiEvents";
import {
  refreshDaemon,
  currentStatus,
  getDesktopShell,
  paintShellStatus,
  prepareDesktop,
  resetDesktopShellForTests,
  setDesktopHooks,
} from "./desktopShell";
import type { BridgeAnswer } from "./platform/contracts";
import { INFO, fakeDaemon, fakeDesktop, notSupported } from "./testSupport/fakeDesktop";
import { daemonLabel } from "./shellStatus";
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
    await observedFetch("https://x.example/api", { headers: { Authorization: "Bearer t" } });
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
    // The handshake always comes first; a refused handshake stops the reads.
    expect((seen[0] as unknown[])[0]).toBe("runtime.handshake");
    expect(seen).toHaveLength(1);
  });

  describe("P3 ↔ P4: handshake, status, health", () => {
    const STUDIO = { configured: "https://studio.example.com", applied: "https://studio.example.com", restart_required: false };
    const boot = async (
      daemon: ReturnType<typeof fakeDaemon>,
      info: Partial<{ sidecar: unknown }> = {},
    ) => {
      stubFetch(async () => new Response("ok", { status: 200 }));
      await prepareDesktop(
        fakeDesktop(
          {
            request: daemon.request,
            desktopInfo: async () => ({ ...INFO, ...info }) as unknown as typeof INFO,
          },
          STUDIO,
        ),
      );
      await flush();
      return getDesktopShell()!;
    };

    it("negotiates before status, then reads health when daemon.health was granted", async () => {
      const daemon = fakeDaemon({ git_watchers: [{ condition: "healthy" }, { condition: "offline" }] });
      const shell = await boot(daemon);
      expect(daemon.calls.slice(0, 3)).toEqual(["runtime.handshake", "daemon.status", "daemon.health"]);
      expect(shell.daemon).toMatchObject({
        kind: "state",
        state: "running",
        health: { heartbeat: "healthy", outboxReplay: "healthy", gitWatchers: { total: 2, healthy: 1 } },
      });
      expect(currentStatus()?.reason).toBe("connected");
    });

    it("an older daemon without daemon.health stays compatible: no health request, health absent", async () => {
      const daemon = fakeDaemon({ offers: ["daemon.control", "identity.view"] });
      const shell = await boot(daemon);
      expect(daemon.calls).not.toContain("daemon.health");
      expect(shell.daemon).toEqual({ kind: "state", state: "running" });
      expect(currentStatus()?.reason).toBe("connected");
    });

    it("a daemon restart forgets the grant: the next refresh negotiates again", async () => {
      const daemon = fakeDaemon();
      const shell = await boot(daemon);
      daemon.restart();
      await refreshDaemon(shell);
      expect(shell.daemon.kind).toBe("state");
      expect(daemon.calls.filter((c) => c === "runtime.handshake")).toHaveLength(2);
      expect(daemon.calls).not.toContain("capability_missing");
    });

    it.each([
      ["starting", "daemon_recovering", "Assistant local en démarrage"],
      ["recovering", "daemon_recovering", "Assistant local en reprise"],
      ["unavailable", "daemon_unavailable", "Assistant local indisponible"],
      ["crashed", "daemon_unavailable", "Assistant local indisponible"],
      ["incompatible", "protocol_incompatible", "Version incompatible"],
    ] as const)("presents the daemon state %s", async (state, reason, label) => {
      const shell = await boot(fakeDaemon({ state }));
      expect(shell.daemon).toMatchObject({ kind: "state", state });
      expect(currentStatus()).toMatchObject({ reason, label });
    });

    it("a refused handshake is shown as an incompatible version", async () => {
      const shell = await boot(fakeDaemon({ refuse: "daemon_too_old" }));
      expect(shell.daemon).toEqual({ kind: "error", code: "protocol_incompatible" });
      expect(currentStatus()?.reason).toBe("protocol_incompatible");
    });

    it("the supervisor giving up is an abandoned daemon, not a generic error", async () => {
      const unavailable = { ok: false, error: { code: "daemon_crashed" } } as unknown as BridgeAnswer;
      stubFetch(async () => new Response("ok", { status: 200 }));
      await prepareDesktop(
        fakeDesktop(
          {
            request: async () => unavailable,
            desktopInfo: async () => ({ ...INFO, sidecar: { state: "abandoned", attempts: 3 } }) as never,
          },
          STUDIO,
        ),
      );
      await flush();
      expect(getDesktopShell()!.daemon).toEqual({ kind: "error", code: "daemon_abandoned" });
      expect(currentStatus()?.reason).toBe("daemon_unavailable");
      expect(daemonLabel(getDesktopShell()!.daemon)).toBe("Abandonné après plusieurs arrêts");
    });

    it("a supervised restart in progress is recovering, not an alarm", async () => {
      const unavailable = { ok: false, error: { code: "daemon_crashed" } } as unknown as BridgeAnswer;
      stubFetch(async () => new Response("ok", { status: 200 }));
      await prepareDesktop(
        fakeDesktop(
          {
            request: async () => unavailable,
            desktopInfo: async () => ({ ...INFO, sidecar: { state: "recovering", attempts: 1 } }) as never,
          },
          STUDIO,
        ),
      );
      await flush();
      expect(currentStatus()).toMatchObject({ level: "info", reason: "daemon_recovering" });
    });
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
