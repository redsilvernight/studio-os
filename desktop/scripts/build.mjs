// Reproducible Desktop build.
//
//   node scripts/build.mjs [--api-url <origin>] [--storage-url <origin>] [--channel prod|dev] [--sidecar] [--installer]
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
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { ALLOW_INSECURE_ORIGIN_ENV, allowInsecureOrigin, arg, buildChannel, buildDir, dashboardDir, dashboardOut, DEFAULT_API_URL, desktopDir, flag, overlayPath, runOrFail, tauriCli, tauriDir, validateBuildApiUrl, viteCli } from "./lib.mjs";
import { importPfx, pfxImportFromEnv, requireWindowsSigning, windowsSigningFromEnv } from "./windows-signing.mjs";

const insecureOriginAllowed = allowInsecureOrigin();
const apiUrl = validateBuildApiUrl(
  arg("--api-url", process.env.STUDIO_DESKTOP_API_URL ?? DEFAULT_API_URL),
  insecureOriginAllowed,
);
const storageArg = arg("--storage-url", process.env.STUDIO_DESKTOP_STORAGE_URL);
const storageUrl = storageArg ? validateBuildApiUrl(storageArg, allowInsecureOrigin()) : undefined;
const installer = flag("--installer");
const sidecar = flag("--sidecar") || installer;
const channel = buildChannel();
const node = process.execPath;

await runOrFail(node, [join(desktopDir, "scripts", "check-prereqs.mjs"), ...(sidecar ? ["--sidecar"] : [])]);
await runOrFail(node, [join(desktopDir, "scripts", "version.mjs"), "--check"]);

// B4 — Authenticode before the Tauri build (never after: post-build signing
// would invalidate the minisign updater signatures). Dormant per DEC-0129 (no
// certificate): the installer stays unsigned and SmartScreen will warn, which
// is the accepted distribution model. Only with STUDIO_REQUIRE_AUTHENTICODE=1
// (a future certificate) does a missing certificate fail the build.
const pfx = pfxImportFromEnv();
if (pfx) {
  if (process.platform !== "win32") {
    console.error("✖ WINDOWS_SIGN_PFX_BASE64 is set but code signing needs Windows");
    process.exit(1);
  }
  const pfxPath = join(buildDir, "studio-sign.pfx");
  writeFileSync(pfxPath, Buffer.from(pfx.pfxBase64, "base64"));
  process.env.WINDOWS_CERT_THUMBPRINT = importPfx(pfxPath, pfx.password);
  console.log("▶ Signing certificate imported into Cert:\\CurrentUser\\My");
}
const signing = windowsSigningFromEnv();
if (!signing && requireWindowsSigning()) {
  console.error("✖ STUDIO_REQUIRE_AUTHENTICODE=1 but no signing certificate is configured (WINDOWS_CERT_THUMBPRINT or WINDOWS_SIGN_PFX_BASE64+WINDOWS_SIGN_PASSWORD)");
  process.exit(1);
}

console.log(`\n▶ Dashboard build (API: ${apiUrl})`);
await runOrFail(node, [viteCli(), "build", "--outDir", dashboardOut, "--emptyOutDir"], {
  cwd: dashboardDir,
  env: { VITE_STUDIO_API_URL: apiUrl },
});

const cfg = [join(desktopDir, "scripts", "make-config.mjs"), "--api-url", apiUrl, "--channel", channel];
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
    STUDIO_DESKTOP_CHANNEL: channel,
    [ALLOW_INSECURE_ORIGIN_ENV]: insecureOriginAllowed ? "1" : "0",
  },
});
console.log("\n✔ built: desktop/src-tauri/target/release/studio-desktop.exe");
if (installer) {
  console.log("✔ installer: desktop/src-tauri/target/release/bundle/nsis/");
  // B4 — report the Authenticode state of every delivered executable
  // (DEC-0129: unsigned is accepted; --require only when a certificate exists).
  const verify = [join(desktopDir, "scripts", "windows-signing.mjs"), "--verify", "--dir", join(tauriDir, "target", "release", "bundle", "nsis")];
  if (requireWindowsSigning()) verify.push("--require");
  await runOrFail(node, verify);
}
