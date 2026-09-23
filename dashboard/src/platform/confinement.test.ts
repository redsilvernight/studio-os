import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { describe, expect, it } from "vitest";

const srcRoot = resolve(__dirname, "..");
const allowed = join("platform", "desktop.ts");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "generated" ? [] : sources(path);
    return /\.(ts|js)$/.test(name) && !/\.test\.ts$/.test(name) ? [path] : [];
  });
}

describe("Tauri stays behind the platform adapter", () => {
  it("only platform/desktop.ts may name the Tauri global or package", () => {
    const offenders = sources(srcRoot)
      .filter((file) => relative(srcRoot, file).split(sep).join(sep) !== allowed)
      .filter((file) => /__TAURI__|@tauri-apps|tauri-apps/.test(readFileSync(file, "utf8")))
      .map((file) => relative(srcRoot, file));
    expect(offenders).toEqual([]);
  });

  it("the dashboard package does not depend on any @tauri-apps package", () => {
    const pkg = JSON.parse(readFileSync(resolve(srcRoot, "..", "package.json"), "utf8")) as Record<
      string,
      Record<string, string> | undefined
    >;
    const deps = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
    expect(deps.filter((d) => d.startsWith("@tauri-apps"))).toEqual([]);
  });
});
