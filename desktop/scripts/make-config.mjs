// Derives the build-specific Tauri config overlay (never hand-edited).
//
//   node scripts/make-config.mjs [--api-url <origin>] [--storage-url <origin>] [--channel prod|dev] [--sidecar] [--installer]   # write .build/tauri.overlay.json
//   node scripts/make-config.mjs --check                            # base config CSP is in sync
//
// The Content-Security-Policy is built from the Dashboard's own policy module
// (dashboard/csp-policy.ts) so there is one definition; the desktop build only
// adds what the shell needs: the IPC origin and — because a Tauri CSP is static
// per build — the API origin this build talks to and, when given, the storage
// origin of the pre-signed transfer URLs (direct uploads, DEC-0025).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { allowInsecureOrigin, arg, buildChannel, buildDir, CHANNELS, dashboardDir, DEFAULT_API_URL, flag, overlayPath, tauriDir, validateBuildApiUrl } from "./lib.mjs";
import { windowsSigningFromEnv } from "./windows-signing.mjs";

const { buildDashboardCsp } = await import(pathToFileURL(join(dashboardDir, "csp-policy.ts")).href);

export function apiOrigin(apiUrl) {
  const u = new URL(apiUrl);
  if (!["http:", "https:"].includes(u.protocol)) throw new Error(`API url must be http(s): ${apiUrl}`);
  return u.origin;
}

/** Desktop CSP: Dashboard policy + IPC + optional API and storage origins; never framed. */
export function desktopCsp(apiUrl, storageUrl) {
  const origins = [apiUrl, storageUrl].filter(Boolean).map(apiOrigin);
  const extra = ["ipc:", "http://ipc.localhost", ...new Set(origins)];
  return buildDashboardCsp({ connectExtra: extra }).replace("frame-ancestors 'self'", "frame-ancestors 'none'");
}

export const CHANNEL_HOOKS_FILE = "installer-hooks.nsh";

/** Channel-specific NSIS hooks: the base hooks with the channel's data folder. */
export function channelHooks(channel) {
  const hooks = join(tauriDir, "installer", "hooks.nsh").replaceAll("/", "\\");
  return `!define STUDIO_DATA_DIR "${CHANNELS[channel].dataDir}"\n!include "${hooks}"\n`;
}

/** The frozen daemon folder, relative to src-tauri (so nothing absolute is written). */
export const SIDECAR_RESOURCE = { "../.build/sidecar/dist/studio-daemon/": "sidecar/" };

/**
 * `sidecar`: ship the frozen daemon as a resource folder (`<install>\sidecar\`).
 * `installer`: switch the bundler on (NSIS, per-user, see tauri.conf.json).
 * `updater`: `{ pubkey, endpoint }` - only then is the update mechanism present;
 *   the public key is baked in and the artifacts are signed by the build.
 * `channel`: `prod` keeps the base identity; `dev` installs side by side
 *   (own identifier, product name, install folder and daemon data folder).
 * `signing`: `{ certificateThumbprint, digestAlgorithm, timestampUrl }` (B4,
 *   dormant per DEC-0129) - Authenticode is applied by Tauri DURING the build,
 *   so the minisign updater signatures cover the final signed bytes. Merged
 *   into `bundle.windows` without overwriting the channel's `nsis` block;
 *   absent when no certificate is configured.
 */
export function overlay({ apiUrl, storageUrl, sidecar, installer = false, updater, channel = "prod", signing }) {
  const out = { app: { security: { csp: desktopCsp(apiUrl, storageUrl) } } };
  const bundle = {};
  if (sidecar) bundle.resources = SIDECAR_RESOURCE;
  if (installer) bundle.active = true;
  const identity = CHANNELS[channel];
  if (identity === undefined) throw new Error(`unknown channel: ${channel}`);
  if (channel !== "prod") {
    out.productName = identity.productName;
    out.identifier = identity.identifier;
    bundle.shortDescription = identity.productName;
    bundle.windows = { nsis: { installerHooks: `../.build/${CHANNEL_HOOKS_FILE}` } };
  }
  if (updater) {
    const url = new URL(updater.endpoint);
    if (url.protocol !== "https:") throw new Error(`updater endpoint must be https: ${updater.endpoint}`);
    if (!updater.pubkey || /\s/.test(updater.pubkey.trim())) throw new Error("updater public key missing or malformed");
    bundle.createUpdaterArtifacts = true;
    out.plugins = { updater: { pubkey: updater.pubkey.trim(), endpoints: [url.href], requireSignedVersion: true } };
  }
  if (signing) bundle.windows = { ...(bundle.windows ?? {}), ...signing };
  if (Object.keys(bundle).length) out.bundle = bundle;
  return out;
}

/** Updater settings from the environment: both or neither (never half configured). */
export function updaterFromEnv(env = process.env) {
  const pubkey = env.STUDIO_UPDATER_PUBKEY;
  const endpoint = env.STUDIO_UPDATER_ENDPOINT;
  if (!pubkey && !endpoint) return undefined;
  if (!pubkey || !endpoint) throw new Error("set both STUDIO_UPDATER_PUBKEY and STUDIO_UPDATER_ENDPOINT, or neither");
  return { pubkey, endpoint };
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (flag("--check")) {
    const base = JSON.parse(readFileSync(join(tauriDir, "tauri.conf.json"), "utf8"));
    if (base.app.security.csp !== desktopCsp(undefined)) {
      console.error("tauri.conf.json CSP drifted from dashboard/csp-policy.ts. Expected:\n" + desktopCsp(undefined));
      process.exit(1);
    }
    console.log("tauri.conf.json CSP in sync with dashboard/csp-policy.ts");
  } else {
    const apiUrl = validateBuildApiUrl(
      arg("--api-url", process.env.STUDIO_DESKTOP_API_URL ?? DEFAULT_API_URL),
      allowInsecureOrigin(),
    );
    const storageArg = arg("--storage-url", process.env.STUDIO_DESKTOP_STORAGE_URL);
    const storageUrl = storageArg ? validateBuildApiUrl(storageArg, allowInsecureOrigin()) : undefined;
    const channel = buildChannel();
    const signing = windowsSigningFromEnv();
    if (signing) console.log(`Authenticode: Tauri will sign with thumbprint ${signing.certificateThumbprint.slice(0, 8)}… (${signing.digestAlgorithm}, ${signing.timestampUrl})`);
    else console.log("Authenticode: no certificate configured — installer will be unsigned (DEC-0129)");
    const out = overlay({ apiUrl, storageUrl, sidecar: flag("--sidecar"), installer: flag("--installer"), updater: updaterFromEnv(), channel, signing });
    mkdirSync(buildDir, { recursive: true });
    if (channel !== "prod") writeFileSync(join(buildDir, CHANNEL_HOOKS_FILE), channelHooks(channel));
    writeFileSync(overlayPath, JSON.stringify(out, null, 2) + "\n");
    console.log(`wrote ${overlayPath}`);
  }
}
