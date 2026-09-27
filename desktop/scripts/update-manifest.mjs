// Update feed manifest (B5/T2): the `latest.json` a Desktop build's updater reads.
//
//   node scripts/update-manifest.mjs --bundle-dir <dir> --url-base <https url>
//        [--channel prod|dev] [--version <semver>] [--installer <file>]
//        [--notes <text>] [--api-url <origin>] [--out <path>]
//
// Reads the NSIS installer and its Tauri minisign signature (`<installer>.sig`)
// and writes `latest.json` in the `tauri-plugin-updater` static format
// (`version`, `notes`, `pub_date`, `platforms[target]{url,signature}`) plus an
// additive, versioned block the plugin does not know about and therefore
// ignores (`schema_version`, `channel`, `artifacts{file,size_bytes,sha256}`,
// `api_origin`). A new optional field can never break an older reader (B5
// acceptance criterion 4); this is proven by the Rust updater test accepting a
// manifest that carries them. Only an https URL is ever recorded, and never
// file bytes.
//
// `channel` maps the build channel to the public release lane (DEC-0108):
// `dev` -> `beta`, `prod` -> `stable`. `api_origin` is the API origin baked into
// the build; a later promotion (C3) refuses to move an artefact between lanes
// whose origins differ (a stable feed must never point at a dev API).
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { arg, buildChannel, flag, tauriDir } from "./lib.mjs";
import { canonicalVersion } from "./version.mjs";
import { sha256Of } from "./release-artifacts.mjs";

/** The platform key `tauri-plugin-updater` looks a release up under (2.12). */
export function updaterTarget(platform = process.platform, arch = process.arch) {
  const os = { win32: "windows", darwin: "darwin", linux: "linux" }[platform];
  const cpu = { x64: "x86_64", arm64: "aarch64", ia32: "i686", arm: "armv7" }[arch];
  if (!os || !cpu) throw new Error(`unsupported updater target: ${platform}-${arch}`);
  return `${os}-${cpu}`;
}

/** The public release lane of a build channel (DEC-0108). */
export function publicChannel(channel) {
  if (channel === "dev") return "beta";
  if (channel === "prod") return "stable";
  throw new Error(`unknown build channel: ${channel}`);
}

export function installerIn(bundleDir, installer) {
  if (installer) return installer;
  const exes = readdirSync(bundleDir).filter((name) => /\.exe$/i.test(name));
  if (exes.length === 0) throw new Error(`no installer (*.exe) in ${bundleDir}`);
  if (exes.length > 1) throw new Error(`several installers in ${bundleDir}, pass --installer`);
  return exes[0];
}

/** The HTTPS URL an asset of a GitHub release is downloaded from. */
export function assetUrl(urlBase, filename) {
  const url = new URL(urlBase);
  if (url.protocol !== "https:") throw new Error(`update feed base must be https: ${urlBase}`);
  return `${url.href.replace(/\/+$/, "")}/${encodeURIComponent(filename)}`;
}

/** The API origin baked into the build, or undefined when none was given. */
export function apiOrigin(apiUrl) {
  if (!apiUrl) return undefined;
  try {
    return new URL(apiUrl).origin;
  } catch {
    throw new Error(`api url is not a valid origin: ${apiUrl}`);
  }
}

export function buildManifest({ bundleDir, urlBase, channel = "prod", version, installer, assetName, notes, pubDate, apiUrl } = {}) {
  const name = installerIn(bundleDir, installer);
  const path = join(bundleDir, name);
  if (!existsSync(`${path}.sig`)) {
    throw new Error(`no updater signature for ${name} (was the updater compiled in?)`);
  }
  const signature = readFileSync(`${path}.sig`, "utf8").trim();
  if (!signature) throw new Error(`empty updater signature for ${name} (was the updater compiled in?)`);
  const target = updaterTarget();
  // The downloaded asset may be renamed by the publisher (channels rename it),
  // but the signature covers the bytes, not the name.
  const asset = assetName ?? name;
  const url = assetUrl(urlBase, asset);
  const release = version ?? canonicalVersion();
  const origin = apiOrigin(apiUrl);
  return {
    version: release,
    notes: notes ?? `Studi'OS Desktop ${release}`,
    pub_date: pubDate ?? new Date().toISOString(),
    platforms: { [target]: { url, signature } },
    schema_version: 1,
    channel: publicChannel(channel),
    artifacts: { [target]: { file: asset, size_bytes: statSync(path).size, sha256: sha256Of(path) } },
    ...(origin ? { api_origin: origin } : {}),
  };
}

export function writeManifest(path, manifest) {
  writeFileSync(path, `${JSON.stringify(manifest, null, 2)}\n`);
  return manifest;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const bundleDir = arg("--bundle-dir", join(tauriDir, "target", "release", "bundle", "nsis"));
  const urlBase = arg("--url-base", process.env.STUDIO_RELEASE_URL_BASE);
  if (!urlBase) {
    console.error("✖ --url-base <https url> (or STUDIO_RELEASE_URL_BASE) is required");
    process.exit(1);
  }
  const out = arg("--out", join(bundleDir, "latest.json"));
  const manifest = writeManifest(
    out,
    buildManifest({
      bundleDir,
      urlBase,
      channel: buildChannel(),
      version: arg("--version"),
      installer: arg("--installer"),
      assetName: arg("--asset-name"),
      notes: arg("--notes"),
      apiUrl: arg("--api-url", process.env.STUDIO_DESKTOP_API_URL),
    }),
  );
  const platform = manifest.platforms[updaterTarget()];
  console.log(`latest.json: ${manifest.channel} ${manifest.version} -> ${platform.url}`);
}
