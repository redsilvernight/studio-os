// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiBaseUrl, createApiClient } from "./api";
import { clearToken } from "./auth";
import { resolveApiUrl } from "./config";
import { currentStatus, getDesktopShell, prepareDesktop, resetDesktopShellForTests } from "./desktopShell";
import { renderLogin } from "./login";
import { fetchCanonicalMachines } from "./machinesApi";
import { fakeDesktop } from "./testSupport/fakeDesktop";
import { connectEventStream } from "./sse";
import { checkHealth } from "./views/overview";

const realFetch = globalThis.fetch;
const flush = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
};

let network: ReturnType<typeof vi.fn>;

beforeEach(async () => {
  document.body.innerHTML = '<header class="app-topbar"><span id="token-state"></span></header>';
  clearToken();
  network = vi.fn(async () => new Response("{}", { status: 200 }));
  globalThis.fetch = network as unknown as typeof fetch;
  await prepareDesktop(fakeDesktop());
  await flush();
  network.mockClear();
});
afterEach(() => {
  resetDesktopShellForTests();
  globalThis.fetch = realFetch;
  clearToken();
});

describe("Desktop network guard: no server address configured", () => {
  it("has no effective server address", () => {
    expect(apiBaseUrl()).toBe("");
    expect(currentStatus()?.reason).toBe("server_unreachable");
  });

  it("login never reaches the network", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    renderLogin(root, () => undefined);
    (root.querySelector("#login-email") as HTMLInputElement).value = "a@b.c";
    (root.querySelector("#login-password") as HTMLInputElement).value = "secret";
    root.querySelector("form")?.dispatchEvent(new Event("submit", { cancelable: true }));
    await flush();
    expect(network).not.toHaveBeenCalled();
    expect(root.querySelector("#login-error")?.textContent).toContain("injoignable");
  });

  it("the event stream never reaches the network", async () => {
    const onError = vi.fn();
    await connectEventStream("", "t", "p", { onMessage: vi.fn(), onError, onClose: vi.fn() });
    expect(network).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalled();
  });

  it("machines never reach the network", async () => {
    await expect(fetchCanonicalMachines("", "t")).rejects.toBeInstanceOf(TypeError);
    expect(network).not.toHaveBeenCalled();
  });

  it("the overview health probe reports unreachable without a request", async () => {
    expect(await checkHealth("")).toEqual({ reachable: false });
    expect(network).not.toHaveBeenCalled();
  });

  it("the shell /healthz probe never reaches the network", async () => {
    await getDesktopShell()?.monitor.check();
    expect(network).not.toHaveBeenCalled();
    expect(currentStatus()?.reason).toBe("server_unreachable");
  });

  it("openapi-fetch requests, resolved against tauri.localhost, are refused", async () => {
    const client = createApiClient(resolveApiUrl(apiBaseUrl()));
    await expect(client.GET("/api/v1/projects" as never, {} as never)).rejects.toBeInstanceOf(TypeError);
    expect(network).not.toHaveBeenCalled();
  });

  it("nothing ever targets the Desktop origin", async () => {
    await checkHealth("").catch(() => undefined);
    await fetchCanonicalMachines("", "t").catch(() => undefined);
    for (const call of network.mock.calls) {
      expect(String(call[0])).not.toContain("tauri.localhost");
    }
    expect(network).not.toHaveBeenCalled();
  });
});
