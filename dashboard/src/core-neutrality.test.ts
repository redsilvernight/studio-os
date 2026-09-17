/**
 * P12 structural guard — the dashboard is not a resolver.
 *
 * The single source of truth for shadowing, effective version, runtime
 * precedence and compatibility is the server (P2/P5). This test fails if a
 * hand-written dashboard source file starts encoding that logic, or proposes a
 * closed vendor catalog for runtime references (DEC-0069/0070/0071).
 */
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC_DIR = join(__dirname);

/** Generated from the backend OpenAPI document — never hand-written. */
const GENERATED = new Set(["openapi-schema.ts"]);

function collectSourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      collectSourceFiles(full, out);
    } else if (full.endsWith(".ts") && !full.endsWith(".test.ts") && !GENERATED.has(entry)) {
      out.push(full.replace(/\\/g, "/"));
    }
  }
  return out;
}

const SOURCES = collectSourceFiles(SRC_DIR).map((file) => ({ file, content: readFileSync(file, "utf-8") }));

const RESOLVER_IDENTIFIERS = [
  "select_runtime",
  "selectRuntime",
  "check_compatibility",
  "checkCompatibility",
  "resolve_agent",
  "resolveAgent",
  "resolve_definition",
  "resolveDefinition",
];

const VENDOR_NAMES = /anthropic|openai|ollama|gemini|mistral|\bkimi\b|gpt-4/i;

/** The full P4 precedence chain in order — encoding it locally would be a
 *  resolver. A subset (e.g. the storable levels, which exclude `session`) is
 *  not an ordering and stays allowed. */
const PRECEDENCE_CHAIN =
  /["']session["']\s*,\s*["']project_override["']\s*,\s*["']user["']\s*,\s*["']project_default["']\s*,\s*["']studio_default["']/;

describe("core neutrality", () => {
  it("collects the hand-written sources", () => {
    expect(SOURCES.some((source) => source.file.endsWith("views/inspector.ts"))).toBe(true);
  });

  it("never renames or reimplements a server resolver", () => {
    const offenders = SOURCES.filter((source) => RESOLVER_IDENTIFIERS.some((name) => source.content.includes(name))).map(
      (source) => source.file,
    );
    expect(offenders).toEqual([]);
  });

  it("never encodes the P4 precedence order locally", () => {
    const offenders = SOURCES.filter((source) => PRECEDENCE_CHAIN.test(source.content)).map((source) => source.file);
    expect(offenders).toEqual([]);
  });

  it("never proposes a closed vendor catalog", () => {
    const offenders = SOURCES.filter((source) => VENDOR_NAMES.test(source.content)).map((source) => source.file);
    expect(offenders).toEqual([]);
  });

  it("resolves only through the canonical POST /resolutions route", () => {
    const api = SOURCES.find((source) => source.file.endsWith("resolutionApi.ts"));
    const inspector = SOURCES.find((source) => source.file.endsWith("views/inspector.ts"));
    expect(api?.content).toContain('"/api/v1/resolutions"');
    expect(inspector?.content).toContain("postResolution(");
  });
});
