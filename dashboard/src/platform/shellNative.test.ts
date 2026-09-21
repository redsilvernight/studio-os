import { describe, expect, it } from "vitest";
import { createDesktopPlatform } from "./desktop";
import { webPlatform } from "./web";

type Call = { name: string; args?: Record<string, unknown> };

function fake(answers: Record<string, unknown>) {
  const calls: Call[] = [];
  const platform = createDesktopPlatform(async (name, args) => {
    calls.push({ name, args });
    const answer = answers[name];
    if (answer instanceof Error) throw answer;
    return answer;
  });
  return { platform, calls };
}

const refusal = (code: string) => Object.assign(new Error(code), { code });

describe("Desktop shell adapter: server origin", () => {
  it("reads and shape-checks the origin state", async () => {
    const good = { configured: "https://studio.example.com", applied: null, restart_required: true };
    const { platform, calls } = fake({ get_server_origin: good });
    expect(await platform.serverOrigin()).toEqual(good);
    expect(calls[0]?.name).toBe("get_server_origin");
    const bad = fake({ get_server_origin: { configured: 3 } });
    await expect(bad.platform.serverOrigin()).rejects.toThrow(/unexpected shape/);
  });

  it("saves through the shell and returns the new state", async () => {
    const state = { configured: "https://studio.example.com", applied: null, restart_required: true };
    const { platform, calls } = fake({ set_server_origin: state });
    expect(await platform.setServerOrigin("https://studio.example.com")).toEqual({ ok: true, state });
    expect(calls[0]).toEqual({ name: "set_server_origin", args: { origin: "https://studio.example.com" } });
  });

  it("maps every shell refusal to a typed reason and never guesses success", async () => {
    for (const code of ["origin_invalid", "origin_insecure_scheme", "origin_is_desktop_origin", "storage_failed"]) {
      const { platform } = fake({ set_server_origin: refusal(code) });
      expect(await platform.setServerOrigin("x")).toEqual({ ok: false, reason: code });
    }
    const unknown = fake({ set_server_origin: refusal("something_new") });
    expect(await unknown.platform.setServerOrigin("x")).toEqual({ ok: false, reason: "failed" });
    const garbage = fake({ set_server_origin: { hello: 1 } });
    expect(await garbage.platform.setServerOrigin("x")).toEqual({ ok: false, reason: "failed" });
  });

  it("restart reports false when the shell refuses", async () => {
    expect(await fake({ restart_desktop: undefined }).platform.restartDesktop()).toBe(true);
    expect(await fake({ restart_desktop: refusal("untrusted_caller") }).platform.restartDesktop()).toBe(false);
  });
});

describe("Desktop shell adapter: native pickers", () => {
  it("returns only what the user chose", async () => {
    const { platform, calls } = fake({
      choose_folder: { status: "selected", path: "C:/Jeux/Mon Projet", display_name: "Mon Projet" },
    });
    expect(await platform.chooseFolder({ title: "Choisir un dossier" })).toEqual({
      status: "selected",
      path: "C:/Jeux/Mon Projet",
      display_name: "Mon Projet",
    });
    expect(calls[0]).toEqual({ name: "choose_folder", args: { options: { title: "Choisir un dossier" } } });
  });

  it("treats cancellation as a normal outcome", async () => {
    expect(await fake({ choose_file: { status: "cancelled" } }).platform.chooseFile()).toEqual({ status: "cancelled" });
    expect(await fake({ choose_folder: { status: "cancelled" } }).platform.chooseFolder()).toEqual({ status: "cancelled" });
  });

  it("surfaces a shell error code and rejects malformed answers", async () => {
    expect(await fake({ choose_file: refusal("picker_busy") }).platform.chooseFile()).toEqual({
      status: "error",
      code: "picker_busy",
    });
    expect(await fake({ choose_file: { status: "selected", path: "" } }).platform.chooseFile()).toEqual({
      status: "error",
      code: "unexpected_answer",
    });
    expect(await fake({ choose_file: new Error("Bad Code!") }).platform.chooseFile()).toEqual({
      status: "error",
      code: "failed",
    });
  });

  it("offers no generic file API: no read/list capability exists on the platform", () => {
    const names = Object.keys(fake({}).platform);
    expect(names.filter((n) => /read|list|scan|write|readdir/i.test(n))).toEqual([]);
  });
});

describe("Web adapter: native controls are absent, never faked", () => {
  it("reports unavailable everywhere", async () => {
    expect(webPlatform.native).toEqual({ serverOrigin: false, pickers: false });
    expect(await webPlatform.serverOrigin()).toBeNull();
    expect(await webPlatform.setServerOrigin("https://x.example")).toEqual({ ok: false, reason: "unavailable" });
    expect(await webPlatform.restartDesktop()).toBe(false);
    expect(await webPlatform.chooseFolder()).toEqual({ status: "unavailable" });
    expect(await webPlatform.chooseFile()).toEqual({ status: "unavailable" });
  });

  it("works without any Tauri global (absent native API)", () => {
    expect((globalThis as Record<string, unknown>)["__TAURI__"]).toBeUndefined();
    expect(webPlatform.mode).toBe("web");
  });
});

describe("Desktop platform declares its native controls", () => {
  it("flags server origin and pickers as available", () => {
    expect(fake({}).platform.native).toEqual({ serverOrigin: true, pickers: true });
  });
});
