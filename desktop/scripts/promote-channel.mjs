// Restoration of an already built Desktop artefact into its own public release
// lane (DEC-0108, restricted by DEC-0162): an older artefact of `beta` or
// `stable` is re-published on that same lane by rewriting the manifest and
// copying the installer unchanged, never by rebuilding. Cross-lane promotion
// is refused: Dev and Prod are distinct builds. A rebuild of the same tag
// produces different bytes and a different SHA-256, so it can never be the
// restored artefact.
//
//   node scripts/promote-channel.mjs --dir <downloaded src> --url-base <https url>
//        [--to stable|beta] [--out <dir>] [--asset-name <file>]
//        [--source-file <file>] [--api-url <target origin>]
//
// `--dir` holds the source `latest.json` and the installer it describes.
// `--source-file` selects the bytes to copy when the manifest names a moving
// asset but the retained file is versioned (rollback / retour vers stable).
import { copyFileSync, existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { arg } from "./lib.mjs";
import { sha256Of } from "./release-artifacts.mjs";
import { assetUrl, updaterTarget, writeManifest } from "./update-manifest.mjs";

/** The public release lanes (DEC-0108). */
export const LANES = ["beta", "stable"];

/** The GitHub release tag a lane publishes to (DEC-0133). */
export function laneRelease(lane) {
  if (lane === "beta") return "desktop-dev";
  if (lane === "stable") return "desktop-prod";
  throw new Error(`unknown lane: ${lane} (expected ${LANES.join(", ")})`);
}

export function readManifest(dir, name = "latest.json") {
  const path = join(dir, name);
  if (!existsSync(path)) throw new Error(`no manifest at ${path}`);
  return JSON.parse(readFileSync(path, "utf8"));
}

/** The updater entry (platform + artifact) a manifest must carry to be promotable. */
export function artifactOf(manifest, target = updaterTarget()) {
  const platform = manifest.platforms?.[target];
  const artifact = manifest.artifacts?.[target];
  if (!platform?.url || !platform?.signature) {
    throw new Error(`source manifest has no signed ${target} platform`);
  }
  if (!artifact?.file || !artifact?.sha256) {
    throw new Error(`source manifest carries no ${target} artifact`);
  }
  return artifact;
}

/**
 * The bytes on disk must be exactly the ones the manifest describes: a hash or
 * size mismatch means the file was rebuilt or tampered with, never promoted.
 */
export function verifyArtifact(dir, artifact, sourceFile) {
  const file = sourceFile ?? artifact.file;
  const path = join(dir, file);
  if (!existsSync(path)) throw new Error(`no artefact at ${path}`);
  const size = statSync(path).size;
  if (size !== artifact.size_bytes) {
    throw new Error(`size_mismatch: ${file} is ${size} bytes, manifest says ${artifact.size_bytes}`);
  }
  const sha256 = sha256Of(path);
  if (sha256 !== artifact.sha256) {
    throw new Error(
      `hash_mismatch: ${file} is ${sha256}, manifest says ${artifact.sha256} (a rebuild is never the promoted artefact)`,
    );
  }
  return path;
}

/** The same artefact pointed at the target lane: manifest rewritten, bytes kept. */
export function promoteManifest(source, { to, urlBase, assetName, apiUrl } = {}) {
  if (!LANES.includes(to)) throw new Error(`unknown target lane: ${to} (expected ${LANES.join(", ")})`);
  // DEC-0162: Dev and Prod are distinct builds (identity, origins), so an
  // artefact is only ever restored into the lane it was built for.
  if (source.channel !== to) {
    throw new Error(
      `lane_mismatch: source artefact belongs to ${source.channel ?? "an unknown lane"}, target is ${to} (cross-lane promotion is forbidden by DEC-0162)`,
    );
  }
  const target = updaterTarget();
  const artifact = artifactOf(source, target);
  const origin = apiUrl ? new URL(apiUrl).origin : undefined;
  if (origin && source.api_origin && new URL(source.api_origin).origin !== origin) {
    throw new Error(
      `api_origin_mismatch: source targets ${source.api_origin}, target expects ${origin} (a stable feed must not point at a dev API)`,
    );
  }
  const asset = assetName ?? artifact.file;
  return {
    ...source,
    channel: to,
    promoted_from: source.channel ?? null,
    platforms: { ...source.platforms, [target]: { ...source.platforms[target], url: assetUrl(urlBase, asset) } },
    artifacts: { ...source.artifacts, [target]: { ...artifact, file: asset } },
  };
}

/** Validates and promotes in one step; returns the promoted manifest. */
export function promote({ dir, out, to, urlBase, assetName, sourceFile, apiUrl }) {
  if (!urlBase) throw new Error("--url-base <https url> is required");
  const source = readManifest(dir);
  const artifact = artifactOf(source);
  const from = verifyArtifact(dir, artifact, sourceFile);
  const promoted = promoteManifest(source, { to, urlBase, assetName, apiUrl });
  const asset = promoted.artifacts[updaterTarget()].file;
  if (out !== dir || asset !== artifact.file) {
    mkdirSync(out, { recursive: true });
    copyFileSync(from, join(out, asset));
  }
  writeManifest(join(out, "latest.json"), promoted);
  return promoted;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const dir = arg("--dir");
  if (!dir) {
    console.error("✖ --dir <downloaded source> is required");
    process.exit(1);
  }
  try {
    const to = arg("--to", "stable");
    const promoted = promote({
      dir,
      out: arg("--out", dir),
      to,
      urlBase: arg("--url-base", process.env.STUDIO_RELEASE_URL_BASE),
      assetName: arg("--asset-name"),
      sourceFile: arg("--source-file"),
      apiUrl: arg("--api-url", process.env.STUDIO_DESKTOP_API_URL),
    });
    const platform = promoted.platforms[updaterTarget()];
    console.log(
      `promoted ${promoted.version} ${promoted.promoted_from ?? "?"} -> ${promoted.channel}: ${platform.url}`,
    );
  } catch (error) {
    console.error(`✖ ${error.message}`);
    process.exit(1);
  }
}
