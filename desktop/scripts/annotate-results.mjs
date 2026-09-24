// Turns the FAIL entries of desktop/.build/*-results.json into GitHub Actions
// error annotations, so a failed desktop gate can be read from the public
// check-run annotations without downloading the (authenticated) job log.
//
//   node scripts/annotate-results.mjs [install-test-results.json ...]

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { buildDir } from "./lib.mjs";

const escape = (text) => String(text).replaceAll("%", "%25").replaceAll("\r", "%0D").replaceAll("\n", "%0A");

const names = process.argv.slice(2).length ? process.argv.slice(2) : ["install-test-results.json"];
let failures = 0;
for (const name of names) {
  const file = join(buildDir, name);
  if (!existsSync(file)) {
    console.log(`::warning title=${escape(name)}::no results file (the step stopped before writing it)`);
    continue;
  }
  let results = [];
  try {
    results = JSON.parse(readFileSync(file, "utf8"));
  } catch (error) {
    console.log(`::warning title=${escape(name)}::unreadable results file: ${escape(error)}`);
    continue;
  }
  for (const result of results.filter((r) => r.status === "FAIL")) {
    failures += 1;
    console.log(`::error title=${escape(`${name}: ${result.id}`)}::${escape(String(result.evidence).slice(0, 2000))}`);
  }
}
console.log(`${failures} failing check(s) annotated`);
