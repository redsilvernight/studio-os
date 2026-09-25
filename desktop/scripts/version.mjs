// Version scope of the Desktop distribution (B2: docs/VERSION_SCOPE.md).
//
//   node scripts/version.mjs            # print the canonical version
//   node scripts/version.mjs --check    # synced carriers equal the canonical
//                                       # version AND every declared version
//                                       # parses as semver
//   node scripts/version.mjs --sync     # rewrite the synced carriers from the
//                                       # canonical version (independent ones
//                                       # are never touched)
//
// Canonical: desktop/package.json "version". Synced carriers: the Rust crate
// (the Desktop version reported by the shell and used by Tauri/NSIS, since
// tauri.conf.json deliberately has no "version") and the daemon's
// DAEMON_VERSION. Cargo.lock follows the crate on the next cargo run.
//
// Independent versions (declared below, never synced): the dashboard SPA is
// deployed with the server stack, not inside the Desktop bundle, so
// dashboard/package.json follows the server release; every pyproject.toml
// carries an internal package version, not a product version.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { dashboardDir, desktopDir, flag, repoRoot, tauriDir } from "./lib.mjs";

const SEMVER = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;

export const canonicalVersion = () => {
  const version = JSON.parse(readFileSync(join(desktopDir, "package.json"), "utf8")).version;
  if (!SEMVER.test(version)) throw new Error(`desktop/package.json version is not semver: ${version}`);
  return version;
};

const daemonFile = join(repoRoot, "packages", "studio-client", "src", "studio_client", "daemon", "service.py");
const cargoFile = join(tauriDir, "Cargo.toml");

const syncedCarriers = [
  {
    name: "src-tauri/Cargo.toml [package] version",
    file: cargoFile,
    pattern: /(\[package\][^[]*?\nversion\s*=\s*")([^"]+)(")/,
  },
  {
    name: "daemon service.py DAEMON_VERSION",
    file: daemonFile,
    pattern: /(\nDAEMON_VERSION\s*=\s*")([^"]+)(")/,
  },
];

const independentVersions = [
  { name: "dashboard/package.json version", file: join(dashboardDir, "package.json") },
  { name: "root pyproject.toml version", file: join(repoRoot, "pyproject.toml") },
  ...["studio-client", "studio-code-graph", "studio-contracts", "studio-workspaces"].map((pkg) => ({
    name: `packages/${pkg}/pyproject.toml version`,
    file: join(repoRoot, "packages", pkg, "pyproject.toml"),
  })),
  ...["api", "mcp"].map((svc) => ({
    name: `services/${svc}/pyproject.toml version`,
    file: join(repoRoot, "services", svc, "pyproject.toml"),
  })),
];

const readJsonVersion = (file) => {
  const version = JSON.parse(readFileSync(file, "utf8")).version;
  if (typeof version !== "string" || !SEMVER.test(version)) {
    throw new Error(`${file} version is not semver: ${version}`);
  }
  return version;
};

const readTomlVersion = (file) => {
  const match = /^version\s*=\s*"([^"]+)"(?:\s|$)/m.exec(readFileSync(file, "utf8"));
  if (!match || !SEMVER.test(match[1])) {
    throw new Error(`${file} version is missing or not semver`);
  }
  return match[1];
};

function read(carrier) {
  const text = readFileSync(carrier.file, "utf8");
  const match = carrier.pattern.exec(text);
  if (!match) throw new Error(`${carrier.name}: version declaration not found`);
  return { text, match, value: match[2] };
}

export function checkVersions() {
  const expected = canonicalVersion();
  return syncedCarriers.map((carrier) => ({ name: carrier.name, expected, actual: read(carrier).value }));
}

export function checkIndependentVersions() {
  return independentVersions.map((entry) => ({
    name: entry.name,
    actual: entry.file.endsWith(".json") ? readJsonVersion(entry.file) : readTomlVersion(entry.file),
  }));
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const expected = canonicalVersion();
  if (flag("--sync")) {
    for (const carrier of syncedCarriers) {
      const { text, match, value } = read(carrier);
      if (value !== expected) {
        writeFileSync(carrier.file, text.replace(carrier.pattern, `$1${expected}$3`));
        console.log(`${carrier.name}: ${value} -> ${expected}`);
      }
    }
    console.log(`versions synced to ${expected}`);
  } else if (flag("--check")) {
    const rows = checkVersions();
    const drift = rows.filter((r) => r.actual !== r.expected);
    for (const r of rows) console.log(`${r.actual === r.expected ? "✔" : "✖"} ${r.name}: ${r.actual}`);
    if (drift.length) {
      console.error(`version drift (canonical desktop/package.json = ${expected}); run: node scripts/version.mjs --sync`);
      process.exit(1);
    }
    console.log(`all synced versions equal ${expected}`);
    for (const entry of checkIndependentVersions()) {
      console.log(`○ ${entry.name}: ${entry.actual} (independent, not synced)`);
    }
  } else {
    console.log(expected);
  }
}
