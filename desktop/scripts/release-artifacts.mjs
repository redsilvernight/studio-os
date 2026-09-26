// Release hashes and provenance (B3).
//
//   node scripts/release-artifacts.mjs [--bundle-dir <dir>] [--api-url <origin>]
//
// Scans the NSIS bundle directory for release artifacts (*.exe, *.sig),
// writes SHA256SUMS.txt (GNU `sha256sum -c` format) and provenance.json next
// to them: the exact source (commit, tag when the build runs on one, dirty
// flag), the component versions and the builder toolchain. Two builds from the
// same tag are functionally equivalent when hashes match for an identical
// recorded source; the provenance file is what makes that auditable.
//
// The provenance never contains secrets: only the API origin host baked into
// the build is recorded, never keys, tokens or passwords (enforced by test).
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import { pathToFileURL } from "node:url";
import { arg, capture, desktopDir, repoRoot, tauriDir } from "./lib.mjs";
import { canonicalVersion } from "./version.mjs";

const ARTIFACT_PATTERN = /\.(exe|sig)$/i;

export function sha256Of(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

export function collectArtifacts(bundleDir) {
  return readdirSync(bundleDir)
    .filter((name) => ARTIFACT_PATTERN.test(name))
    .map((name) => {
      const path = join(bundleDir, name);
      const { size } = statSync(path);
      return { file: name, sha256: sha256Of(path), bytes: size };
    })
    .sort((a, b) => a.file.localeCompare(b.file));
}

export function gitSource() {
  const commit = capture("git", ["rev-parse", "HEAD"], { cwd: repoRoot });
  const tag = capture("git", ["describe", "--tags", "--exact-match"], { cwd: repoRoot });
  const dirty = capture("git", ["status", "--porcelain"], { cwd: repoRoot });
  return {
    commit: commit.ok ? commit.stdout : "unknown",
    tag: tag.ok ? tag.stdout : null,
    dirty: dirty.ok ? dirty.stdout.length > 0 : true,
  };
}

export function daemonVersion() {
  const source = readFileSync(
    join(repoRoot, "packages", "studio-client", "src", "studio_client", "daemon", "service.py"),
    "utf8",
  );
  return /\nDAEMON_VERSION\s*=\s*"([^"]+)"/.exec(source)?.[1] ?? "unknown";
}

export function buildProvenance({ artifacts, apiUrl }) {
  const node = capture("node", ["--version"]);
  const rustc = capture("rustc", ["-vV"]);
  // Origin only: validateBuildApiUrl guarantees no credentials/path/query.
  const apiOrigin = (() => {
    try {
      return new URL(apiUrl).origin;
    } catch {
      return "unknown";
    }
  })();
  return {
    format: "studio.release-provenance/v1",
    built_at: new Date().toISOString(),
    source: gitSource(),
    versions: { desktop: canonicalVersion(), daemon: daemonVersion() },
    build: { api_origin: apiOrigin, updater_compiled_in: Boolean(process.env.STUDIO_UPDATER_PUBKEY) },
    builder: {
      platform: process.platform,
      arch: process.arch,
      node: node.ok ? node.stdout.split("\n")[0] : "unknown",
      rustc_host: rustc.ok
        ? (rustc.stdout.split("\n").find((l) => l.startsWith("host:")) ?? "unknown")
        : "unknown",
    },
    artifacts,
  };
}

export function writeReleaseFiles(bundleDir, apiUrl) {
  const artifacts = collectArtifacts(bundleDir);
  if (artifacts.length === 0) throw new Error(`no release artifact (*.exe, *.sig) in ${bundleDir}`);
  const sums = `${artifacts.map((a) => `${a.sha256}  ${a.file}`).join("\n")}\n`;
  writeFileSync(join(bundleDir, "SHA256SUMS.txt"), sums);
  const provenance = buildProvenance({ artifacts, apiUrl });
  writeFileSync(join(bundleDir, "provenance.json"), `${JSON.stringify(provenance, null, 2)}\n`);
  return { artifacts, provenance };
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const bundleDir = arg("--bundle-dir", join(tauriDir, "target", "release", "bundle", "nsis"));
  const apiUrl = arg("--api-url", process.env.STUDIO_DESKTOP_API_URL ?? "unknown");
  const { artifacts, provenance } = writeReleaseFiles(bundleDir, apiUrl);
  for (const a of artifacts) console.log(`${a.sha256}  ${a.file}`);
  console.log(`provenance: commit ${provenance.source.commit} tag ${provenance.source.tag ?? "(none)"} dirty=${provenance.source.dirty}`);
}
