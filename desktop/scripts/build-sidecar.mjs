// Freezes the P4 daemon service into a self-contained folder (PyInstaller
// --onedir) that the installer ships as `<install dir>\sidecar\`.
//
// --onedir, not --onefile: a onefile executable unpacks itself into %TEMP% at
// every start (slower, antivirus-suspicious, leaves _MEI* folders behind after a
// crash). The folder is installed once, read-only, and never written at runtime.
import { mkdirSync, readFileSync, rmSync, statSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { buildDir, desktopDir, repoRoot, runOrFail } from "./lib.mjs";
import { canonicalVersion } from "./version.mjs";

export const PROTOCOL = "studio.local/v1";
export const sidecarDist = join(buildDir, "sidecar", "dist", "studio-daemon");

// Present in the build environment (workspace dev group) but never imported by the daemon.
const DEV_TOOLING = ["mypy", "mypy_extensions", "pytest", "_pytest", "pluggy", "iniconfig", "pygments", "tkinter"];

const work = join(buildDir, "sidecar");
mkdirSync(work, { recursive: true });
rmSync(sidecarDist, { recursive: true, force: true });

await runOrFail(
  "uv",
  [
    "run", "--all-packages", "--frozen", "--with", "pyinstaller",
    "pyinstaller", "--noconfirm", "--clean", "--onedir",
    "--name", "studio-daemon",
    "--distpath", join(work, "dist"), "--workpath", join(work, "work"), "--specpath", work,
    "--hidden-import", "keyring.backends.Windows",
    ...DEV_TOOLING.flatMap((module) => ["--exclude-module", module]),
    join(desktopDir, "sidecar", "studio_daemon.py"),
  ],
  { cwd: repoRoot },
);

const daemonSource = readFileSync(
  join(repoRoot, "packages", "studio-client", "src", "studio_client", "daemon", "service.py"),
  "utf8",
);
const daemonVersion = /\nDAEMON_VERSION\s*=\s*"([^"]+)"/.exec(daemonSource)?.[1];
if (!daemonVersion) throw new Error("DAEMON_VERSION not found in service.py");

// The shell reads this to refuse a daemon speaking another bridge protocol and
// to flag version drift; it is also the size/version record of the sidecar.
const manifest = { daemon_version: daemonVersion, desktop_version: canonicalVersion(), protocol: PROTOCOL };
writeFileSync(join(sidecarDist, "sidecar-manifest.json"), JSON.stringify(manifest, null, 2) + "\n");

const size = (dir) =>
  readdirSync(dir, { withFileTypes: true }).reduce(
    (sum, e) => sum + (e.isDirectory() ? size(join(dir, e.name)) : statSync(join(dir, e.name)).size),
    0,
  );
console.log(`sidecar ready: ${sidecarDist} (${(size(sidecarDist) / 1e6).toFixed(1)} MB)`);
