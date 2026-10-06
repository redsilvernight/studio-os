#!/usr/bin/env node
/**
 * Reproducible bundle analysis (task d5c1183f).
 *
 *   npm run analyze:bundle            # table: chunks + top modules per chunk
 *   npm run check:bundle              # same + fails if the initial-load budget is exceeded
 *
 * Builds in memory (`write: false`, nothing touches dist/), then reports every
 * chunk (minified bytes, gzip bytes) and the largest source modules inside it
 * (rendered size BEFORE minification — a ranking, not an exact byte count).
 * "Initial load" = the entry chunk + every chunk reachable through STATIC
 * imports from it (what index.html makes the browser fetch before first paint),
 * plus the CSS the entry emits. Dynamic imports are excluded by definition.
 */
import { gzipSync } from "node:zlib";
import { build } from "vite";

// Budget for the initial load (JS + CSS, gzip). Justification: see README.md
// « Bundle budget ». Raise it only with a measured reason.
export const INITIAL_JS_GZIP_BUDGET = 60 * 1024;
export const INITIAL_CSS_GZIP_BUDGET = 20 * 1024;

const kb = (n) => `${(n / 1024).toFixed(2)} kB`;
const gz = (code) => gzipSync(typeof code === "string" ? Buffer.from(code) : code).length;

const result = await build({ logLevel: "silent", build: { write: false } });
const outputs = (Array.isArray(result) ? result : [result]).flatMap((r) => r.output);
const chunks = outputs.filter((o) => o.type === "chunk");
const assets = outputs.filter((o) => o.type === "asset");
const byName = new Map(chunks.map((c) => [c.fileName, c]));

// Initial closure: entry + static imports (transitively).
const entry = chunks.find((c) => c.isEntry);
const initial = new Set();
const visit = (file) => {
  if (initial.has(file)) return;
  initial.add(file);
  for (const dep of byName.get(file)?.imports ?? []) visit(dep);
};
visit(entry.fileName);
const initialCss = new Set(
  [...initial].flatMap((f) => [...(byName.get(f)?.viteMetadata?.importedCss ?? [])]),
);

console.log("Chunks (minified / gzip)");
for (const c of [...chunks].sort((a, b) => b.code.length - a.code.length)) {
  const tag = initial.has(c.fileName) ? "initial" : "lazy   ";
  console.log(`  ${tag}  ${c.fileName.padEnd(44)} ${kb(c.code.length).padStart(10)}  ${kb(gz(c.code)).padStart(10)}`);
}
console.log("\nCSS assets (initial = referenced by an initial chunk)");
for (const a of assets.filter((x) => x.fileName.endsWith(".css"))) {
  const tag = initialCss.has(a.fileName) ? "initial" : "lazy   ";
  console.log(`  ${tag}  ${a.fileName.padEnd(44)} ${kb(a.source.length).padStart(10)}  ${kb(gz(a.source)).padStart(10)}`);
}

const top = Number(process.env.ANALYZE_TOP ?? 12);
for (const c of chunks.filter((x) => initial.has(x.fileName))) {
  console.log(`\nTop modules in initial chunk ${c.fileName}`);
  const mods = Object.entries(c.modules).sort((a, b) => b[1].renderedLength - a[1].renderedLength).slice(0, top);
  for (const [id, m] of mods) {
    console.log(`  ${kb(m.renderedLength).padStart(10)}  ${id.replace(/^.*\/dashboard\//, "")}`);
  }
}

const jsGz = [...initial].reduce((s, f) => s + gz(byName.get(f).code), 0);
const cssGz = [...initialCss].reduce((s, f) => s + gz(assets.find((a) => a.fileName === f).source), 0);
const jsRaw = [...initial].reduce((s, f) => s + byName.get(f).code.length, 0);
console.log(`\nInitial load: JS ${kb(jsRaw)} (gzip ${kb(jsGz)}, budget ${kb(INITIAL_JS_GZIP_BUDGET)}), CSS gzip ${kb(cssGz)} (budget ${kb(INITIAL_CSS_GZIP_BUDGET)})`);

if (process.argv.includes("--check")) {
  const failures = [];
  if (jsGz > INITIAL_JS_GZIP_BUDGET) failures.push(`initial JS gzip ${kb(jsGz)} > ${kb(INITIAL_JS_GZIP_BUDGET)}`);
  if (cssGz > INITIAL_CSS_GZIP_BUDGET) failures.push(`initial CSS gzip ${kb(cssGz)} > ${kb(INITIAL_CSS_GZIP_BUDGET)}`);
  if (failures.length > 0) {
    console.error(`\nBudget exceeded:\n  - ${failures.join("\n  - ")}`);
    process.exit(1);
  }
  console.log("Budget OK.");
}
