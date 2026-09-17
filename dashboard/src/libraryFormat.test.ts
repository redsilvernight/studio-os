import { describe, expect, it } from "vitest";
import {
  bindingLevelLabel,
  capabilityEntries,
  contentSchema,
  contentText,
  dependencyLabel,
  kindFromSlug,
  kindMeta,
  libraryKindHref,
  parseWorkflowContent,
  provenanceReason,
  provenanceSourceLabel,
  relationLabel,
  requirementEntries,
  runtimeTargetEntries,
  scopeLabel,
  statusLabel,
  statusTone,
  versionOriginLabel,
  workflowEdges,
  type Provenance,
} from "./libraryFormat";

describe("kind vocabulary", () => {
  it("maps the five canonical kinds to human slugs and labels", () => {
    expect(kindFromSlug("rules")?.kind).toBe("rule");
    expect(kindFromSlug("skills")?.kind).toBe("skill");
    expect(kindFromSlug("agent-definitions")?.kind).toBe("agent_definition");
    expect(kindFromSlug("workflows")?.kind).toBe("workflow");
    expect(kindFromSlug("model-profiles")?.kind).toBe("model_profile");
    expect(kindFromSlug("nope")).toBeNull();
  });

  it("builds canonical deep links", () => {
    expect(libraryKindHref("rule")).toBe("#/library/rules");
    expect(libraryKindHref("workflow", "abc")).toBe("#/library/workflows/abc");
    expect(kindMeta("agent_definition").plural).toBe("Agent Definitions");
  });
});

describe("labels", () => {
  it("renders scope, status, level, origin and source labels", () => {
    expect(scopeLabel("studio")).toBe("Studio");
    expect(scopeLabel("project")).toBe("Project");
    expect(scopeLabel("user")).toBe("User");
    expect(statusLabel("deprecated")).toBe("Deprecated");
    expect(statusTone("active")).toBe("ok");
    expect(statusTone("deprecated")).toBe("bad");
    expect(statusTone("draft")).toBe("warn");
    expect(bindingLevelLabel("session")).toContain("session");
    expect(bindingLevelLabel("project_override")).toBe("project override");
    expect(versionOriginLabel("lock")).toBe("project lock");
    expect(provenanceSourceLabel("session_override")).toContain("temporary session override");
    expect(relationLabel("uses_skill")).toBe("uses skill");
  });
});

describe("requirement / capability projections", () => {
  it("lists only meaningful requirement dimensions", () => {
    const entries = requirementEntries({
      reasoning: null,
      coding: true,
      context_window_min: 100000,
      tools_required: ["shell", "git"],
      multimodal: null,
      local_compatible: true,
      cost: null,
      latency: null,
    });
    expect(entries.map((entry) => entry.key).sort()).toEqual(["coding", "context_window_min", "local_compatible", "tool:git", "tool:shell"]);
  });

  it("returns nothing for an empty requirement", () => {
    expect(requirementEntries({ coding: false, tools_required: [], local_compatible: false })).toEqual([]);
    expect(requirementEntries(null)).toEqual([]);
  });

  it("projects declared capabilities", () => {
    const entries = capabilityEntries({ coding: true, context_window: 128000, tools: ["shell"], local: true });
    expect(entries.map((entry) => entry.key).sort()).toEqual(["coding", "context_window", "local", "tool:shell"]);
  });
});

describe("provenanceReason", () => {
  it("names a project lock for a locked version", () => {
    const provenance: Provenance = { source: "project_lock", version: 3, scope: "studio", version_origin: "lock", locked: true };
    const reason = provenanceReason(provenance);
    expect(reason).toContain("project lock");
    expect(reason).toContain("v3");
  });

  it("names the winning binding level for a runtime binding", () => {
    const provenance: Provenance = { source: "runtime_binding", binding_level: "project_override", via: "agent_definition:review-helper", locked: false };
    const reason = provenanceReason(provenance);
    expect(reason).toContain("project override");
    expect(reason).toContain("agent_definition:review-helper");
  });

  it("names a session override", () => {
    const provenance: Provenance = { source: "session_override", binding_level: "session", via: "model_profile:review-profile", locked: false };
    expect(provenanceReason(provenance)).toContain("session");
  });
});

describe("content helpers", () => {
  it("reads the content schema and text", () => {
    expect(contentSchema({ content_schema: "studio.library.rule/v1" })).toBe("studio.library.rule/v1");
    expect(contentSchema({})).toBeNull();
    expect(contentText({ text: "hello" })).toBe("hello");
    expect(contentText(undefined)).toBeNull();
  });

  it("labels a dependency pin", () => {
    expect(dependencyLabel({ kind: "rule", stable_key: "coding-standard", version: 2 })).toBe("Rule coding-standard v2");
  });

  it("lists runtime target anchors", () => {
    const entries = runtimeTargetEntries({ runtime_id: "rt1", harness_ref: "h", capabilities: { coding: false, tools: [], local: false } });
    expect(entries.map((entry) => entry.key)).toEqual(["runtime_id", "harness_ref"]);
  });
});

describe("workflow content", () => {
  const content = {
    content_schema: "studio.library.workflow/v1",
    summary: "review flow",
    participants: [
      { participant_id: "implementer", agent_stable_key: "impl", depends_on: [], inputs: [{ name: "task", required: true }], outputs: [{ name: "patch", required: true }] },
      { participant_id: "tester", agent_stable_key: "test", depends_on: ["implementer"], inputs: [{ name: "patch", required: true, source: { participant_id: "implementer", name: "patch" } }], outputs: [{ name: "report", required: true }] },
      { participant_id: "reviewer", agent_stable_key: "rev", depends_on: ["tester"], inputs: [], outputs: [] },
    ],
    inputs: [{ name: "task", required: true }],
    outputs: [{ name: "verdict", required: true, source: { participant_id: "tester", name: "report" } }],
  };

  it("parses the canonical shape into a read-only view", () => {
    const view = parseWorkflowContent(content);
    expect(view).not.toBeNull();
    expect(view?.participants.map((participant) => participant.participantId)).toEqual(["implementer", "tester", "reviewer"]);
  });

  it("rejects non-workflow content instead of guessing", () => {
    expect(parseWorkflowContent({ content_schema: "studio.library.rule/v1" })).toBeNull();
    expect(parseWorkflowContent(undefined)).toBeNull();
  });

  it("projects declared dependency edges exactly (no graph algorithm)", () => {
    const view = parseWorkflowContent(content);
    expect(view).not.toBeNull();
    expect(workflowEdges(view!)).toEqual([
      { from: "implementer", to: "tester" },
      { from: "tester", to: "reviewer" },
    ]);
  });
});
