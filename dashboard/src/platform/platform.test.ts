import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { buildRequest, knownCommands, parseAnswer } from "./contracts";
import { createDesktopPlatform, detectTauriInvoke } from "./desktop";
import { LOCAL_COMMANDS, LOCAL_PROTOCOL, LOCAL_SCHEMAS } from "./generated/local-contracts.generated";
import { getPlatform } from "./index";
import { validateSchema } from "./schemaValidator";
import { webPlatform } from "./web";

const dashboardRoot = resolve(__dirname, "..", "..");
const localDir = resolve(dashboardRoot, "..", "contracts", "local");
const fixtures = (kind: "valid" | "invalid") =>
  readdirSync(resolve(localDir, "fixtures", kind)).map((name) => ({
    name,
    ...(JSON.parse(readFileSync(resolve(localDir, "fixtures", kind, name), "utf8")) as {
      model: string;
      data: unknown;
    }),
  }));

describe("P1 contract boundary (no second source of truth)", () => {
  it("the generated module is in sync with contracts/local (drift check)", () => {
    expect(() =>
      execFileSync(process.execPath, ["scripts/gen-local-contracts.mjs", "--check"], {
        cwd: dashboardRoot,
        stdio: "pipe",
      }),
    ).not.toThrow();
  });

  it("the command table equals the exported P1 allowlist", () => {
    const exported = JSON.parse(readFileSync(resolve(localDir, "allowlist.json"), "utf8")) as {
      protocol: string;
      commands: { command: string }[];
    };
    expect(LOCAL_PROTOCOL).toBe(exported.protocol);
    expect(knownCommands().sort()).toEqual(exported.commands.map((c) => c.command).sort());
    expect(knownCommands()).toHaveLength(33);
  });

  it("bundles the request and response schema of every allowlisted command", () => {
    for (const c of LOCAL_COMMANDS) {
      expect(LOCAL_SCHEMAS[c.request], `${c.command} request ${c.request}`).toBeDefined();
      expect(LOCAL_SCHEMAS[c.response], `${c.command} response ${c.response}`).toBeDefined();
    }
  });

  it("the reindex commands build a valid request", () => {
    const workspace_id = "3f2b8c1e-4d5a-4b6c-9e7f-0a1b2c3d4e5f";
    expect(() => buildRequest("knowledge.reindex", { workspace_id, mode: "full_rebuild" })).not.toThrow();
    expect(() => buildRequest("code_graph.reindex", { workspace_id, mode: "full_rebuild" })).not.toThrow();
  });

  it("every bundled schema accepts every valid P1 fixture of that model", () => {
    const checked = fixtures("valid").filter((f) => f.model in LOCAL_SCHEMAS);
    expect(checked.length).toBeGreaterThan(10);
    for (const f of checked) {
      expect(validateSchema(LOCAL_SCHEMAS[f.model], f.data), f.name).toEqual([]);
    }
  });

  it("rejects the invalid P1 fixtures the JSON Schema can express", () => {
    for (const name of ["bridge.request.unknown_field", "bridge.request.forbidden_command"]) {
      const f = fixtures("invalid").find((x) => x.name === `${name}.json`);
      expect(f, name).toBeDefined();
      expect(validateSchema(LOCAL_SCHEMAS[f!.model], f!.data), name).not.toEqual([]);
    }
  });

  it("enforces minProperties and maxProperties on objects", () => {
    const schema = { type: "object", minProperties: 1, maxProperties: 2 };
    expect(validateSchema(schema, { a: 1 })).toEqual([]);
    expect(validateSchema(schema, {})).not.toEqual([]);
    expect(validateSchema(schema, { a: 1, b: 2, c: 3 })).not.toEqual([]);
  });

  it("exposes no dangerous primitive in the command table", () => {
    const banned = ["execute_shell", "spawn_process", "read_file", "write_file", "proxy_http", "execute", "run_command"];
    for (const name of banned) expect(knownCommands()).not.toContain(name);
    for (const c of LOCAL_COMMANDS) expect(c.command).toMatch(/^[a-z_]+\.[a-z_]+$/);
  });
});

describe("request building", () => {
  it("builds a valid studio.local/v1 request", () => {
    const req = buildRequest("identity.get_view");
    expect(req.protocol).toBe("studio.local/v1");
    expect(req.kind).toBe("request");
    expect(validateSchema(LOCAL_SCHEMAS.BridgeRequest, req)).toEqual([]);
  });

  it("refuses a payload that does not match the P1 request model", () => {
    expect(() => buildRequest("daemon.status", { action: "rm -rf" })).toThrow(/payload/);
    expect(() => buildRequest("identity.get_view", { anything: 1 })).toThrow(/payload/);
  });

  it("refuses a command outside the allowlist", () => {
    expect(() => buildRequest("execute_shell" as never)).toThrow(/allowlist/);
  });
});

