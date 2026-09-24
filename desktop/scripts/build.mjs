// Reproducible Desktop build.
//
//   node scripts/build.mjs [--api-url <origin>] [--storage-url <origin>] [--sidecar] [--installer]
//
// Without --installer: the bare executable (`--no-bundle`, `bundle.active` false).
// With --installer: also freezes the daemon and produces the NSIS per-user
// installer (implies --sidecar). A missing tool or version drift fails the build;
// nothing is downloaded silently except the NSIS toolchain the Tauri CLI manages.
// When STUDIO_UPDATER_PUBKEY + STUDIO_UPDATER_ENDPOINT are set the update
// mechanism is compiled in and the artifacts must be signed
// (TAURI_SIGNING_PRIVATE_KEY[_PASSWORD]); without them there is no updater.
//
// 1. builds the SHARED Dashboard (dashboard/, Vite) into desktop/.build/dashboard
//    with VITE_STUDIO_API_URL = the API this build talks to;
// 2. derives the Tauri config overlay (CSP incl. that API origin and, with
//    --storage-url, the pre-signed transfer storage origin; optional sidecar);
// 3. freezes the daemon service when --sidecar is given;
//    and writes its third-party inventory (fails on an undeclared/unreviewed license);
// 4. compiles the shell with `tauri build --no-bundle` (or `--bundles nsis` with --installer).
import { join } from "node:path";
import { ALLOW_INSECURE_ORIGIN_ENV, allowInsecureOrigin, arg, dashboardDir, dashboardOut, DEFAULT_API_URL, desktopDir, flag, overlayPath, runOrFail, tauriCli, validateBuildApiUrl, viteCli } from "./lib.mjs";

const insecureOriginAllowed = allowInsecureOrigin();
const apiUrl = validateBuildApiUrl(
  arg("--api-url", process.env.STUDIO_DESKTOP_API_URL ?? DEFAULT_API_URL),
  insecureOriginAllowed,
);
const storageArg = arg("--storage-url", process.env.STUDIO_DESKTOP_STORAGE_URL);
const storageUrl = storageArg ? validateBuildApiUrl(storageArg, insecureOriginAllowed) : undefined;
const installer = flag("--installer");
const sidecar = flag("--sidecar") || installer;
const node = process.execPath;

await runOrFail(node, [join(desktopDir, "scripts", "check-prereqs.mjs"), ...(sidecar ? ["--sidecar"] : [])]);
await runOrFail(node, [join(desktopDir, "scripts", "version.mjs"), "--check"]);

console.log(`\n▶ Dashboard build (API: ${apiUrl})`);
await runOrFail(node, [viteCli(), "build", "--outDir", dashboardOut, "--emptyOutDir"], {
  cwd: dashboardDir,
  env: { VITE_STUDIO_API_URL: apiUrl },
});

const cfg = [join(desktopDir, "scripts", "make-config.mjs"), "--api-url", apiUrl];
if (storageUrl) cfg.push("--storage-url", storageUrl);
if (sidecar) cfg.push("--sidecar");
if (installer) cfg.push("--installer");
await runOrFail(node, cfg);

if (sidecar) {
  console.log("\n▶ Daemon sidecar (PyInstaller)");
  await runOrFail(node, [join(desktopDir, "scripts", "build-sidecar.mjs")]);
  console.log("\n▶ Third-party inventory");
  await runOrFail(node, [join(desktopDir, "scripts", "notices.mjs"), "--check"]);
}

const tauriArgs = installer ? ["build", "--bundles", "nsis"] : ["build", "--no-bundle"];
console.log(`\n▶ Tauri build (${tauriArgs.slice(1).join(" ")})`);
await runOrFail(node, [tauriCli(), ...tauriArgs, "--config", overlayPath], {
  env: {
    STUDIO_DESKTOP_API_URL: apiUrl,
    [ALLOW_INSECURE_ORIGIN_ENV]: insecureOriginAllowed ? "1" : "0",
  },
});
console.log("\n✔ built: desktop/src-tauri/target/release/studio-desktop.exe");
if (installer) console.log("✔ installer: desktop/src-tauri/target/release/bundle/nsis/");
