// Third-party inventory of what the Desktop distribution contains.
//
//   node scripts/notices.mjs [--check]
//
// Lists, from metadata that is actually present, the Python distributions frozen
// into the sidecar, the Rust crates linked into the shell (`cargo metadata
// --locked`) and the runtime npm packages of the Dashboard. It is an inventory
// with the license each package declares, NOT a certified SBOM and NOT legal
// advice. The full license texts shipped by the Python packages stay next to
// them in `sidecar/_internal/*.dist-info/`. Written to
// `<sidecar dist>/THIRD_PARTY_INVENTORY.json`, so the installer ships it.
//
// --check fails when a package declares no license or a copyleft one that is not
// on the reviewed allow-list below.
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { dashboardDir, desktopDir, flag, tauriDir, toolEnv } from "./lib.mjs";

const sidecarDir = join(desktopDir, ".build", "sidecar", "dist", "studio-daemon");
const internal = join(sidecarDir, "_internal");
const archiveToc = join(desktopDir, ".build", "sidecar", "work", "studio-daemon", "PYZ-00.toc");

// Reviewed copyleft / weak-copyleft items: dynamically linked or unmodified, no
// source-combination with Studio OS code. Anything else copyleft fails --check.
const REVIEWED_COPYLEFT = new Set([
  "certifi", "pyinstaller", "pathspec", "tqdm", "orjson",
  "cssparser", "cssparser-macros", "dtoa-short", "option-ext", "selectors",
]);

function pythonInventory() {
  if (!existsSync(internal) || !existsSync(archiveToc)) return [];
  const r = spawnSync("uv", ["run", "--all-packages", "--frozen", "python", join(desktopDir, "scripts", "python_inventory.py"), internal, archiveToc], {
    encoding: "utf8",
    env: toolEnv(),
    cwd: join(desktopDir, ".."),
    maxBuffer: 64 * 1024 * 1024,
  });
  if (r.status !== 0) throw new Error(`python inventory failed: ${(r.stderr ?? String(r.error)).slice(-300)}`);
  return JSON.parse(r.stdout);
}

function rustInventory() {
  const r = spawnSync(
    "cargo",
    ["metadata", "--format-version", "1", "--locked", "--filter-platform", "x86_64-pc-windows-msvc", "--manifest-path", join(tauriDir, "Cargo.toml")],
    { encoding: "utf8", env: toolEnv(), maxBuffer: 512 * 1024 * 1024 },
  );
  if (r.status !== 0) throw new Error(`cargo metadata failed: ${(r.stderr ?? String(r.error)).slice(-300)}`);
  const meta = JSON.parse(r.stdout);
  const linked = new Set(meta.resolve.nodes.map((n) => n.id));
  meta.packages = meta.packages.filter((p) => linked.has(p.id));
  return meta.packages
    .filter((p) => p.source !== null)
    .map((p) => ({ name: p.name, version: p.version, license: p.license ?? "UNDECLARED", ecosystem: "rust" }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

function npmInventory() {
  const pkg = JSON.parse(readFileSync(join(dashboardDir, "package.json"), "utf8"));
  return Object.keys(pkg.dependencies ?? {}).map((name) => {
    const file = join(dashboardDir, "node_modules", name, "package.json");
    const info = existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : {};
    return { name, version: info.version ?? "unknown", license: info.license ?? "UNDECLARED", ecosystem: "npm" };
  });
}

const COPYLEFT = /\b(A?GPL|LGPL|MPL|EPL|CDDL|SSPL)\b/i;

const packages = [...pythonInventory(), ...rustInventory(), ...npmInventory()];
const undeclared = packages.filter((p) => p.license === "UNDECLARED");
const copyleft = packages.filter((p) => COPYLEFT.test(p.license) && !REVIEWED_COPYLEFT.has(p.name.toLowerCase()));
const byLicense = {};
for (const p of packages) byLicense[p.license] = (byLicense[p.license] ?? 0) + 1;

const inventory = {
  note: "Inventory built from package metadata; not a certified SBOM and not legal advice.",
  generated_for: "studio-desktop",
  counts: { total: packages.length, python: packages.filter((p) => p.ecosystem === "python").length, rust: packages.filter((p) => p.ecosystem === "rust").length, npm: packages.filter((p) => p.ecosystem === "npm").length },
  licenses: Object.fromEntries(Object.entries(byLicense).sort((a, b) => b[1] - a[1])),
  undeclared: undeclared.map((p) => `${p.ecosystem}:${p.name}`),
  packages,
};

if (existsSync(sidecarDir)) writeFileSync(join(sidecarDir, "THIRD_PARTY_INVENTORY.json"), JSON.stringify(inventory, null, 2) + "\n");
console.log(`inventory: ${inventory.counts.total} packages (python ${inventory.counts.python}, rust ${inventory.counts.rust}, npm ${inventory.counts.npm}); undeclared license: ${undeclared.length}; unreviewed copyleft: ${copyleft.length}`);
if (undeclared.length) console.log(`  undeclared: ${undeclared.map((p) => p.name).join(", ")}`);
if (copyleft.length) console.log(`  copyleft: ${copyleft.map((p) => `${p.name} (${p.license})`).join(", ")}`);
if (flag("--check") && (undeclared.length || copyleft.length)) process.exit(1);
