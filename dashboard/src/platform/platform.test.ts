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
    expect(knownCommands()).toHaveLength(29);
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
});
