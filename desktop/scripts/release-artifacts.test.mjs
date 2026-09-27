import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { buildProvenance, collectArtifacts, sha256Of, writeReleaseFiles } from "./release-artifacts.mjs";

function fixtureDir() {
  const dir = mkdtempSync(join(tmpdir(), "studio-release-artifacts-"));
  writeFileSync(join(dir, "studio-desktop_0.1.0_x64-setup.exe"), Buffer.from("fake-installer-bytes"));
  writeFileSync(join(dir, "studio-desktop_0.1.0_x64-setup.exe.sig"), Buffer.from("fake-sig"));
  writeFileSync(join(dir, "notes.txt"), Buffer.from("not an artifact"));
  return dir;
}

test("hashes are deterministic and cover exe+sig only", () => {
  const dir = fixtureDir();
  try {
    const first = collectArtifacts(dir);
    assert.equal(first.length, 2);
    assert.deepEqual(
      first.map((a) => a.file),
      ["studio-desktop_0.1.0_x64-setup.exe", "studio-desktop_0.1.0_x64-setup.exe.sig"],
    );
    assert.equal(first[0].sha256, sha256Of(join(dir, first[0].file)));
    assert.equal(first[0].sha256, collectArtifacts(dir)[0].sha256);
    assert.match(first[0].sha256, /^[0-9a-f]{64}$/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("SHA256SUMS.txt is sha256sum-compatible and provenance carries source, not secrets", () => {
  const dir = fixtureDir();
  const secrets = {
    TAURI_SIGNING_PRIVATE_KEY: "SECRET-should-never-appear",
    STUDIO_UPDATER_PUBKEY: "PUBKEY-should-never-appear-in-full",
  };
  const previous = { ...process.env, ...secrets };
  Object.assign(process.env, secrets);
  try {
    const { provenance } = writeReleaseFiles(dir, "https://api.example:8443");
    const sums = readFileSync(join(dir, "SHA256SUMS.txt"), "utf8").trim().split("\n");
    assert.equal(sums.length, 2);
    for (const line of sums) assert.match(line, /^[0-9a-f]{64}  \S+$/);
    const files = JSON.parse(readFileSync(join(dir, "provenance.json"), "utf8"));
    assert.equal(files.format, "studio.release-provenance/v1");
    assert.match(files.source.commit, /^[0-9a-f]{40}$|^unknown$/);
    assert.equal(typeof files.source.dirty, "boolean");
    assert.ok("tag" in files.source);
    assert.equal(files.build.api_origin, "https://api.example:8443");
    const blob = JSON.stringify(files) + readFileSync(join(dir, "SHA256SUMS.txt"), "utf8");
    assert.doesNotMatch(blob, /SECRET-should-never-appear/);
    assert.doesNotMatch(blob, /PUBKEY-should-never-appear-in-full/);
    assert.equal(provenance.artifacts.length, 2);
  } finally {
    process.env.TAURI_SIGNING_PRIVATE_KEY = previous.TAURI_SIGNING_PRIVATE_KEY;
    process.env.STUDIO_UPDATER_PUBKEY = previous.STUDIO_UPDATER_PUBKEY;
    rmSync(dir, { recursive: true, force: true });
  }
});

test("an empty bundle directory fails closed", () => {
  const dir = mkdtempSync(join(tmpdir(), "studio-release-empty-"));
  try {
    assert.throws(() => writeReleaseFiles(dir, "https://api.example"), /no release artifact/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("provenance builder records versions without secrets", () => {
  const built = buildProvenance({ artifacts: [], apiUrl: "https://api.example" });
  assert.match(built.versions.desktop, /^\d+\.\d+\.\d+/);
  assert.match(built.versions.daemon, /^\d+\.\d+\.\d+/);
});
