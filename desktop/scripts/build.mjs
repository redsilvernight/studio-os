// Reproducible Desktop build (no installer: `bundle.active` is false in P2).
//
//   node scripts/build.mjs [--api-url <origin>] [--sidecar]
//
// 1. builds the SHARED Dashboard (dashboard/, Vite) into desktop/.build/dashboard
//    with VITE_STUDIO_API_URL = the API this build talks to;
// 2. derives the Tauri config overlay (CSP incl. that API origin, optional sidecar);
// 3. freezes the daemon spike when --sidecar is given;
// 4. compiles the shell with `tauri build --no-bundle`.
import { join } from "node:path";
import { arg, dashboardDir, dashboardOut, DEFAULT_API_URL, desktopDir, flag, overlayPath, runOrFail, tauriCli, viteCli } from "./lib.mjs";

const apiUrl = arg("--api-url", process.env.STUDIO_DESKTOP_API_URL ?? DEFAULT_API_URL);
const sidecar = flag("--sidecar");
const node = process.execPath;

await runOrFail(node, [join(desktopDir, "scripts", "check-prereqs.mjs")]);

console.log(`\n▶ Dashboard build (API: ${apiUrl})`);
await runOrFail(node, [viteCli(), "build", "--outDir", dashboardOut, "--emptyOutDir"], {
  cwd: dashboardDir,
  env: { VITE_STUDIO_API_URL: apiUrl },
});

const cfg = [join(desktopDir, "scripts", "make-config.mjs"), "--api-url", apiUrl];
if (sidecar) cfg.push("--sidecar");
await runOrFail(node, cfg);

if (sidecar) {
  console.log("\n▶ Sidecar spike (PyInstaller)");
  await runOrFail(node, [join(desktopDir, "scripts", "build-sidecar.mjs")]);
}

console.log("\n▶ Tauri build (--no-bundle)");
await runOrFail(node, [tauriCli(), "build", "--no-bundle", "--config", overlayPath]);
console.log("\n✔ built: desktop/src-tauri/target/release/studio-desktop.exe");
