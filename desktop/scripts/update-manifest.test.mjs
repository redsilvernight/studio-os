import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  assetUrl,
  buildManifest,
  installerIn,
  publicChannel,
  updaterTarget,
  writeManifest,
} from "./update-manifest.mjs";

const INSTALLER = "Studio OS Desktop_0.1.0_x64-setup.exe";

function fixtureDir({ withSig = true } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "studio-update-manifest-"));
  writeFileSync(join(dir, INSTALLER), Buffer.from("fake-installer-bytes"));
  if (withSig) writeFileSync(join(dir, `${INSTALLER}.sig`), "dW50cnVzdGVkIHNpZwo=\n");
  return dir;
}

test("updater platform key is the one tauri-plugin-updater 2.12 looks up", () => {
  assert.equal(updaterTarget("win32", "x64"), "windows-x86_64");
  assert.equal(updaterTarget("darwin", "arm64"), "darwin-aarch64");
  assert.equal(updaterTarget("linux", "x64"), "linux-x86_64");
  assert.throws(() => updaterTarget("sunos", "x64"), /unsupported updater target/);
});

test("build channels map to the public release lanes (DEC-0108)", () => {
  assert.equal(publicChannel("dev"), "beta");
  assert.equal(publicChannel("prod"), "stable");
  assert.throws(() => publicChannel("canary"), /unknown build channel/);
});

test("asset URLs are https and percent-encode the installer name", () => {
  assert.equal(
    assetUrl("https://github.com/o/r/releases/download/desktop-prod", INSTALLER),
    `https://github.com/o/r/releases/download/desktop-prod/${encodeURIComponent(INSTALLER)}`,
  );
  assert.throws(() => assetUrl("http://example.test", INSTALLER), /must be https/);
});

test("the manifest carries the plugin fields plus additive, versioned data", () => {
  const dir = fixtureDir();
  try {
    const manifest = buildManifest({
      bundleDir: dir,
      urlBase: "https://github.com/o/r/releases/download/desktop-prod",
      channel: "prod",
      version: "0.1.0",
      pubDate: "2026-09-26T00:00:00.000Z",
    });
    // Required by the updater plugin.
    assert.equal(manifest.version, "0.1.0");
    assert.equal(typeof manifest.notes, "string");
    assert.equal(manifest.pub_date, "2026-09-26T00:00:00.000Z");
    const platform = manifest.platforms["windows-x86_64"];
    assert.equal(
      platform.url,
      `https://github.com/o/r/releases/download/desktop-prod/${encodeURIComponent(INSTALLER)}`,
    );
    assert.equal(platform.signature, "dW50cnVzdGVkIHNpZwo=");
    // Additive, ignored by older readers.
    assert.equal(manifest.schema_version, 1);
    assert.equal(manifest.channel, "stable");
    assert.deepEqual(Object.keys(manifest.artifacts), ["windows-x86_64"]);
    assert.equal(manifest.artifacts["windows-x86_64"].file, INSTALLER);
    assert.equal(manifest.artifacts["windows-x86_64"].size_bytes, Buffer.byteLength("fake-installer-bytes"));
    assert.match(manifest.artifacts["windows-x86_64"].sha256, /^[0-9a-f]{64}$/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("dev builds announce the beta lane and write a parseable file", () => {
  const dir = fixtureDir();
  try {
    const path = join(dir, "latest.json");
    writeManifest(
      path,
      buildManifest({ bundleDir: dir, urlBase: "https://example.test/rel", channel: "dev" }),
    );
    const written = JSON.parse(readFileSync(path, "utf8"));
    assert.equal(written.channel, "beta");
    assert.ok(written.platforms["windows-x86_64"].url.startsWith("https://example.test/rel/"));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a renamed download asset keeps the signature but changes the URL", () => {
  const dir = fixtureDir();
  try {
    const manifest = buildManifest({
      bundleDir: dir,
      urlBase: "https://github.com/o/r/releases/download/desktop-dev",
      channel: "dev",
      assetName: "StudiOS-Setup-dev.exe",
    });
    assert.equal(
      manifest.platforms["windows-x86_64"].url,
      "https://github.com/o/r/releases/download/desktop-dev/StudiOS-Setup-dev.exe",
    );
    assert.equal(manifest.platforms["windows-x86_64"].signature, "dW50cnVzdGVkIHNpZwo=");
    assert.equal(manifest.artifacts["windows-x86_64"].file, "StudiOS-Setup-dev.exe");
    assert.equal(
      manifest.artifacts["windows-x86_64"].sha256,
      buildManifest({ bundleDir: dir, urlBase: "https://example.test" }).artifacts["windows-x86_64"].sha256,
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a missing signature fails closed (updater not compiled in)", () => {
  const dir = fixtureDir({ withSig: false });
  try {
    assert.throws(
      () => buildManifest({ bundleDir: dir, urlBase: "https://example.test/rel" }),
      /updater signature/,
    );
    assert.equal(installerIn(dir), INSTALLER);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
