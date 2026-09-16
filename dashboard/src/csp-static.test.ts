/**
 * Static prerequisites for a strict dashboard Content-Security-Policy
 * (DEC-0061): no inline scripts/styles and no inline event handlers, neither
 * in the built `dist/index.html` nor in the `src/` templates that produce it.
 *
 * Requires `npm run build` first (CI builds before testing).
 */
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = join(__dirname, "..");
const DIST_HTML = join(ROOT, "dist", "index.html");
const SRC_DIR = join(ROOT, "src");

function readDistHtml(): string {
  try {
    return readFileSync(DIST_HTML, "utf-8");
  } catch {
    throw new Error(`dist/index.html missing — run "npm run build" before "npm test"`);
  }
}

function collectTsFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      collectTsFiles(full, out);
    } else if (full.endsWith(".ts") && !full.endsWith(".test.ts")) {
      out.push(full);
    }
  }
  return out;
}

describe("CSP static prerequisites", () => {
  it("dist/index.html has no inline script", () => {
    const html = readDistHtml();
    const scripts = [...html.matchAll(/<script\b[^>]*>/gi)].map((m) => m[0]);
    expect(scripts.length).toBeGreaterThan(0);
    for (const tag of scripts) {
      expect(tag).toMatch(/\ssrc\s*=/i);
    }
  });

  it("dist/index.html has no inline style block", () => {
    expect(readDistHtml()).not.toMatch(/<style\b/i);
  });

  it("dist/index.html has no inline event handler or javascript: URL", () => {
    const html = readDistHtml();
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/javascript:/i);
  });

  it("src templates have no inline style= attributes", () => {
    const offenders: string[] = [];
    for (const file of collectTsFiles(SRC_DIR)) {
      const content = readFileSync(file, "utf-8");
      if (/<[^>]*\sstyle\s*=/i.test(content)) offenders.push(file);
    }
    expect(offenders).toEqual([]);
  });

  it("src templates have no inline on*= event handler attributes", () => {
    const offenders: string[] = [];
    for (const file of collectTsFiles(SRC_DIR)) {
      const content = readFileSync(file, "utf-8");
      if (/<[^>]*\son[a-z]+\s*=/i.test(content)) offenders.push(file);
    }
    expect(offenders).toEqual([]);
  });
});
