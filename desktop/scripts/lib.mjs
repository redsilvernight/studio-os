// Shared helpers for the Desktop build scripts. Everything is derived from this
// file's location: no absolute or user-specific path is ever written down.
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const desktopDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const repoRoot = resolve(desktopDir, "..");
export const dashboardDir = join(repoRoot, "dashboard");
export const tauriDir = join(desktopDir, "src-tauri");
export const buildDir = join(desktopDir, ".build");
export const dashboardOut = join(buildDir, "dashboard");
export const overlayPath = join(buildDir, "tauri.overlay.json");
export const DEFAULT_API_URL = "http://127.0.0.1:8000";

/** Environment with rustup's default install location on PATH (Windows installs do not always export it). */
export function toolEnv(extra = {}) {
  const cargoBin = join(homedir(), ".cargo", "bin");
  const path = [process.env.PATH ?? process.env.Path ?? "", existsSync(cargoBin) ? cargoBin : ""]
    .filter(Boolean)
    .join(delimiter);
  return { ...process.env, PATH: path, Path: path, ...extra };
}

/** Run a command to completion, streaming its output. Resolves with the exit code. */
export function run(command, args, options = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, {
      stdio: "inherit",
      env: toolEnv(options.env),
      cwd: options.cwd ?? desktopDir,
      shell: false,
    });
    child.on("error", reject);
    child.on("exit", (code) => resolvePromise(code ?? 1));
  });
}

export async function runOrFail(command, args, options) {
  const code = await run(command, args, options);
  if (code !== 0) {
    console.error(`\n✖ ${command} ${args.slice(0, 3).join(" ")} … exited with ${code}`);
    process.exit(code);
  }
}

export function capture(command, args, options = {}) {
  const r = spawnSync(command, args, {
    encoding: "utf8",
    env: toolEnv(options.env),
    cwd: options.cwd ?? desktopDir,
    shell: false,
  });
  return { ok: r.status === 0, stdout: (r.stdout ?? "").trim(), stderr: (r.stderr ?? "").trim() };
}

/** The local Tauri CLI (a devDependency), run through Node so no shell is involved. */
export const tauriCli = () => join(desktopDir, "node_modules", "@tauri-apps", "cli", "tauri.js");
export const viteCli = () => join(dashboardDir, "node_modules", "vite", "bin", "vite.js");

export function hostTriple() {
  const r = capture("rustc", ["-vV"]);
  const host = r.stdout.split(/\r?\n/).find((l) => l.startsWith("host:"));
  if (!r.ok || !host) throw new Error("rustc not found: install Rust (see desktop/README.md)");
  return host.slice(5).trim();
}

export function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
export const flag = (name) => process.argv.includes(name);
