import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { sha256Of } from "./release-artifacts.mjs";
import { buildManifest, updaterTarget } from "./update-manifest.mjs";
import {
  artifactOf,
  laneRelease,
  promote,
  promoteManifest,
  readManifest,
  verifyArtifact,
} from "./promote-channel.mjs";

const INSTALLER = "StudiOS-Setup-dev.exe";
const URL_BASE = "https://github.com/o/r/releases/download/desktop-prod";
const TARGET = updaterTarget();

function fixture({ channel = "dev", apiUrl = "https://api.example.test" } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "studio-promote-"));
  writeFileSync(join(dir, INSTALLER), Buffer.from("promotable-installer-bytes"));
  writeFileSync(join(dir, `${INSTALLER}.sig`), "dW50cnVzdGVkIHNpZwo=\n");
  const manifest = buildManifest({
    bundleDir: dir,
    urlBase: "https://github.com/o/r/releases/download/desktop-dev",
    channel,
    version: "0.1.0",
    assetName: INSTALLER,
    pubDate: "2026-09-27T00:00:00.000Z",
    apiUrl,
  });
  writeFileSync(join(dir, "latest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
  return { dir, manifest };
}

function withFixture(options, run) {
  const { dir, manifest } = fixture(options);
  try {
    return run({ dir, manifest });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("lanes publish to the release tags DEC-0133 fixes", () => {
  assert.equal(laneRelease("beta"), "desktop-dev");
  assert.equal(laneRelease("stable"), "desktop-prod");
  assert.throws(() => laneRelease("canary"), /unknown lane/);
});

test("promotion rewrites the manifest and keeps version, signature and hash", () => {
  withFixture({}, ({ manifest }) => {
    const promoted = promoteManifest(manifest, { to: "stable", urlBase: URL_BASE });
    assert.equal(promoted.version, manifest.version);
    assert.equal(promoted.pub_date, manifest.pub_date);
    assert.equal(promoted.channel, "stable");
    assert.equal(promoted.promoted_from, "beta");
    assert.equal(promoted.schema_version, 1);
    assert.equal(promoted.platforms[TARGET].signature, manifest.platforms[TARGET].signature);
    assert.equal(promoted.artifacts[TARGET].sha256, manifest.artifacts[TARGET].sha256);
    assert.equal(promoted.artifacts[TARGET].file, INSTALLER);
    assert.equal(promoted.platforms[TARGET].url, `${URL_BASE}/${INSTALLER}`);
    assert.equal(promoted.api_origin, "https://api.example.test");
  });
});

test("a renamed target asset changes the URL but never the bytes", () => {
  withFixture({}, ({ manifest }) => {
    const promoted = promoteManifest(manifest, {
      to: "stable",
      urlBase: URL_BASE,
      assetName: "StudiOS-Setup-prod.exe",
    });
    assert.equal(promoted.platforms[TARGET].url, `${URL_BASE}/StudiOS-Setup-prod.exe`);
    assert.equal(promoted.artifacts[TARGET].file, "StudiOS-Setup-prod.exe");
    assert.equal(promoted.artifacts[TARGET].sha256, manifest.artifacts[TARGET].sha256);
  });
});

test("an unknown target lane or an unsigned source is refused", () => {
  withFixture({}, ({ manifest }) => {
    assert.throws(() => promoteManifest(manifest, { to: "canary", urlBase: URL_BASE }), /unknown target lane/);
    assert.throws(
      () => promoteManifest({ ...manifest, platforms: {} }, { to: "stable", urlBase: URL_BASE }),
      /signed .* platform/,
    );
    assert.throws(
      () => artifactOf({ ...manifest, artifacts: {} }),
      /carries no .* artifact/,
    );
  });
});

test("a source and target on different API origins are refused (fail closed)", () => {
  withFixture({}, ({ manifest }) => {
    assert.throws(
      () => promoteManifest(manifest, { to: "stable", urlBase: URL_BASE, apiUrl: "https://other.example.test" }),
      /api_origin_mismatch/,
    );
    const same = promoteManifest(manifest, {
      to: "stable",
      urlBase: URL_BASE,
      apiUrl: "https://api.example.test",
    });
    assert.equal(same.channel, "stable");
  });
});

test("a manifest without api_origin is still promotable (older build)", () => {
  withFixture({ apiUrl: null }, ({ manifest }) => {
    assert.equal(manifest.api_origin, undefined);
    const promoted = promoteManifest(manifest, {
      to: "stable",
      urlBase: URL_BASE,
      apiUrl: "https://api.example.test",
    });
    assert.equal(promoted.channel, "stable");
    assert.equal(promoted.api_origin, undefined);
  });
});

test("verifyArtifact refuses a rebuilt or truncated file", () => {
  withFixture({}, ({ dir, manifest }) => {
    const artifact = manifest.artifacts[TARGET];
    assert.equal(verifyArtifact(dir, artifact), join(dir, INSTALLER));
    writeFileSync(join(dir, INSTALLER), Buffer.from("REBUILT-installer-bytes"));
    assert.throws(() => verifyArtifact(dir, artifact), /size_mismatch/);
    writeFileSync(join(dir, INSTALLER), Buffer.from("Promotable-installer-bytes"));
    assert.throws(() => verifyArtifact(dir, artifact), /hash_mismatch/);
  });
});

test("promote copies the exact bytes and writes the target manifest", () => {
  withFixture({}, ({ dir, manifest }) => {
    const out = join(dir, "out");
    const promoted = promote({ dir, out, to: "stable", urlBase: URL_BASE });
    assert.equal(promoted.channel, "stable");
    const target = join(out, INSTALLER);
    assert.equal(sha256Of(target), manifest.artifacts[TARGET].sha256);
    assert.equal(sha256Of(target), sha256Of(join(dir, INSTALLER)));
    assert.deepEqual(readManifest(out), JSON.parse(readFileSync(join(out, "latest.json"), "utf8")));
    assert.equal(readManifest(out).channel, "stable");
  });
});

test("a rollback re-points stable to an earlier artefact (retour vers stable)", () => {
  withFixture({ channel: "prod" }, ({ manifest }) => {
    const back = promoteManifest(manifest, { to: "stable", urlBase: URL_BASE });
    assert.equal(back.channel, "stable");
    assert.equal(back.promoted_from, "stable");
    assert.equal(back.artifacts[TARGET].sha256, manifest.artifacts[TARGET].sha256);
  });
});

test("the CLI promotes a downloaded release without rebuilding", () => {
  withFixture({}, ({ dir, manifest }) => {
    const script = fileURLToPath(new URL("./promote-channel.mjs", import.meta.url));
    const out = join(dir, "out");
    const result = spawnSync(
      process.execPath,
      [script, "--dir", dir, "--out", out, "--to", "stable", "--url-base", URL_BASE],
      { encoding: "utf8" },
    );
    assert.equal(result.status, 0, result.stderr);
    assert.equal(sha256Of(join(out, INSTALLER)), manifest.artifacts[TARGET].sha256);
    assert.equal(readManifest(out).channel, "stable");
  });
});

test("the CLI fails closed on a rebuilt artefact", () => {
  withFixture({}, ({ dir }) => {
    writeFileSync(join(dir, INSTALLER), Buffer.from("REBUILT"));
    const script = fileURLToPath(new URL("./promote-channel.mjs", import.meta.url));
    const result = spawnSync(
      process.execPath,
      [script, "--dir", dir, "--to", "stable", "--url-base", URL_BASE],
      { encoding: "utf8" },
    );
    assert.equal(result.status, 1);
    assert.match(result.stderr, /size_mismatch|hash_mismatch/);
  });
});
