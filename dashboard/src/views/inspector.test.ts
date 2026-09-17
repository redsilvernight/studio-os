import { describe, expect, it } from "vitest";
import { ApiError, parseErrorBody } from "../api";
import { resolutionErrorView, type ResolvedAgentDefinition } from "../resolutionApi";
import {
  buildResolutionRequest,
  compatibilityComparisonHtml,
  modelProfileHtml,
  provenanceReasonsHtml,
  resolutionFailureHtml,
  resolutionResultHtml,
  rulesTableHtml,
  runtimeHtml,
} from "./inspector";

/** Canonical fixture from the roadmap gate (P12 spec §69). */
const resolved = (): ResolvedAgentDefinition =>
  ({
    agent: {
      resource_id: "a1",
      kind: "agent_definition",
      stable_key: "review-helper",
      scope: "studio",
      version: 4,
      version_origin: "lock",
      deprecated: false,
      title: "Review helper",
      content: {},
      provenance: { source: "project_lock", version: 4, scope: "studio", version_origin: "lock", locked: true },
    },
    rules: [
      {
        resource_id: "r1",
        stable_key: "coding-standard",
        scope: "studio",
        version: 3,
        version_origin: "pin",
        deprecated: false,
        title: "",
        content: {},
        paths: [{ relation: "applies_rule", via_kind: "agent_definition", via_resource_id: "a1", via_stable_key: "review-helper", via_version: 4 }],
      },
    ],
    skills: [
      {
        resource_id: "s1",
        stable_key: "code-review",
        scope: "studio",
        version: 5,
        version_origin: "pin",
        deprecated: false,
        title: "",
        content: {},
        provenance: { source: "version_pin", version: 5, relation: "uses_skill", via: "agent_definition:review-helper" },
      },
    ],
    model_profile: {
      resource_id: "m1",
      stable_key: "review-profile",
      scope: "studio",
      version: 2,
      version_origin: "pin",
      deprecated: false,
      title: "",
      requirements: { coding: true },
      provenance: { source: "version_pin", version: 2, relation: "requires_model_profile", via: "agent_definition:review-helper" },
    },
    requirements: { coding: true },
    composed_agents: [],
    workflows: [],
    runtime: {
      target: { runtime_id: "rt1", harness_ref: "opencode", provider_ref: "provider_a", model_ref: "model_a", capabilities: { coding: true, tools: [], local: false } },
      level: "project_override",
      matched_kind: "agent_definition",
      matched_stable_key: "review-helper",
      compatible: true,
      unsatisfied: [],
      provenance: { source: "runtime_binding", binding_level: "project_override", via: "agent_definition:review-helper" },
    },
  }) as unknown as ResolvedAgentDefinition;

describe("buildResolutionRequest", () => {
  it("requires an AgentDefinition stable key", () => {
    expect(buildResolutionRequest({ stableKey: "  ", projectId: "", enableOverride: false, override: { targetKind: "agent_definition", stableKey: "", runtimeId: "", machineId: "", harnessRef: "", providerRef: "", modelRef: "" } })).toEqual({
      ok: false,
      error: "an AgentDefinition stable key is required",
    });
  });

  it("builds a plain request with no ephemeral override", () => {
    const built = buildResolutionRequest({ stableKey: "review-helper", projectId: "", enableOverride: false, override: { targetKind: "agent_definition", stableKey: "", runtimeId: "", machineId: "", harnessRef: "", providerRef: "", modelRef: "" } });
    expect(built).toEqual({ ok: true, value: { stable_key: "review-helper", session_overrides: [] } });
  });

  it("adds a temporary session override without any persistence field", () => {
    const built = buildResolutionRequest({
      stableKey: "review-helper",
      projectId: "p1",
      enableOverride: true,
      override: { targetKind: "model_profile", stableKey: "review-profile", runtimeId: "rt1", machineId: "", harnessRef: "", providerRef: "", modelRef: "" },
    });
    expect(built.ok).toBe(true);
    if (!built.ok) return;
    expect(built.value.project_id).toBe("p1");
    expect(built.value.session_overrides).toHaveLength(1);
    expect(built.value.session_overrides[0]).toMatchObject({ target_kind: "model_profile", target_stable_key: "review-profile" });
    expect(built.value.session_overrides[0]?.target.runtime_id).toBe("rt1");
  });

  it("rejects an override with no anchor", () => {
    const built = buildResolutionRequest({
      stableKey: "review-helper",
      projectId: "",
      enableOverride: true,
      override: { targetKind: "agent_definition", stableKey: "review-helper", runtimeId: "", machineId: "", harnessRef: "", providerRef: "", modelRef: "" },
    });
    expect(built).toEqual({ ok: false, error: "session override needs a runtime id or at least one inline anchor" });
  });
});

