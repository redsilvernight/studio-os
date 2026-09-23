// Verifies the Windows dev prerequisites and says how to fix what is missing.
import { existsSync } from "node:fs";
import { capture, flag, repoRoot, tauriCli, viteCli } from "./lib.mjs";
import { join } from "node:path";

const rows = [];
const add = (name, ok, detail, fix, required = true) => rows.push({ name, ok, detail, fix, required });

const nodeMajor = Number(process.versions.node.split(".")[0]);
const nodeMinor = Number(process.versions.node.split(".")[1]);
add("Node ≥ 22.18", nodeMajor > 22 || (nodeMajor === 22 && nodeMinor >= 18), process.versions.node, "Install Node 22.18+ (type stripping is used by the build scripts).");

const rustc = capture("rustc", ["--version"]);
add("Rust (rustc)", rustc.ok, rustc.stdout || "not found", "Install rustup (https://rustup.rs) with the stable MSVC toolchain.");
const cargo = capture("cargo", ["--version"]);
add("Cargo", cargo.ok, cargo.stdout || "not found", "Comes with rustup.");

if (process.platform === "win32") {
  const vswhere = join(process.env["ProgramFiles(x86)"] ?? "C:\Program Files (x86)", "Microsoft Visual Studio", "Installer", "vswhere.exe");
  const msvc = existsSync(vswhere)
    ? capture(vswhere, ["-all", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"])
    : { ok: false, stdout: "" };
  add("MSVC C++ Build Tools", msvc.ok && !!msvc.stdout, msvc.stdout ? "found" : "not found", "Install 'Visual Studio Build Tools' with the 'Desktop development with C++' workload.");

  const keys = [
    String.raw`HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`,
    String.raw`HKCU\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`,
  ];
  let webview2 = "";
  for (const key of keys) {
    const r = capture("reg", ["query", key, "/v", "pv"]);
    const m = r.stdout.match(/pv\s+REG_SZ\s+(\S+)/);
    if (r.ok && m) { webview2 = m[1]; break; }
  }
  add("WebView2 runtime", !!webview2, webview2 || "not found", "Install the Evergreen WebView2 runtime (preinstalled on Windows 11).");
}

add("Tauri CLI (desktop/node_modules)", existsSync(tauriCli()), existsSync(tauriCli()) ? "installed" : "missing", "cd desktop && npm ci");
add("Dashboard deps (dashboard/node_modules)", existsSync(viteCli()), existsSync(viteCli()) ? "installed" : "missing", "cd dashboard && npm ci");

const uv = capture("uv", ["--version"]);
add("uv (freezes the daemon)", uv.ok, uv.stdout || "not found", "Install uv (https://docs.astral.sh/uv/) — needed to freeze the daemon service.", flag("--sidecar"));

if (repoRoot.includes("'")) {
  add(
    "Repository path without apostrophe",
    true,
    `path contains an apostrophe: handled by the build.rs icon workaround`,
    "The Windows resource compiler (RC.EXE) cannot read an apostrophe in the icon path; build.rs copies the icon to %TEMP% automatically.",
    false,
  );
}

let failed = 0;
for (const r of rows) {
  const mark = r.ok ? "✔" : r.required ? "✖" : "•";
  console.log(`${mark} ${r.name.padEnd(42)} ${r.detail}`);
  if (!r.ok) {
    console.log(`    → ${r.fix}`);
    if (r.required) failed += 1;
  }
}
console.log("");
if (failed) {
  console.error(`${failed} required prerequisite(s) missing.`);
  process.exit(1);
}
console.log("All required prerequisites present.");
