// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearToken } from "../auth";
import { prepareDesktop, resetDesktopShellForTests } from "../desktopShell";
import type { BridgeAnswer } from "../platform/contracts";
import type { DesktopInfo } from "../platform";
import { webPlatform } from "../platform/web";
import { fakeDaemon, fakeDesktop, INFO } from "../testSupport/fakeDesktop";
import { applicationPageHtml, originRefusalMessage, renderApplication } from "./application";

const realFetch = globalThis.fetch;
const healthy = (): void => {
  globalThis.fetch = vi.fn(async () => new Response("ok", { status: 200 })) as unknown as typeof fetch;
};
const flush = async (): Promise<void> => {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
};

const info: DesktopInfo = {
  product: "Studi'OS Desktop",
  desktop_version: "0.1.0",
  mode: "desktop",
  protocol: "studio.local/v1",
  sidecar: { state: "not_started" },
};

beforeEach(() => {
  document.body.innerHTML = "";
  clearToken();
});
afterEach(() => {
  resetDesktopShellForTests();
  globalThis.fetch = realFetch;
});

describe("applicationPageHtml", () => {
  it("shows identity, version, mode and protocol in desktop mode", () => {
    const html = applicationPageHtml("desktop", info);
    expect(html).toContain("Studi'OS Desktop");
    expect(html).toContain("0.1.0");
    expect(html).toContain("Version Desktop");
    expect(html).toContain("Version studio.local");
    expect(html).toContain("studio.local/v1");
    expect(html).toContain('aria-current="page"');
  });

  it("does not claim Desktop availability in web mode and shows no native control", () => {
    const html = applicationPageHtml("web", null);
    expect(html).toContain("Web");
    expect(html).toContain("Application Desktop non utilisée");
    expect(html).not.toContain("studio.local");
    expect(html).not.toContain("Version Desktop");
    expect(html).not.toMatch(/server-origin|Redémarrer|data-action|Assistant local|Détails techniques/);
  });

  it("shows a visible error when the desktop identity cannot be read", () => {
    const html = applicationPageHtml("desktop", null, "protocole incompatible");
    expect(html).toContain('role="alert"');
    expect(html).toContain("protocole incompatible");
  });

  it("never renders a secret or token", () => {
    expect(applicationPageHtml("desktop", info)).not.toMatch(/keyring|token|password/i);
  });
});

describe("originRefusalMessage", () => {
  it("words every shell refusal in French, none empty", () => {
    for (const reason of [
      "origin_empty",
      "origin_too_long",
      "origin_invalid",
      "origin_unsupported_scheme",
      "origin_credentials_not_allowed",
      "origin_not_an_origin",
      "origin_insecure_scheme",
      "origin_is_desktop_origin",
      "storage_unavailable",
      "storage_failed",
      "unavailable",
      "failed",
    ] as const) {
      expect(originRefusalMessage(reason).length).toBeGreaterThan(10);
    }
    expect(originRefusalMessage("origin_insecure_scheme")).toContain("localhost");
  });
});

describe("Settings › Application (web)", () => {
  it("renders a coherent page with no bridge call and no native control", async () => {
    const root = document.createElement("main");
    await renderApplication(root, webPlatform);
    expect(root.textContent).toContain("Mode");
    expect(root.querySelector("form")).toBeNull();
    expect(root.querySelector("[data-action]")).toBeNull();
    expect(root.querySelector("[data-testid=diagnostics]")).toBeNull();
  });
});