describe("resolutionResultHtml", () => {
  it("renders identity, rules, skills, profile, runtime and reasons from the server response", () => {
    const html = resolutionResultHtml(resolved());
    expect(html).toContain("review-helper");
    expect(html).toContain("v4");
    expect(html).toContain("coding-standard");
    expect(html).toContain("code-review");
    expect(html).toContain("review-profile");
    expect(html).toContain("rt1");
    expect(html).toContain("opencode");
    expect(html).toContain("provider_a");
    expect(html).toContain("model_a");
    expect(html).toContain("Compatible");
    expect(html).toContain("Why this version?");
    expect(html).toContain("Which binding won?");
  });

  it("cross-links a rule to the Library and the runtime to Configuration", () => {
    const html = resolutionResultHtml(resolved());
    expect(html).toContain("#/library/rules/r1");
    expect(html).toContain("#/configuration/runtimes/rt1");
  });

  it("shows the server's winner even when local data would suggest otherwise", () => {
    // The response says `project_override`; the dashboard must print exactly
    // that and never substitute a guessed `user` binding.
    const html = resolutionResultHtml(resolved());
    expect(html).toContain("project override");
    expect(html).not.toMatch(/\buser\b/i);
  });
});

describe("runtimeHtml / modelProfileHtml", () => {
  it("distinguishes 'no binding selected' from a failure", () => {
    const html = runtimeHtml(null);
    expect(html).toContain("No runtime binding selected");
    expect(html).toContain("valid outcome");
  });

  it("says a missing ModelProfile means no requirement", () => {
    expect(modelProfileHtml(null)).toContain("expresses no capability requirement");
  });
});

describe("compatibilityComparisonHtml", () => {
  it("reports Compatibility with requirements and declared capabilities", () => {
    const html = compatibilityComparisonHtml(resolved());
    expect(html).toContain("Requirements (ModelProfile)");
    expect(html).toContain("Runtime capabilities (declared)");
    expect(html).toContain("Compatible");
  });

  it("prints the server's unsatisfied list when present", () => {
    const fixture = resolved();
    fixture.runtime!.compatible = false;
    fixture.runtime!.unsatisfied = ["capability_x"];
    const html = compatibilityComparisonHtml(fixture);
    expect(html).toContain("Unsatisfied");
    expect(html).toContain("capability_x");
  });

  it("does not evaluate compatibility without a runtime", () => {
    const fixture = resolved();
    fixture.runtime = null;
    expect(compatibilityComparisonHtml(fixture)).toContain("not evaluated");
  });
});

describe("rulesTableHtml", () => {
  it("shows the dependency path provenance", () => {
    const html = rulesTableHtml(resolved().rules);
    expect(html).toContain("applies rule");
    expect(html).toContain("review-helper");
  });

  it("renders an empty state", () => {
    expect(rulesTableHtml([])).toContain("No rule resolved");
  });
});

describe("provenanceReasonsHtml", () => {
  it("answers why for version, rule, skill, profile and binding", () => {
    const html = provenanceReasonsHtml(resolved());
    expect(html).toContain("Why this version?");
    expect(html).toContain("Why rule coding-standard?");
    expect(html).toContain("Why skill code-review?");
    expect(html).toContain("Why this ModelProfile?");
    expect(html).toContain("project override");
  });

  it("says no binding won when the server selected none", () => {
    const fixture = resolved();
    fixture.runtime = null;
    expect(provenanceReasonsHtml(fixture)).toContain("no applicable runtime binding");
  });
});

describe("resolutionFailureHtml", () => {
  it("renders runtime_incompatible with level, unsatisfied and no fallback", () => {
    const error = new ApiError(
      parseErrorBody(422, {
        detail: {
          error_code: "runtime_incompatible",
          level: "project_override",
          matched_kind: "agent_definition",
          matched_stable_key: "review-helper",
          unsatisfied: ["capability_x"],
        },
      }),
    );
    const html = resolutionFailureHtml(resolutionErrorView(error));
    expect(html).toContain("runtime_incompatible");
    expect(html).toContain("project override");
    expect(html).toContain("capability_x");
    expect(html).toContain("No fallback performed");
  });

  it("renders a masked 404 without revealing ownership", () => {
    const error = new ApiError(parseErrorBody(404, { detail: { error_code: "definition_not_found" } }));
    const html = resolutionFailureHtml(resolutionErrorView(error));
    expect(html).toContain("Not found");
    expect(html).not.toMatch(/own/i);
  });

  it("renders an invalid_resolution_input reason", () => {
    const error = new ApiError(parseErrorBody(422, { detail: { error_code: "invalid_resolution_input", reason: "duplicate_session_override" } }));
    expect(resolutionFailureHtml(resolutionErrorView(error))).toContain("duplicate_session_override");
  });
});
