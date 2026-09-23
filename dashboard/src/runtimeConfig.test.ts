import { afterEach, describe, expect, it } from "vitest";
import { apiBaseUrl } from "./api";
import { getServerOriginOverride, setServerOriginOverride } from "./runtimeConfig";

afterEach(() => setServerOriginOverride(null));

describe("runtime server origin", () => {
  it("has no override by default, so the build value (web) is untouched", () => {
    expect(getServerOriginOverride()).toBeNull();
  });

  it("wins over the build value and drops a trailing slash", () => {
    setServerOriginOverride("https://studio.example.com/");
    expect(getServerOriginOverride()).toBe("https://studio.example.com");
    expect(apiBaseUrl()).toBe("https://studio.example.com");
  });

  it("clearing (null or blank) restores the build value", () => {
    const build = apiBaseUrl();
    setServerOriginOverride("https://studio.example.com");
    setServerOriginOverride("  ");
    expect(getServerOriginOverride()).toBeNull();
    expect(apiBaseUrl()).toBe(build);
    setServerOriginOverride("https://studio.example.com");
    setServerOriginOverride(null);
    expect(getServerOriginOverride()).toBeNull();
  });
});
