// @vitest-environment node
import { spawnSync } from "node:child_process";
import { cpSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

const dashboard = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const repo = resolve(dashboard, "..");
const GENERATED = join("dashboard", "src", "platform", "generated", "local-contracts.generated.ts");
const scratch: string[] = [];

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

function checkout(eol: "\n" | "\r\n"): string {
  const root = mkdtempSync(join(tmpdir(), "local-contracts-"));
  scratch.push(root);
  cpSync(join(repo, "contracts", "local"), join(root, "contracts", "local"), { recursive: true });
  cpSync(join(dashboard, "scripts", "gen-local-contracts.mjs"), join(root, "dashboard", "scripts", "gen-local-contracts.mjs"));
  cpSync(join(repo, GENERATED), join(root, GENERATED), { recursive: true });
  for (const file of walk(root)) {
    const text = readFileSync(file, "utf8").replace(/\r\n/g, "\n");
    writeFileSync(file, eol === "\n" ? text : text.replace(/\n/g, "\r\n"));
  }
  return root;
}

function check(root: string): { status: number | null; output: string } {
  const run = spawnSync(process.execPath, [join(root, "dashboard", "scripts", "gen-local-contracts.mjs"), "--check"], {
    encoding: "utf8",
  });
  return { status: run.status, output: `${run.stdout}${run.stderr}` };
}

afterEach(() => {
  while (scratch.length > 0) rmSync(scratch.pop() as string, { recursive: true, force: true });
});

describe("local contracts drift check and line endings", () => {
  it("is green on an LF checkout", () => {
    expect(check(checkout("\n")).status).toBe(0);
  });

  it("is green on a CRLF checkout (Windows, core.autocrlf=true)", () => {
    expect(check(checkout("\r\n")).status).toBe(0);
  });

  it("still reports a real drift, whatever the line endings", () => {
    for (const eol of ["\n", "\r\n"] as const) {
      const root = checkout(eol);
      const allowlist = join(root, "contracts", "local", "allowlist.json");
      const drifted = readFileSync(allowlist, "utf8").replace('"workspace.get_config"', '"workspace.get_config_x"');
      expect(drifted).not.toBe(readFileSync(allowlist, "utf8"));
      writeFileSync(allowlist, drifted);
      const result = check(root);
      expect(result.status).toBe(1);
      expect(result.output).toContain("out of date");
    }
  });

  it("the committed generated file matches the committed contracts", () => {
    const result = spawnSync(process.execPath, [join(dashboard, "scripts", "gen-local-contracts.mjs"), "--check"], {
      encoding: "utf8",
    });
    expect(result.status).toBe(0);
  });
});
