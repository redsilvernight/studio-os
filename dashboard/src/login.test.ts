// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getToken, clearToken } from "./auth";
import { LOGIN_MESSAGES, renderLogin } from "./login";
import { prepareDesktop, resetDesktopShellForTests } from "./desktopShell";
import { fakeDesktop } from "./testSupport/fakeDesktop";
import { setServerOriginOverride } from "./runtimeConfig";

const realFetch = globalThis.fetch;
const flush = async (): Promise<void> => {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
};

function mount(options?: Parameters<typeof renderLogin>[2], onLogin: () => void = () => undefined): HTMLElement {
  const root = document.createElement("div");
  document.body.append(root);
  renderLogin(root, onLogin, options);
  return root;
}

function submit(root: HTMLElement): void {
  root.querySelector<HTMLInputElement>("#login-email")!.value = "a@b.c";
  root.querySelector<HTMLInputElement>("#login-password")!.value = "secret";
  root.querySelector("#login-form")!.dispatchEvent(new Event("submit", { cancelable: true }));
}

beforeEach(() => {
  document.body.innerHTML = "";
  clearToken();
});
afterEach(() => {
  globalThis.fetch = realFetch;
  setServerOriginOverride(null);
  resetDesktopShellForTests();
  clearToken();
});

describe("login", () => {
  it("web: no server line, no notice", () => {
    const root = mount();
    expect(root.querySelector("[data-testid=login-server]")).toBeNull();
    expect(root.querySelector("[data-testid=login-notice]")).toBeNull();
  });

  it("stores the token on success", async () => {
    globalThis.fetch = vi.fn(
      async () => new Response(JSON.stringify({ access_token: "jwt" }), { status: 200 }),
    ) as unknown as typeof fetch;
    const onLogin = vi.fn();
    const root = mount(undefined, onLogin);
    submit(root);
    await flush();
    expect(getToken()).toBe("jwt");
    expect(onLogin).toHaveBeenCalled();
  });

  it("shows an understandable message, not a crash, when the server is unreachable", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;
    const root = mount();
    submit(root);
    await flush();
    const error = root.querySelector<HTMLElement>("#login-error")!;
    expect(error.hidden).toBe(false);
    expect(error.textContent).toContain("Serveur injoignable");
    const button = root.querySelector<HTMLButtonElement>("#login-form button[type=submit]")!;
    expect(button.disabled).toBe(false);
    expect(getToken()).toBeNull();
  });

  it.each([
    [401, LOGIN_MESSAGES.invalid],
    [429, LOGIN_MESSAGES.rateLimited],
    [500, LOGIN_MESSAGES.failed],
  ])("HTTP %i: fixed French message, never the server's text", async (status, message) => {
    globalThis.fetch = vi.fn(
      async () => new Response(JSON.stringify({ detail: "invalid email or password" }), { status }),
    ) as unknown as typeof fetch;
    const root = mount();
    submit(root);
    await flush();
    expect(root.querySelector("#login-error")?.textContent).toBe(message);
  });

  it("offers account creation and recovery only when wired", () => {
    expect(mount().querySelector("[data-testid=login-account-links]")).toBeNull();
    const onAccountAction = vi.fn();
    const root = mount({ onAccountAction });
    root.querySelector<HTMLAnchorElement>("a[data-account-action=register]")!.click();
    root.querySelector<HTMLAnchorElement>("a[data-account-action=forgot]")!.click();
    expect(onAccountAction.mock.calls).toEqual([["register"], ["forgot"]]);
  });

  it("shows the reason the user came back (expired session)", () => {
    const root = mount({ notice: "Votre session a expiré." });
    expect(root.querySelector("[data-testid=login-notice]")?.textContent).toBe("Votre session a expiré.");
  });
});

describe("login (Desktop)", () => {
  it("shows the server in use and an explicit Modifier control", () => {
    setServerOriginOverride("https://studio.example.com");
    const root = mount({ desktop: true });
    expect(root.querySelector("[data-testid=login-server-effective]")?.textContent).toBe("https://studio.example.com");
    expect(root.querySelector<HTMLFormElement>("#login-server-form")?.hidden).toBe(true);
    root.querySelector<HTMLButtonElement>("#login-server-edit")!.click();
    expect(root.querySelector<HTMLFormElement>("#login-server-form")?.hidden).toBe(false);
  });

  it("without any server address: unreachable message, no request to the Desktop origin", async () => {
    const fetchSpy = vi.fn(async () => new Response("{}", { status: 200 }));
    globalThis.fetch = fetchSpy as unknown as typeof fetch;
    await prepareDesktop(fakeDesktop());
    await flush();
    fetchSpy.mockClear();
    const root = mount({ desktop: true });
    submit(root);
    await flush();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(root.querySelector("#login-error")?.textContent).toContain("Serveur injoignable");
    expect(getToken()).toBeNull();
  });
});
