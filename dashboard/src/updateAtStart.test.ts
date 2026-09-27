// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { APPLICATION_SETTINGS_HASH, checkUpdateAtStart, paintUpdateBanner, resetUpdateAtStartForTests } from "./updateAtStart";
import type { UpdateCheckResult } from "./platform/types";

const banner = (): HTMLElement => document.getElementById("client-update-banner")!;
const platform = (result: UpdateCheckResult | Error) => ({
  checkForUpdate: async () => {
    if (result instanceof Error) throw result;
    return result;
  },
});

beforeEach(() => {
  document.body.innerHTML = '<div id="client-update-banner" hidden></div>';
});
afterEach(() => resetUpdateAtStartForTests());

describe("update check at start", () => {
  it("an available release shows a banner leading to the settings, nothing installed", async () => {
    await checkUpdateAtStart(platform({ ok: true, status: { state: "available", current: "0.1.0-dev.25", version: "0.1.0-dev.30", notes: null } }));
    expect(banner().hidden).toBe(false);
    expect(banner().textContent).toContain("0.1.0-dev.30");
    expect(banner().querySelector("a")?.getAttribute("href")).toBe(APPLICATION_SETTINGS_HASH);
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
    document.body.innerHTML = '<div id="client-update-banner" hidden></div>';
    paintUpdateBanner(document);
    expect(banner().hidden).toBe(false);
    expect(banner().textContent).toContain("(2)");
  });
});
