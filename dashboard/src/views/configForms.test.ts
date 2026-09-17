import { describe, expect, it } from "vitest";
import {
  buildBindingCreate,
  buildBindingCreateTarget,
  buildRuntimeCreate,
  buildRuntimeUpdate,
  parseMetadataLines,
  readCapabilities,
} from "./configForms";
import type { FormReader } from "./libraryForms";

function reader(values: Record<string, string>, checks: Record<string, boolean> = {}): FormReader {
  return {
    text: (name: string) => values[name] ?? "",
    checked: (name: string) => checks[name] ?? false,
  };
}

describe("parseMetadataLines", () => {
  it("parses key=value lines and ignores blanks/malformed", () => {
    expect(parseMetadataLines("region=eu\n\nmalformed\n note = hello ")).toEqual({ region: "eu", note: "hello" });
  });
});

describe("readCapabilities", () => {
  it("keeps open strings and structured booleans", () => {
    const capabilities = readCapabilities(reader({ cap_reasoning: "high", cap_tools: "shell, git", cap_context_window: "128000" }, { cap_coding: true }));
    expect(capabilities).toEqual({
      coding: true,
      tools: ["shell", "git"],
      local: false,
      reasoning: "high",
      context_window: 128000,
    });
  });
});

describe("buildRuntimeCreate", () => {
  it("requires at least one anchor", () => {
    expect(buildRuntimeCreate(reader({}))).toEqual({
      ok: false,
      error: "at least one of machine, harness, provider or model is required",
    });
  });

  it("declares capabilities and accepts open refs", () => {
    const result = buildRuntimeCreate(reader({ harness_ref: "any-harness", provider_ref: "any-provider", model_ref: "any-model", metadata: "region=eu" }));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.capability_source).toBe("declared");
    expect(result.value.harness_ref).toBe("any-harness");
    expect(result.value.runtime_metadata).toEqual({ region: "eu" });
  });
});

describe("buildRuntimeUpdate", () => {
  it("omits untouched refs and requires a valid expected_version", () => {
    const result = buildRuntimeUpdate(reader({ expected_version: "3" }, { detach_machine: true }));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.expected_version).toBe(3);
    expect(result.value.update.detach_machine).toBe(true);
    expect(result.value.update.harness_ref).toBeUndefined();
    expect(result.value.update.capabilities).toBeUndefined();
  });

  it("includes capabilities only when explicitly replacing them", () => {
    const result = buildRuntimeUpdate(reader({ expected_version: "1", cap_tools: "shell" }, { update_capabilities: true }));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.update.capabilities?.tools).toEqual(["shell"]);
  });

  it("rejects a missing expected_version", () => {
    expect(buildRuntimeUpdate(reader({}))).toEqual({ ok: false, error: "expected_version must be ≥ 1" });
  });
});

describe("buildBindingCreateTarget", () => {
  it("makes runtime_id exclusive", () => {
    const target = buildBindingCreateTarget({ runtimeId: "rt1", machineId: "m1", harnessRef: "h", providerRef: "", modelRef: "" });
    expect(target?.runtime_id).toBe("rt1");
    expect(target?.harness_ref).toBeUndefined();
  });

  it("falls back to inline anchors and returns null when empty", () => {
    expect(buildBindingCreateTarget({ runtimeId: "", machineId: "", harnessRef: "h", providerRef: "", modelRef: "" })?.harness_ref).toBe("h");
    expect(buildBindingCreateTarget({ runtimeId: "", machineId: "", harnessRef: "", providerRef: "", modelRef: "" })).toBeNull();
  });
});

describe("buildBindingCreate", () => {
  const base = {
    level: "user",
    project_id: "",
    target_kind: "agent_definition",
    target_stable_key: "review-helper",
    runtime_id: "rt1",
  };

  it("builds a user-level binding toward a registry runtime", () => {
    const result = buildBindingCreate(reader(base));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.level).toBe("user");
    expect(result.value.project_id).toBeNull();
    expect(result.value.target.runtime_id).toBe("rt1");
  });

  it("refuses the ephemeral session level", () => {
    expect(buildBindingCreate(reader({ ...base, level: "session" }))).toEqual({
      ok: false,
      error: "level must be one of user, project_override, project_default, studio_default",
    });
  });

  it("requires a project for project levels", () => {
    expect(buildBindingCreate(reader({ ...base, level: "project_override", project_id: "" }))).toEqual({
      ok: false,
      error: "project_override requires a project ID",
    });
  });

  it("requires an anchor when no registry id is given", () => {
    expect(buildBindingCreate(reader({ ...base, runtime_id: "" }))).toEqual({
      ok: false,
      error: "provide a runtime registry id, or at least one inline anchor (machine/harness/provider/model)",
    });
  });
});