describe("Settings › Application (Desktop)", () => {
  const DEFAULT_ORIGIN = { configured: null, applied: "https://studio.example.com", restart_required: false };
  async function mount(p = fakeDesktop({}, DEFAULT_ORIGIN)) {
    healthy();
    await prepareDesktop(p);
    await flush();
    const root = document.createElement("main");
    document.body.append(root);
    await renderApplication(root, p);
    return { root, p };
  }

  it("shows identity, server, assistant, compatibility and technical details", async () => {
    const { root } = await mount(
      fakeDesktop({}, { configured: "https://studio.example.com", applied: "https://studio.example.com", restart_required: false }),
    );
    const text = root.textContent ?? "";
    expect(text).toContain(INFO.desktop_version);
    expect(root.querySelector("[data-testid=server-effective]")?.textContent).toBe("https://studio.example.com");
    expect(root.querySelector("[data-testid=server-summary]")?.textContent).toBe("Connecté");
    expect(root.querySelector("[data-testid=compatibility]")?.textContent).toBe("Compatible");
    expect(root.querySelector("[data-testid=daemon-state]")?.textContent).toBe("Non disponible dans cette version");
    expect(root.querySelector("[data-testid=diagnostics]")).not.toBeNull();
  });

  it("the logs entry opens the logs folder and the export reports the file, never a secret", async () => {
    const openDataFolder = vi.fn(async () => true);
    const exportDiagnostics = vi.fn(async () => ({ ok: true as const, file: "~\\StudioOS\\diagnostics\\diagnostics-1.json" }));
    const { root } = await mount(fakeDesktop({ openDataFolder, exportDiagnostics }));
    const logs = root.querySelector<HTMLButtonElement>("[data-testid=open-logs]");
    expect(logs?.disabled).toBe(false);
    logs?.click();
    await flush();
    expect(openDataFolder).toHaveBeenCalledWith("logs");
    root.querySelector<HTMLButtonElement>("[data-testid=export-diagnostics]")?.click();
    await flush();
    expect(exportDiagnostics).toHaveBeenCalledTimes(1);
    const shown = root.querySelector("[data-testid=export-result]")?.textContent ?? "";
    expect(shown).toContain("diagnostics-1.json");
    expect(root.textContent).not.toMatch(/token|password|api[_ ]?key/i);
  });

  it("shows versions, the sidecar, optional components and where user data lives", async () => {
    const { root } = await mount();
    const text = root.querySelector("[data-testid=diagnostics]")?.textContent ?? "";
    expect(text).toContain("Version de l'assistant local");
    expect(text).toContain("Compatible");
    expect(text).toContain("Graphify : installation séparée");
    expect(text).toContain("StudioOS");
    expect(text).toContain("Version 1");
  });

  it("degrades to a sentence when the diagnostics cannot be read", async () => {
    const { root } = await mount(
      fakeDesktop({
        diagnostics: async () => {
          throw new Error("bad shape");
        },
      }),
    );
    expect(root.querySelector("[data-testid=open-logs]")).toBeNull();
    expect(root.querySelector("[data-testid=diagnostics]")?.textContent).toContain("Non disponible");
  });

  it("update check: not configured, up to date, available then install, and each refusal", async () => {
    const checkForUpdate = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: { state: "not_configured" } })
      .mockResolvedValueOnce({ ok: true, status: { state: "up_to_date", current: "0.1.0" } })
      .mockResolvedValueOnce({ ok: true, status: { state: "available", current: "0.1.0", version: "0.2.0", notes: null } })
      .mockResolvedValueOnce({ ok: false, code: "invalid_signature" });
    const installUpdate = vi.fn(async () => ({ ok: false as const, code: "network" as const }));
    const { root } = await mount(fakeDesktop({ checkForUpdate, installUpdate }));
    const click = async (action: string): Promise<void> => {
      root.querySelector<HTMLButtonElement>(`[data-action=${action}]`)?.click();
      await flush();
    };
    const status = (): string => root.querySelector("[data-testid=update-status]")?.textContent ?? "";
    await click("check-update");
    expect(status()).toContain("ne sont pas activées");
    await click("check-update");
    expect(status()).toContain("dernière version");
    await click("check-update");
    expect(status()).toContain("0.2.0");
    const button = root.querySelector<HTMLButtonElement>("[data-action=install-update]");
    button?.click();
    // While downloading: no second click, and the restart is announced.
    expect(button?.disabled).toBe(true);
    expect(root.querySelector("[data-testid=update-progress]")?.textContent).toContain("redémarrera");
    await flush();
    expect(installUpdate).toHaveBeenCalledTimes(1);
    expect(root.querySelector("[data-testid=update-error]")?.textContent).toContain("injoignable");
    // An interrupted download stays pending: a retry is offered without a new check.
    expect(root.querySelector("[data-action=install-update]")?.textContent).toContain("Réessayer");
    await click("install-update");
    expect(installUpdate).toHaveBeenCalledTimes(2);
    await click("check-update");
    expect(root.querySelector("[data-testid=update-error]")?.textContent).toContain("signature");
    expect(root.querySelector("[data-action=install-update]")).toBeNull();
  });

  it("refuses an invalid address with an understandable message and keeps the typed text", async () => {
    const setServerOrigin = vi.fn(async () => ({ ok: false as const, reason: "origin_insecure_scheme" as const }));
    const { root } = await mount(fakeDesktop({ setServerOrigin }, DEFAULT_ORIGIN));
    const input = root.querySelector<HTMLInputElement>("#server-origin-input")!;
    input.value = "http://evil.example.com";
    root.querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flush();
    expect(setServerOrigin).toHaveBeenCalledWith("http://evil.example.com");
    expect(root.querySelector("[data-testid=server-origin-error]")?.textContent).toContain("localhost");
    expect(root.querySelector<HTMLInputElement>("#server-origin-input")?.value).toBe("http://evil.example.com");
    expect(root.querySelector("#server-origin-input")?.getAttribute("aria-invalid")).toBe("true");
  });

  it("saving a valid address asks for an explicit restart and keeps using the applied one", async () => {
    let saved: { configured: string | null; applied: string | null; restart_required: boolean } = {
      configured: null,
      applied: "https://studio.example.com",
      restart_required: false,
    };
    const restartDesktop = vi.fn(async () => true);
    const { root } = await mount(
      fakeDesktop({
        serverOrigin: async () => saved,
        setServerOrigin: async (origin) => {
          saved = { configured: origin, applied: "https://studio.example.com", restart_required: true };
          return { ok: true, state: saved };
        },
        restartDesktop,
      }, DEFAULT_ORIGIN),
    );
    expect(root.querySelector("[data-testid=restart-required]")).toBeNull();
    root.querySelector<HTMLInputElement>("#server-origin-input")!.value = "https://new.example.com";
    root.querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flush();
    expect(root.querySelector("[data-testid=restart-required]")?.textContent).toContain("https://new.example.com");
    expect(root.querySelector("[data-testid=server-effective]")?.textContent).toBe("https://studio.example.com");
    expect(restartDesktop).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>("[data-action=restart]")!.click();
    await flush();
    expect(restartDesktop).toHaveBeenCalledTimes(1);
  });

  it("can restore the build default", async () => {
    const setServerOrigin = vi.fn(async () => ({
      ok: true as const,
      state: { configured: null, applied: "https://studio.example.com", restart_required: false },
    }));
    const { root } = await mount(
      fakeDesktop(
        { setServerOrigin },
        { configured: "https://studio.example.com", applied: "https://studio.example.com", restart_required: false },
      ),
    );
    root.querySelector<HTMLButtonElement>("[data-action=reset-origin]")!.click();
    await flush();
    expect(setServerOrigin).toHaveBeenCalledWith(null);
  });

  it("shows an unreachable server with a retry that recovers without restart", async () => {
    healthy();
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;
    const p = fakeDesktop({}, { configured: "https://s.example.com", applied: "https://s.example.com", restart_required: false });
    await prepareDesktop(p);
    await flush();
    const root = document.createElement("main");
    document.body.append(root);
    await renderApplication(root, p);
    expect(root.querySelector("[data-testid=server-summary]")?.textContent).toBe("Serveur injoignable");
    globalThis.fetch = vi.fn(async () => new Response("ok", { status: 200 })) as unknown as typeof fetch;
    root.querySelector<HTMLButtonElement>("[data-action=retry]")!.click();
    await flush();
    expect(root.querySelector("[data-testid=server-summary]")?.textContent).toBe("Connecté");
    expect(root.querySelector("[data-action=retry]")).toBeNull();
  });

  it("flags an unavailable local assistant without hiding the rest", async () => {
    const unavailable = { ok: false, error: { code: "daemon_unavailable" } } as unknown as BridgeAnswer;
    const { root } = await mount(
      fakeDesktop(
        { request: async () => unavailable },
        { configured: "https://s.example.com", applied: "https://s.example.com", restart_required: false },
      ),
    );
    expect(root.querySelector("[data-testid=daemon-state]")?.getAttribute("data-attention")).toBe("true");
    expect(root.querySelector("[data-testid=server-section]")).not.toBeNull();
  });

  it("shows the P4 health block when daemon.health was negotiated, and hides it otherwise", async () => {
    const withHealth = fakeDaemon({ git_watchers: [{ condition: "healthy" }] });
    const { root } = await mount(
      fakeDesktop({ request: withHealth.request }, { configured: null, applied: "https://studio.example.com", restart_required: false }),
    );
    expect(root.querySelector("[data-testid=daemon-state]")?.textContent).toBe("En marche");
    expect(root.querySelector("[data-testid=health-heartbeat]")?.textContent).toBe("Fonctionne");
    expect(root.querySelector("[data-testid=health-watchers]")?.textContent).toBe("1 / 1 en bonne santé");
    document.body.innerHTML = '<header class="app-topbar"><span id="token-state"></span></header>';
    resetDesktopShellForTests();
    const older = fakeDaemon({ offers: ["daemon.control", "identity.view"] });
    const second = await mount(
      fakeDesktop({ request: older.request }, { configured: null, applied: "https://studio.example.com", restart_required: false }),
    );
    expect(second.root.querySelector("[data-testid=daemon-state]")?.textContent).toBe("En marche");
    expect(second.root.querySelector("[data-testid=health-heartbeat]")).toBeNull();
  });

  it("advises updating an older local assistant that misses optional capabilities", async () => {
    const older = fakeDaemon({ offers: ["daemon.control", "identity.view"] });
    const { root } = await mount(
      fakeDesktop({ request: older.request }, { configured: null, applied: "https://studio.example.com", restart_required: false }),
    );
    expect(root.querySelector("[data-testid=compatibility]")?.textContent).toBe(
      "Compatible — mettez à jour l'assistant local pour disposer de toutes les fonctions",
    );
    document.body.innerHTML = '<header class="app-topbar"><span id="token-state"></span></header>';
    resetDesktopShellForTests();
    const current = fakeDaemon();
    const again = await mount(
      fakeDesktop({ request: current.request }, { configured: null, applied: "https://studio.example.com", restart_required: false }),
    );
    expect(again.root.querySelector("[data-testid=compatibility]")?.textContent).toBe("Compatible");
  });

  it("shows an incompatible protocol as such", async () => {
    const { root } = await mount(
      fakeDesktop({
        desktopInfo: async () => {
          throw new Error("Desktop speaks studio.local/v2 but this Dashboard expects studio.local/v1");
        },
      }),
    );
    expect(root.querySelector("[data-testid=compatibility]")?.textContent).toContain("Incompatible");
    expect(root.querySelector("[data-testid=application-error]")).not.toBeNull();
  });

  it("without any server address: says so, never probes the Desktop origin", async () => {
    const fetchSpy = vi.fn(async () => new Response("ok", { status: 200 }));
    healthy();
    globalThis.fetch = fetchSpy as unknown as typeof fetch;
    const p = fakeDesktop();
    await prepareDesktop(p);
    await flush();
    const root = document.createElement("main");
    document.body.append(root);
    await renderApplication(root, p);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(root.querySelector("[data-testid=server-effective]")?.textContent).toContain("Aucune adresse configurée");
    expect(root.querySelector("[data-testid=server-summary]")?.textContent).toBe("Serveur injoignable");
  });

  it("uses no inline style anywhere on the page", async () => {
    const { root } = await mount();
    expect(root.innerHTML).not.toContain("style=");
  });
});
