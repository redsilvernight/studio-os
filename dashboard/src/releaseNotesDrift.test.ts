// @vitest-environment node
// The embedded notes module is generated from desktop/release-notes/*.md and
// committed. This guards against editing a note without regenerating it.
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const dashboard = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repo = resolve(dashboard, "..");
const script = join(repo, "desktop", "scripts", "release-notes.mjs");

describe("release notes drift", () => {
  it("the committed embedded module matches the note files", () => {
    const run = spawnSync(process.execPath, [script, "--check"], { encoding: "utf8" });
    expect(`${run.stdout}${run.stderr}`).toContain("release notes OK");
    expect(run.status).toBe(0);
  });
});
