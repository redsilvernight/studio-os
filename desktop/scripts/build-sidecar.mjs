// Freezes the P2 daemon spike (desktop/sidecar/studio_daemon_spike.py) into a
// single executable named the way Tauri's `externalBin` expects. This is a
// SPIKE artefact for the P2 gate, not the packaged Studio OS daemon (P4/P10).
import { copyFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { buildDir, desktopDir, hostTriple, repoRoot, runOrFail, tauriDir } from "./lib.mjs";

const triple = hostTriple();
const work = join(buildDir, "sidecar");
const dist = join(work, "dist");
mkdirSync(work, { recursive: true });

await runOrFail(
  "uv",
  [
    "run", "--all-packages", "--with", "pyinstaller",
    "pyinstaller", "--noconfirm", "--clean", "--onefile",
    "--name", "studio-daemon-spike",
    "--distpath", dist, "--workpath", join(work, "work"), "--specpath", work,
    "--hidden-import", "keyring.backends.Windows",
    join(desktopDir, "sidecar", "studio_daemon_spike.py"),
  ],
  { cwd: repoRoot },
);

const ext = process.platform === "win32" ? ".exe" : "";
const binaries = join(tauriDir, "binaries");
mkdirSync(binaries, { recursive: true });
const target = join(binaries, `studio-daemon-spike-${triple}${ext}`);
copyFileSync(join(dist, `studio-daemon-spike${ext}`), target);
console.log(`sidecar ready: ${target}`);
