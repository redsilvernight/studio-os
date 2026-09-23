// One version for the whole Desktop distribution.
//
//   node scripts/version.mjs            # print the canonical version
//   node scripts/version.mjs --check    # every carrier equals the canonical version
//   node scripts/version.mjs --sync     # rewrite the carriers from the canonical version
//
// Canonical: desktop/package.json "version". Carriers: the Rust crate (the
// Desktop version reported by the shell and used by Tauri/NSIS, since
// tauri.conf.json deliberately has no "version") and the daemon's
// DAEMON_VERSION. Cargo.lock follows the crate on the next cargo run.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { desktopDir, flag, repoRoot, tauriDir } from "./lib.mjs";

const SEMVER = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;

export const canonicalVersion = () => {
  const version = JSON.parse(readFileSync(join(desktopDir, "package.json"), "utf8")).version;
  if (!SEMVER.test(version)) throw new Error(`desktop/package.json version is not semver: ${version}`);
  return version;
};

const daemonFile = join(repoRoot, "packages", "studio-client", "src", "studio_client", "daemon", "service.py");
const cargoFile = join(tauriDir, "Cargo.toml");

const carriers = [
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

function read(carrier) {
  const text = readFileSync(carrier.file, "utf8");
  const match = carrier.pattern.exec(text);
  if (!match) throw new Error(`${carrier.name}: version declaration not found`);
  return { text, match, value: match[2] };
}

export function checkVersions() {
  const expected = canonicalVersion();
  return carriers.map((carrier) => ({ name: carrier.name, expected, actual: read(carrier).value }));
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const expected = canonicalVersion();
  if (flag("--sync")) {
    for (const carrier of carriers) {
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
    console.log(`all versions equal ${expected}`);
  } else {
    console.log(expected);
  }
}