const statusPayload = {
  action: "status",
  profile: { profile_id: "default", server_origin: "https://studio.example.test" },
};

describe("answer validation fails closed", () => {
  const validResponse = () => {
    const req = buildRequest("daemon.status", statusPayload);
    const payload = fixtures("valid").find((f) => f.name === "daemon.control.unavailable.json")!.data;
    return {
      req,
      raw: {
        kind: "response",
        protocol: LOCAL_PROTOCOL,
        message_id: "desktop-res-1",
        correlation_id: req.correlation_id,
        request_id: req.message_id,
        sent_at: "2026-01-15T12:00:00Z",
        command: "daemon.status",
        payload,
      },
    };
  };

  it("accepts a correct answer", () => {
    const { req, raw } = validResponse();
    expect(parseAnswer(req, raw).ok).toBe(true);
  });

  it("refuses another protocol", () => {
    const { req, raw } = validResponse();
    const out = parseAnswer(req, { ...raw, protocol: "studio.local/v2" });
    expect(out.ok).toBe(false);
  });

  it("refuses a different correlation id", () => {
    const { req, raw } = validResponse();
    expect(parseAnswer(req, { ...raw, correlation_id: "someone-else" }).ok).toBe(false);
  });

  it("refuses an answer to another request id", () => {
    const { req, raw } = validResponse();
    expect(parseAnswer(req, { ...raw, request_id: "other" }).ok).toBe(false);
  });

  it("refuses a payload that violates the P1 model", () => {
    const { req, raw } = validResponse();
    expect(parseAnswer(req, { ...raw, payload: { state: "running" } }).ok).toBe(false);
  });

  it("refuses unknown kinds and garbage", () => {
    const { req } = validResponse();
    expect(parseAnswer(req, { kind: "event" }).ok).toBe(false);
    expect(parseAnswer(req, null).ok).toBe(false);
    expect(parseAnswer(req, "text").ok).toBe(false);
  });

  it("passes a P1 error message through as a typed error", () => {
    const { req } = validResponse();
    const err = fixtures("valid").find((f) => f.name === "bridge.error.capability_missing.json")!.data;
    const out = parseAnswer(req, err);
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.error.code).toBe("capability_missing");
  });
});

describe("platform adapters", () => {
  it("web adapter has no desktop and never fakes availability", async () => {
    expect(webPlatform.mode).toBe("web");
    expect(await webPlatform.desktopInfo()).toBeNull();
    const out = await webPlatform.request("daemon.status");
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.error.code).toBe("not_supported");
  });

  it("is web when Tauri is absent", () => {
    expect(detectTauriInvoke({})).toBeNull();
    expect(getPlatform({}).mode).toBe("web");
  });

  it("is desktop only when the shell injected invoke", () => {
    const scope = { __TAURI__: { core: { invoke: async () => ({}) } } };
    expect(detectTauriInvoke(scope)).not.toBeNull();
    expect(getPlatform(scope).mode).toBe("desktop");
    expect(detectTauriInvoke({ __TAURI__: { core: { invoke: "nope" } } })).toBeNull();
  });

  it("desktop adapter reads identity and fails closed on another protocol", async () => {
    const info = {
      product: "Studi'OS Desktop",
      desktop_version: "0.1.0",
      mode: "desktop",
      protocol: LOCAL_PROTOCOL,
      sidecar: { state: "not_started" },
    };
    const ok = createDesktopPlatform(async () => info);
    expect((await ok.desktopInfo())?.desktop_version).toBe("0.1.0");
    const bad = createDesktopPlatform(async () => ({ ...info, protocol: "studio.local/v2" }));
    await expect(bad.desktopInfo()).rejects.toThrow(/expects/);
    const garbage = createDesktopPlatform(async () => ({ hello: "world" }));
    await expect(garbage.desktopInfo()).rejects.toThrow();
  });

  it("desktop adapter only ever invokes the two app commands", async () => {
    const seen: string[] = [];
    const platform = createDesktopPlatform(async (name) => {
      seen.push(name);
      throw new Error("shell down");
    });
    const out = await platform.request("identity.get_view");
    expect(out.ok).toBe(false);
    expect(seen).toEqual(["bridge_request"]);
  });

  it("desktop adapter answers a contract-invalid request with a typed error, never a throw", async () => {
    const seen: string[] = [];
    const platform = createDesktopPlatform(async (name) => {
      seen.push(name);
      return null;
    });
    const out = await platform.request("knowledge.reindex", { workspace_id: "not-a-uuid" });
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.error.code).toBe("invalid_request");
    expect(seen).toEqual([]);
  });
});

