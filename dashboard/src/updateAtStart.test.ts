// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { checkUpdateAtStart, paintUpdateBanner, resetUpdateAtStartForTests } from "./updateAtStart";
import { installUpdateOnce } from "./updateInstaller";
import type { UpdateCheckResult } from "./platform/types";

const banner = (): HTMLElement => document.getElementById("desktop-update-banner")!;
const platform = (result: UpdateCheckResult | Error) => ({
  checkForUpdate: async () => {
    if (result instanceof Error) throw result;
    return result;
  },
  installUpdate: vi.fn(async () => ({ ok: true as const })),
  restartDesktop: vi.fn(async () => true),
});

beforeEach(() => {
  document.body.innerHTML = '<div id="desktop-update-banner" hidden></div>';
});
afterEach(() => resetUpdateAtStartForTests());

describe("update check at start", () => {
  it("installe sur un clic explicite, indique la progression et ignore les clics répétés", async () => {
    const target = platform({ ok: true, status: { state: "available", current: "0.1.0-dev.25", version: "0.1.0-dev.30", notes: null } });
    let finish!: (result: { ok: true }) => void;
    target.installUpdate = vi.fn(() => new Promise((resolve) => { finish = resolve; }));
    await checkUpdateAtStart(target);
    expect(banner().hidden).toBe(false);
    expect(banner().textContent).toContain("0.1.0-dev.30");
    expect(target.installUpdate).not.toHaveBeenCalled();
    const button = banner().querySelector("button")!;
    button.click();
    button.click();
    expect(banner().getAttribute("aria-busy")).toBe("true");
    expect(banner().querySelector("progress")).not.toBeNull();
    expect(banner().querySelector("button")?.disabled).toBe(true);
    await vi.waitFor(() => expect(target.installUpdate).toHaveBeenCalledTimes(1));
    finish({ ok: true });
    await vi.waitFor(() => expect(banner().textContent).toContain("Redémarrage"));
    banner().querySelector("button")!.click();
    await vi.waitFor(() => expect(target.restartDesktop).toHaveBeenCalledTimes(1));
    expect(banner().querySelector("a")).toBeNull();
  });

  it("up to date, not configured, error or offline: silence", async () => {
    await checkUpdateAtStart(platform({ ok: true, status: { state: "up_to_date", current: "1" } }));
    await checkUpdateAtStart(platform({ ok: true, status: { state: "not_configured" } }));
    await checkUpdateAtStart(platform({ ok: false, code: "network" } as UpdateCheckResult));
    await checkUpdateAtStart(platform(new Error("offline")));
    expect(banner().hidden).toBe(true);
  });

  it("the banner is repainted in a shell mounted after the check", async () => {
    document.body.innerHTML = "";
    await checkUpdateAtStart(platform({ ok: true, status: { state: "available", current: "1", version: "2", notes: null } }));
    document.body.innerHTML = '<div id="desktop-update-banner" hidden></div>';
    paintUpdateBanner(document);
    expect(banner().hidden).toBe(false);
    expect(banner().textContent).toContain("(2)");
  });

  it("annonce une erreur, retrouve la version puis permet une nouvelle tentative", async () => {
    const target = {
      ...platform({ ok: true, status: { state: "available", current: "1", version: "2", notes: null } }),
      installUpdate: vi.fn().mockResolvedValueOnce({ ok: false, code: "network" }).mockResolvedValueOnce({ ok: true }),
    };
    await checkUpdateAtStart(target);
    banner().querySelector("button")!.click();
    await vi.waitFor(() => expect(banner().querySelector('[role="alert"]')?.textContent).toContain("injoignable"));
    banner().querySelector("button")!.click();
    await vi.waitFor(() => expect(target.installUpdate).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(banner().textContent).toContain("Redémarrage"));
  });

  it("un appel depuis une autre vue partage la même installation et les exceptions sont affichables", async () => {
    const target = { installUpdate: vi.fn(async () => { throw new Error("bridge disconnected"); }) };
    const first = installUpdateOnce(target);
    expect(installUpdateOnce(target)).toBe(first);
    await expect(first).resolves.toEqual({ ok: false, code: "failed" });
    expect(target.installUpdate).toHaveBeenCalledTimes(1);
  });

  it("le bandeau de compatibilité serveur ne masque pas l'installation détectée", async () => {
    document.body.insertAdjacentHTML("beforeend", '<div id="client-update-banner">Autre version conseillée</div>');
    await checkUpdateAtStart(platform({ ok: true, status: { state: "available", current: "1", version: "2", notes: null } }));
    expect(document.getElementById("client-update-banner")?.textContent).toBe("Autre version conseillée");
    expect(banner().querySelector("button")?.textContent).toBe("Installer");
  });
});
