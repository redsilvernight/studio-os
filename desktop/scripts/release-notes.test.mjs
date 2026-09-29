// Release notes (patch notes): one file per release, a committed embedded
// module, and a gate that refuses a release without its note.
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { canonicalVersion } from "./version.mjs";
import {
  baseVersion,
  buildNotesModule,
  checkNotesModule,
  generatedModulePath,
  noteVersions,
  readReleaseNote,
  releaseNotesDir,
  requireReleaseNote,
} from "./release-notes.mjs";

function scratchNotes(files) {
  const dir = mkdtempSync(join(tmpdir(), "release-notes-"));
  for (const [version, text] of Object.entries(files)) writeFileSync(join(dir, `${version}.md`), text, "utf8");
  return dir;
}

test("a pre-release resolves to its base version", () => {
  assert.equal(baseVersion("0.1.0"), "0.1.0");
  assert.equal(baseVersion("0.1.0-dev.42"), "0.1.0");
  assert.equal(baseVersion("1.2.3-prod.7"), "1.2.3");
  assert.throws(() => baseVersion("latest"), /not a semver version/);
});

test("note versions are ascending base versions, other files ignored", () => {
  const dir = scratchNotes({ "0.2.0": "# Version 0.2.0\n", "0.1.0": "# Version 0.1.0\n", README: "x" });
  writeFileSync(join(dir, "notes.txt"), "ignored", "utf8");
  assert.deepEqual(noteVersions(dir), ["0.1.0", "0.2.0"]);
  rmSync(dir, { recursive: true, force: true });
});

test("a missing or empty note is refused", () => {
  const dir = scratchNotes({ "0.1.0": "   \n" });
  assert.equal(readReleaseNote("0.1.0", dir), null);
  assert.throws(() => requireReleaseNote("0.1.0", dir), /missing release note for 0\.1\.0/);
  assert.throws(() => requireReleaseNote("0.9.9", dir), /missing release note for 0\.9\.9/);
  rmSync(dir, { recursive: true, force: true });
});

test("a pre-release build reads the note of its base version", () => {
  const dir = scratchNotes({ "0.1.0": "# Version 0.1.0\n" });
  assert.equal(requireReleaseNote("0.1.0-dev.42", dir), "# Version 0.1.0");
  rmSync(dir, { recursive: true, force: true });
});

test("the embedded module lists every note and detects drift", () => {
  const dir = scratchNotes({ "0.1.0": "# Version 0.1.0\n", "0.2.0": "# Version 0.2.0\n" });
  const out = join(dir, "releaseNotes.generated.ts");
  const module = buildNotesModule(dir);
  assert.match(module, /"0\.1\.0": "# Version 0\.1\.0"/);
  assert.match(module, /RELEASE_NOTES_VERSIONS: readonly string\[\] = \["0\.1\.0", "0\.2\.0"\]/);
  writeFileSync(out, module, "utf8");
  checkNotesModule(dir, out);
  writeFileSync(out, `${module}\n// drifted`, "utf8");
  assert.throws(() => checkNotesModule(dir, out), /out of date/);
  rmSync(dir, { recursive: true, force: true });
});

test("the committed notes answer the canonical release and the module is fresh", () => {
  const version = canonicalVersion();
  assert.ok(requireReleaseNote(version, releaseNotesDir));
  checkNotesModule(releaseNotesDir, generatedModulePath);
});
