// Windows code signing (Authenticode) helpers — B4.
//
// Order matters: Authenticode is applied DURING `tauri build` (via the
// `bundle.windows` overlay in make-config.mjs), so the minisign updater
// signatures Tauri produces cover the final signed bytes. Signing after the
// build would invalidate the `.sig` updater artifacts.
//
// Secrets (CI `desktop-release` environment, never committed):
//   WINDOWS_CERT_THUMBPRINT      SHA1 thumbprint of the code-signing cert in
//                                Cert:\\CurrentUser\\My on the build machine.
//   WINDOWS_SIGN_PFX_BASE64      alternative: base64 PFX imported by build.mjs
//                                before the Tauri build (needs WINDOWS_SIGN_PASSWORD).
//   WINDOWS_SIGN_PASSWORD        PFX password (empty string allowed, but the var
//                                must exist when a PFX is given).
//   WINDOWS_SIGN_TIMESTAMP_URL   RFC3161 server (default Digicert).
//   WINDOWS_SIGN_DIGEST_ALGORITHM sha256 (default) | sha384 | sha512.
//   STUDIO_REQUIRE_AUTHENTICODE=1 fail-closed: build and verify refuse to
//                                produce/accept an unsigned installer.
//
// No certificate (DEC-0129: refused on cost, no free alternative): the installer
// stays unsigned and the build logs it; SmartScreen will warn. That is the
// accepted distribution model — trust comes from minisign + SHA256SUMS +
// provenance (see §9 of docs/DESKTOP_P10_PACKAGING.md). The signing path below
// stays dormant until a certificate is ever configured.
import { spawnSync } from "node:child_process";
import { existsSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { arg, capture, flag } from "./lib.mjs";

export const DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com";
export const DEFAULT_DIGEST_ALGORITHM = "sha256";
const ALLOWED_DIGESTS = new Set(["sha256", "sha384", "sha512"]);
const THUMBPRINT_RE = /^[0-9a-fA-F]{40}$/;

function cleanThumbprint(raw) {
  return String(raw ?? "").replace(/[\s:]/g, "");
}

/**
 * Overlay fragment for `bundle.windows` from the environment, or `undefined`
 * when no certificate is configured. Throws on a malformed configuration —
 * a half-configured release must fail here, not ship unsigned.
 */
export function windowsSigningFromEnv(env = process.env) {
  const thumbprint = cleanThumbprint(env.WINDOWS_CERT_THUMBPRINT);
  const timestampUrl = (env.WINDOWS_SIGN_TIMESTAMP_URL ?? DEFAULT_TIMESTAMP_URL).trim();
  const digest = (env.WINDOWS_SIGN_DIGEST_ALGORITHM ?? DEFAULT_DIGEST_ALGORITHM).trim().toLowerCase();
  if (!env.WINDOWS_CERT_THUMBPRINT) return undefined;
  if (!THUMBPRINT_RE.test(thumbprint)) {
    throw new Error("WINDOWS_CERT_THUMBPRINT must be the 40-hex SHA1 thumbprint of the signing certificate");
  }
  if (!/^https?:\/\/[^/]+$/i.test(timestampUrl) && !/^https?:\/\/[^/]+\/\S*$/i.test(timestampUrl)) {
    throw new Error(`WINDOWS_SIGN_TIMESTAMP_URL is not an http(s) URL: ${timestampUrl}`);
  }
  if (!ALLOWED_DIGESTS.has(digest)) {
    throw new Error(`WINDOWS_SIGN_DIGEST_ALGORITHM must be one of sha256/sha384/sha512, got: ${digest}`);
  }
  return { certificateThumbprint: thumbprint.toUpperCase(), digestAlgorithm: digest, timestampUrl };
}

/** Fail-closed switch used by release builds. */
export function requireWindowsSigning(env = process.env) {
  return env.STUDIO_REQUIRE_AUTHENTICODE === "1";
}

/**
 * PFX import described by the environment, or `undefined` when none is given.
 * Throws when a PFX is given without its password variable.
 */
export function pfxImportFromEnv(env = process.env) {
  if (!env.WINDOWS_SIGN_PFX_BASE64) return undefined;
  if (!("WINDOWS_SIGN_PASSWORD" in env)) {
    throw new Error("WINDOWS_SIGN_PFX_BASE64 is set but WINDOWS_SIGN_PASSWORD is missing");
  }
  return { pfxBase64: env.WINDOWS_SIGN_PFX_BASE64, password: env.WINDOWS_SIGN_PASSWORD };
}

/**
 * Import a PFX file into Cert:\\CurrentUser\\My (Windows only) and return its
 * SHA1 thumbprint. The password travels via an env var, never the command line.
 */
export function importPfx(pfxPath, password) {
  if (process.platform !== "win32") {
    throw new Error(`PFX import needs Windows (current platform: ${process.platform})`);
  }
  const script = [
    "$pfx = Import-PfxCertificate -FilePath $env:STUDIO_PFX_PATH",
    " -CertStoreLocation Cert:\\CurrentUser\\My",
    " -Password (ConvertTo-SecureString -String $env:STUDIO_PFX_PASSWORD -AsPlainText -Force)",
    " -Exportable:$false | Select-Object -ExpandProperty Thumbprint",
    "Write-Output $pfx",
  ].join("");
  const r = spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", script], {
    encoding: "utf8",
    env: { ...process.env, STUDIO_PFX_PATH: pfxPath, STUDIO_PFX_PASSWORD: password },
  });
  const thumbprint = cleanThumbprint((r.stdout ?? "").trim().split(/\r?\n/).pop() ?? "");
  if (r.status !== 0 || !THUMBPRINT_RE.test(thumbprint)) {
    throw new Error(`PFX import failed${r.status ? ` (exit ${r.status})` : ""}: ${(r.stderr ?? "").trim().slice(-500)}`);
  }
  return thumbprint.toUpperCase();
}

