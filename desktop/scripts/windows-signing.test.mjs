import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import test from "node:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  collectSignTargets,
  DEFAULT_DIGEST_ALGORITHM,
  DEFAULT_TIMESTAMP_URL,
  pfxImportFromEnv,
  requireWindowsSigning,
  windowsSigningFromEnv,
} from "./windows-signing.mjs";

const THUMB = "A1B2C3D4E5F60718293A4B5C6D7E8F9012345678";

test("no certificate means no signing, without failing", () => {
  assert.equal(windowsSigningFromEnv({}), undefined);
});

test("a valid thumbprint yields the Tauri windows signing block with timestamp defaults", () => {
  const out = windowsSigningFromEnv({ WINDOWS_CERT_THUMBPRINT: THUMB });
  assert.deepEqual(out, {
    certificateThumbprint: THUMB,
    digestAlgorithm: DEFAULT_DIGEST_ALGORITHM,
    timestampUrl: DEFAULT_TIMESTAMP_URL,
  });
});

test("thumbprint case and separators are normalized", () => {
  const out = windowsSigningFromEnv({ WINDOWS_CERT_THUMBPRINT: ` ${THUMB.toLowerCase()} ` });
  assert.equal(out.certificateThumbprint, THUMB);
});

test("a malformed thumbprint fails closed, never silently unsigned", () => {
  for (const bad of ["short", "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ", "A1B2"]) {
    assert.throws(() => windowsSigningFromEnv({ WINDOWS_CERT_THUMBPRINT: bad }), /THUMBPRINT/);
  }
  assert.equal(windowsSigningFromEnv({ WINDOWS_CERT_THUMBPRINT: "" }), undefined);
});

test("timestamp and digest overrides are validated", () => {
  const ok = windowsSigningFromEnv({
    WINDOWS_CERT_THUMBPRINT: THUMB,
    WINDOWS_SIGN_TIMESTAMP_URL: "http://timestamp.sectigo.com",
    WINDOWS_SIGN_DIGEST_ALGORITHM: "SHA512",
  });
  assert.equal(ok.timestampUrl, "http://timestamp.sectigo.com");
  assert.equal(ok.digestAlgorithm, "sha512");
  assert.throws(
    () => windowsSigningFromEnv({ WINDOWS_CERT_THUMBPRINT: THUMB, WINDOWS_SIGN_TIMESTAMP_URL: "not-a-url" }),
    /TIMESTAMP_URL/,
  );
  assert.throws(
    () => windowsSigningFromEnv({ WINDOWS_CERT_THUMBPRINT: THUMB, WINDOWS_SIGN_DIGEST_ALGORITHM: "md5" }),
    /DIGEST_ALGORITHM/,
  );
});

test("the fail-closed switch is opt-in only", () => {
  assert.equal(requireWindowsSigning({}), false);
  assert.equal(requireWindowsSigning({ STUDIO_REQUIRE_AUTHENTICODE: "0" }), false);
  assert.equal(requireWindowsSigning({ STUDIO_REQUIRE_AUTHENTICODE: "1" }), true);
});

test("a PFX without its password variable fails closed", () => {
  assert.equal(pfxImportFromEnv({}), undefined);
  assert.throws(() => pfxImportFromEnv({ WINDOWS_SIGN_PFX_BASE64: "aGk=" }), /WINDOWS_SIGN_PASSWORD/);
  const ok = pfxImportFromEnv({ WINDOWS_SIGN_PFX_BASE64: "aGk=", WINDOWS_SIGN_PASSWORD: "" });
  assert.equal(ok.password, "");
});

test("sign targets collect every .exe recursively and nothing else", () => {
  const dir = mkdtempSync(join(tmpdir(), "studio-sign-targets-"));
  try {
    mkdirSync(join(dir, "sidecar"));
    writeFileSync(join(dir, "setup.exe"), "a");
    writeFileSync(join(dir, "setup.exe.sig"), "b");
    writeFileSync(join(dir, "sidecar", "studio-daemon.exe"), "c");
    writeFileSync(join(dir, "notes.txt"), "d");
    const found = collectSignTargets([dir]).map((f) => f.slice(dir.length + 1));
    assert.deepEqual(found, [join("setup.exe"), join("sidecar", "studio-daemon.exe")].sort());
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a missing target directory fails closed", () => {
  assert.throws(() => collectSignTargets([join(tmpdir(), "studio-sign-targets-does-not-exist")]), /missing/);
});

test("verify without --require reports instead of failing (DEC-0129)", () => {
  if (process.platform === "win32") return; // needs signtool + real binaries; CI Windows covers it
  const dir = mkdtempSync(join(tmpdir(), "studio-sign-report-"));
  try {
    writeFileSync(join(dir, "setup.exe"), "a");
    const cli = join(dirname(fileURLToPath(import.meta.url)), "windows-signing.mjs");
    const report = execFileSync(process.execPath, [cli, "--verify", "--dir", dir], { encoding: "utf8" });
    assert.match(report, /SKIP/);
    assert.throws(() => execFileSync(process.execPath, [cli, "--verify", "--require", "--dir", dir], { stdio: "pipe" }));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("the Tauri overlay carries the signing block only when configured", async () => {
  const { overlay } = await import("./make-config.mjs");
  const plain = overlay({ apiUrl: "https://a.example" });
  assert.ok(!("windows" in (plain.bundle ?? {})));
  const signing = windowsSigningFromEnv({ WINDOWS_CERT_THUMBPRINT: THUMB });
  const signed = overlay({ apiUrl: "https://a.example", installer: true, signing });
  assert.equal(signed.bundle.active, true);
  assert.equal(signed.bundle.windows.certificateThumbprint, THUMB);
  assert.equal(signed.bundle.windows.digestAlgorithm, DEFAULT_DIGEST_ALGORITHM);
  assert.equal(signed.bundle.windows.timestampUrl, DEFAULT_TIMESTAMP_URL);
});
