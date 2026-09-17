import { describe, expect, it } from "vitest";
import { capabilitySummary, configTabsHtml, runtimeTargetSummary } from "./configuration";
import type { RuntimeCapabilities, RuntimeTarget } from "../libraryFormat";

const target = (overrides: Partial<RuntimeTarget>): RuntimeTarget =>
  ({ capabilities: { coding: false, tools: [], local: false }, ...overrides }) as RuntimeTarget;

describe("configTabsHtml", () => {
  it("lists Runtimes / Bindings / Project and marks the active tab", () => {
    const html = configTabsHtml("bindings");
    expect(html).toContain("#/configuration/runtimes");
    expect(html).toContain("#/configuration/bindings");
    expect(html).toContain("#/configuration/project");
    expect(html).toMatch(/class="tab active" href="#\/configuration\/bindings"/);
  });
});

describe("runtimeTargetSummary", () => {
  it("shows registry id and open refs", () => {
    const html = runtimeTargetSummary(target({ runtime_id: "rt1", harness_ref: "any-harness", provider_ref: "any-provider", model_ref: "any-model" }));
    expect(html).toContain("rt1");
    expect(html).toContain("any-harness");
    expect(html).toContain("any-provider");
    expect(html).toContain("any-model");
  });

  it("shows a dash when no anchor is present", () => {
    expect(runtimeTargetSummary(target({}))).toContain("—");
  });
});

describe("capabilitySummary", () => {
  it("summarises declared capabilities and says when none are declared", () => {
    const capabilities: RuntimeCapabilities = { coding: true, context_window: 128000, tools: ["shell"], local: false };
    const html = capabilitySummary(capabilities);
    expect(html).toContain("Coding=yes");
    expect(html).toContain("Context window=128000");
    expect(capabilitySummary({ coding: false, tools: [], local: false })).toContain("none declared");
  });
});
