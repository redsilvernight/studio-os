// Channel build versions (B6): strictly increasing, semver, refused when malformed.
import assert from "node:assert/strict";
import { test } from "node:test";
import { channelBuildVersion, checkVersions } from "./version.mjs";

test("a channel build is the canonical release with a <channel>.<n> pre-release", () => {
  assert.equal(channelBuildVersion("0.1.0", "dev", 42), "0.1.0-dev.42");
  assert.equal(channelBuildVersion("0.1.0", "prod", "7"), "0.1.0-prod.7");
  // An already stamped canonical never stacks a second pre-release.
  assert.equal(channelBuildVersion("0.1.0-dev.3", "dev", 4), "0.1.0-dev.4");
});

test("malformed channel or build number is refused", () => {
  assert.throws(() => channelBuildVersion("0.1.0", "beta", 1), /unknown build channel/);
  for (const n of [undefined, "", "0", "-1", "1.5", "01", "x"]) {
    assert.throws(() => channelBuildVersion("0.1.0", "dev", n), /positive integer/, String(n));
  }
  assert.throws(() => channelBuildVersion("latest", "dev", 1), /not semver/);
});

test("the Cargo.lock entry is a synced carrier", () => {
  const lock = checkVersions().find((row) => row.name.includes("Cargo.lock"));
  assert.ok(lock, "Cargo.lock carrier declared");
  assert.equal(lock.actual, lock.expected);
});