describe("desktop adapter: diagnostics and updates", () => {
  const DIAG = {
    desktop_version: "0.1.0",
    protocol: LOCAL_PROTOCOL,
    os: "windows",
    arch: "x86_64",
    sidecar: { state: { state: "not_started" }, present: true, manifest: null, compat: "unknown" },
    server_origin: null,
    updates_configured: false,
    locations: {
      daemon_data_dir: null,
      logs_dir: null,
      shell_settings_dir: null,
      install_dir: null,
      data_format: { state: "unstamped" },
      logs: [],
    },
  };

  it("shape-checks the diagnostics and refuses anything else", async () => {
    expect((await createDesktopPlatform(async () => DIAG).diagnostics())?.os).toBe("windows");
    await expect(createDesktopPlatform(async () => ({ ...DIAG, sidecar: null })).diagnostics()).rejects.toThrow();
    await expect(createDesktopPlatform(async () => ({ ...DIAG, locations: { ...DIAG.locations, logs: [{ name: 1 }] } })).diagnostics()).rejects.toThrow();
    await expect(createDesktopPlatform(async () => "nope").diagnostics()).rejects.toThrow();
  });

  it("accepts the tagged sidecar state the shell really serializes", async () => {
    const running = { ...DIAG, sidecar: { ...DIAG.sidecar, state: { state: "running", pid: 4352 } } };
    expect((await createDesktopPlatform(async () => running).diagnostics())?.sidecar.state).toEqual({ state: "running", pid: 4352 });
    await expect(createDesktopPlatform(async () => ({ ...DIAG, sidecar: { ...DIAG.sidecar, state: "running" } })).diagnostics()).rejects.toThrow();
  });

  it("the folder to open is a closed value passed as is; a refusal is just false", async () => {
    const calls: unknown[] = [];
    const ok = createDesktopPlatform(async (name, args) => {
      calls.push([name, args]);
      return null;
    });
    expect(await ok.openDataFolder("logs")).toBe(true);
    expect(calls).toEqual([["open_data_folder", { folder: "logs" }]]);
    const refused = createDesktopPlatform(async () => {
      throw { code: "open_failed" };
    });
    expect(await refused.openDataFolder("diagnostics")).toBe(false);
  });

  it("exports through the shell and never trusts an answer without a file", async () => {
    expect(await createDesktopPlatform(async () => ({ file: "~\\d.json" })).exportDiagnostics()).toEqual({ ok: true, file: "~\\d.json" });
    expect((await createDesktopPlatform(async () => ({})).exportDiagnostics()).ok).toBe(false);
    const failed = await createDesktopPlatform(async () => {
      throw { code: "export_failed" };
    }).exportDiagnostics();
    expect(failed).toEqual({ ok: false, code: "export_failed" });
  });

  it("maps the update states and every shell error code, unknown ones to failed", async () => {
    const status = async (v: unknown) => createDesktopPlatform(async () => v).checkForUpdate();
    expect(await status({ state: "not_configured" })).toEqual({ ok: true, status: { state: "not_configured" } });
    expect(await status({ state: "up_to_date", current: "0.1.0" })).toEqual({ ok: true, status: { state: "up_to_date", current: "0.1.0" } });
    expect(await status({ state: "available", current: "0.1.0", version: "0.2.0" })).toEqual({
      ok: true,
      status: { state: "available", current: "0.1.0", version: "0.2.0", notes: null },
    });
    expect(await status({ state: "available" })).toEqual({ ok: false, code: "invalid_metadata" });
    const failing = (code: unknown) =>
      createDesktopPlatform(async () => {
        throw { code };
      });
    for (const code of ["not_configured", "network", "invalid_metadata", "invalid_signature", "install_failed"]) {
      expect(await failing(code).checkForUpdate()).toEqual({ ok: false, code });
      expect(await failing(code).installUpdate()).toEqual({ ok: false, code });
    }
    expect(await failing("boom").checkForUpdate()).toEqual({ ok: false, code: "failed" });
  });

  it("the web adapter offers none of it and says so", async () => {
    expect(webPlatform.native.diagnostics || webPlatform.native.updates).toBe(false);
    expect(await webPlatform.diagnostics()).toBeNull();
    expect(await webPlatform.openDataFolder("logs")).toBe(false);
    expect(await webPlatform.checkForUpdate()).toEqual({ ok: false, code: "not_configured" });
  });
});
