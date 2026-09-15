import { describe, expect, it } from "vitest";
import { joinUrl, resolveApiUrl } from "./config";

describe("resolveApiUrl", () => {
  it("defaults to empty (same-origin) when unset", () => {
    expect(resolveApiUrl(undefined)).toBe("");
  });

  it("treats blank as same-origin", () => {
    expect(resolveApiUrl("   ")).toBe("");
  });

  it("keeps a configured remote URL and strips trailing slashes", () => {
    expect(resolveApiUrl("http://localhost:8000///")).toBe("http://localhost:8000");
    expect(resolveApiUrl("https://api.example.com")).toBe("https://api.example.com");
  });
});

describe("joinUrl", () => {
  it("returns relative paths when base is empty (same-origin)", () => {
    expect(joinUrl("", "/api/v1/projects")).toBe("/api/v1/projects");
  });

  it("prefixes a configured base", () => {
    expect(joinUrl("http://localhost:8000", "/healthz")).toBe("http://localhost:8000/healthz");
  });
});
