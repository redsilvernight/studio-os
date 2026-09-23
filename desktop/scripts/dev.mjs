// Dev loop: Vite dev server for the shared Dashboard + `tauri dev`.
// The dev origin (http://localhost:5173) is the only non-packaged origin the
// shell trusts, and only in a dev build (see src-tauri/src/navigation.rs).
import { spawn } from "node:child_process";
import { dashboardDir, desktopDir, runOrFail, tauriCli, toolEnv, viteCli } from "./lib.mjs";

await runOrFail(process.execPath, [`${desktopDir}/scripts/check-prereqs.mjs`]);

const vite = spawn(process.execPath, [viteCli(), "--strictPort"], {
  cwd: dashboardDir,
  env: toolEnv(),
  stdio: "inherit",
});
const stop = () => vite.kill();
process.on("exit", stop);

for (let i = 0; i < 60; i += 1) {
  try {
    if ((await fetch("http://localhost:5173/")).ok) break;
  } catch {
    /* not up yet */
  }
  await new Promise((r) => setTimeout(r, 500));
}

const child = spawn(process.execPath, [tauriCli(), "dev"], { cwd: desktopDir, env: toolEnv(), stdio: "inherit" });
child.on("exit", (code) => {
  stop();
  process.exit(code ?? 0);
});