/** Every .exe under the given directories (installer + sidecar outputs). */
export function collectSignTargets(dirs) {
  const out = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.isFile() && /\.exe$/i.test(entry.name)) out.push(full);
    }
  };
  for (const dir of dirs) {
    if (!existsSync(dir) || !statSync(dir).isDirectory()) {
      throw new Error(`sign-target directory missing: ${dir}`);
    }
    walk(dir);
  }
  return out.sort();
}

/** Locate signtool.exe (PATH, then the newest Windows 10 SDK). */
export function findSigntool() {
  if (process.platform !== "win32") return null;
  const onPath = capture("where", ["signtool.exe"]);
  if (onPath.ok) return onPath.stdout.split(/\r?\n/).filter(Boolean)[0];
  try {
    const kits = "C:\\Program Files (x86)\\Windows Kits\\10\\bin";
    const versions = readdirSync(kits).filter((v) => /^\d+\./.test(v)).sort();
    for (let i = versions.length - 1; i >= 0; i--) {
      const candidate = join(kits, versions[i], "x64", "signtool.exe");
      if (existsSync(candidate)) return candidate;
    }
  } catch {
    /* no SDK layout — caller reports it */
  }
  return null;
}

/** `signtool verify /pa` on one file: chain-trusted Authenticode signature. */
export function verifyFile(file, signtool = findSigntool()) {
  if (!signtool) return { file, ok: false, detail: "signtool.exe not found (Windows SDK required)" };
  const r = spawnSync(signtool, ["verify", "/pa", "/v", file], { encoding: "utf8" });
  const detail = `${r.stdout ?? ""}\n${r.stderr ?? ""}`.trim().split(/\r?\n/).slice(-3).join(" | ").slice(0, 300);
  return { file, ok: r.status === 0, detail };
}

export function verifySignatures(files) {
  const signtool = findSigntool();
  return files.map((f) => verifyFile(f, signtool));
}

function usage() {
  console.log("usage:");
  console.log("  node scripts/windows-signing.mjs --verify --dir <dir> [--dir ...] [--require]");
  console.log("  node scripts/windows-signing.mjs --check-env [--require]");
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (flag("--check-env")) {
    const required = flag("--require") || requireWindowsSigning();
    try {
      const signing = windowsSigningFromEnv();
      console.log(signing ? `configured: thumbprint ${signing.certificateThumbprint.slice(0, 8)}… digest ${signing.digestAlgorithm}` : "not configured (dev installers stay unsigned)");
      if (!signing && required) {
        console.error("STUDIO_REQUIRE_AUTHENTICODE=1 but no signing certificate is configured");
        process.exit(1);
      }
    } catch (e) {
      console.error(String(e.message ?? e));
      process.exit(1);
    }
  } else if (flag("--verify")) {
    const required = flag("--require") || requireWindowsSigning();
    const dirs = process.argv.flatMap((a, i) => (a === "--dir" && process.argv[i + 1] ? [process.argv[i + 1]] : []));
    if (dirs.length === 0) {
      console.error("missing --dir <bundle-or-install-dir> (repeatable)");
      process.exit(2);
    }
    if (process.platform !== "win32") {
      console.log(`SKIP: Authenticode verification needs Windows (current: ${process.platform})`);
      process.exit(required ? 1 : 0);
    }
    let files;
    try {
      files = collectSignTargets(dirs);
    } catch (e) {
      console.error(String(e.message ?? e));
      process.exit(1);
    }
    if (files.length === 0) {
      console.error(`no .exe found under ${dirs.join(", ")}`);
      process.exit(1);
    }
    const results = verifySignatures(files);
    for (const r of results) console.log(`${r.ok ? "SIGNED " : "UNSIGNED"}  ${r.file}${r.ok ? "" : `  (${r.detail})`}`);
    const bad = results.filter((r) => !r.ok);
    if (bad.length > 0) {
      // DEC-0129: unsigned distribution is the accepted default, so report-only
      // unless --require (or STUDIO_REQUIRE_AUTHENTICODE=1) demands signatures.
      console.error(`${bad.length}/${results.length} file(s) without a valid Authenticode signature`);
      process.exit(required ? 1 : 0);
    }
    console.log(`all ${results.length} executable(s) carry a valid Authenticode signature`);
  } else {
    usage();
    process.exit(2);
  }
}
