// Freezes the P4 daemon service into the fixed executable expected by Tauri.
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
    "--name", "studio-daemon",
    "--distpath", dist, "--workpath", join(work, "work"), "--specpath", work,
    "--hidden-import", "keyring.backends.Windows",
    join(desktopDir, "sidecar", "studio_daemon.py"),
  ],
  { cwd: repoRoot },
);

const ext = process.platform === "win32" ? ".exe" : "";
const binaries = join(tauriDir, "binaries");
mkdirSync(binaries, { recursive: true });
const target = join(binaries, `studio-daemon-${triple}${ext}`);
copyFileSync(join(dist, `studio-daemon${ext}`), target);
console.log(`sidecar ready: ${target}`);
