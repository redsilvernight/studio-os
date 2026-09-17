import { describe, expect, it } from "vitest";
import {
  asDependencyInputs,
  asIoInputs,
  asParticipantInputs,
  buildContent,
  buildDependencies,
  buildParticipants,
  buildWorkflowContent,
  buildWorkflowOutputs,
  contentFieldsHtml,
  contentSchemaFor,
  dependencyRowHtml,
  ioRowHtml,
  kindOptionsHtml,
  participantRowHtml,
} from "./libraryForms";
import type { FormReader } from "./libraryForms";

function reader(values: Record<string, string>, checks: Record<string, boolean> = {}): FormReader {
  return {
    text: (name: string) => values[name] ?? "",
    checked: (name: string) => checks[name] ?? false,
  };
}

describe("content schema", () => {
  it("names the canonical per-kind schema", () => {
    expect(contentSchemaFor("rule")).toBe("studio.library.rule/v1");
    expect(contentSchemaFor("workflow")).toBe("studio.library.workflow/v1");
  });

  it("renders per-kind fields (text for rule/skill, requirements for profile)", () => {
    expect(contentFieldsHtml("rule")).toContain('name="text"');
    expect(contentFieldsHtml("skill")).toContain('name="text"');
    expect(contentFieldsHtml("model_profile")).toContain('name="profile_description"');
    expect(contentFieldsHtml("model_profile")).toContain('name="context_window_min"');
    expect(contentFieldsHtml("agent_definition")).toContain('name="intended_use"');
  });
});

describe("buildContent", () => {
  it("requires text for a rule", () => {
    const result = buildContent("rule", reader({ text: "  " }));
    expect(result).toEqual({ ok: false, error: "text is required" });
  });

  it("builds a rule payload", () => {
    const result = buildContent("rule", reader({ text: "do the thing" }));
    expect(result).toEqual({ ok: true, value: { content_schema: "studio.library.rule/v1", text: "do the thing" } });
  });

  it("builds an agent_definition without optional fields", () => {
    const result = buildContent("agent_definition", reader({}));
    expect(result).toEqual({ ok: true, value: { content_schema: "studio.library.agent_definition/v1" } });
  });

  it("builds structured model_profile requirements", () => {
    const result = buildContent(
      "model_profile",
      reader({ reasoning: "high", tools_required: "shell, git", context_window_min: "100000" }, { coding: true, local_compatible: true }),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value["content_schema"]).toBe("studio.library.model_profile/v1");
    expect(result.value["requirements"]).toEqual({
      coding: true,
      local_compatible: true,
      tools_required: ["shell", "git"],
      reasoning: "high",
      context_window_min: 100000,
    });
  });

  it("maps the profile description to the content description (no field collision)", () => {
    const result = buildContent("model_profile", reader({ profile_description: "needs care" }));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value["description"]).toBe("needs care");
  });
});

describe("dependencies", () => {
  it("infers no relation when omitted and keeps explicit ones", () => {
    const result = buildDependencies([
      { kind: "rule", stable_key: "coding-standard", version: "2", relation: "" },
      { kind: "skill", stable_key: "code-review", version: "1", relation: "uses_skill" },
    ]);
    expect(result).toEqual({
      ok: true,
      value: [
        { kind: "rule", stable_key: "coding-standard", version: 2 },
        { kind: "skill", stable_key: "code-review", version: 1, relation: "uses_skill" },
      ],
    });
  });

  it("rejects a bad version and an empty key", () => {
    expect(buildDependencies([{ kind: "rule", stable_key: "a", version: "0", relation: "" }])).toEqual({
      ok: false,
      error: "dependency a needs a version ≥ 1",
    });
    expect(buildDependencies([{ kind: "rule", stable_key: "", version: "1", relation: "" }])).toEqual({
      ok: false,
      error: "dependency stable key is required",
    });
  });

  it("skips fully empty rows", () => {
    expect(buildDependencies([{ kind: "rule", stable_key: "", version: "", relation: "" }])).toEqual({ ok: true, value: [] });
  });

  it("reads back row fields from a plain record list", () => {
    expect(asDependencyInputs([{ kind: "rule", stable_key: "a", version: "1", relation: "" }])[0]).toEqual({
      kind: "rule",
      stable_key: "a",
      version: "1",
      relation: "",
    });
  });
});

describe("participants and workflow content", () => {
  const participantRows = [
    { participant_id: "implementer", agent_stable_key: "impl", depends_on: "", description: "" },
    { participant_id: "tester", agent_stable_key: "test", depends_on: "implementer", description: "runs tests" },
  ];
  const outputRows = [
    { name: "verdict", description: "", type: "", required: "true", source_participant: "tester", source_name: "report" },
  ];

  it("rejects duplicate participant ids", () => {
    const result = buildParticipants([
      { participant_id: "a", agent_stable_key: "x", depends_on: "", description: "" },
      { participant_id: "a", agent_stable_key: "y", depends_on: "", description: "" },
    ]);
    expect(result).toEqual({ ok: false, error: "duplicate participant a" });
  });

  it("requires an agent stable key per participant", () => {
    expect(buildParticipants([{ participant_id: "a", agent_stable_key: "", depends_on: "", description: "" }])).toEqual({
      ok: false,
      error: "participant a needs an agent stable key",
    });
  });

  it("requires a source for a workflow output", () => {
    expect(buildWorkflowOutputs([{ name: "verdict", description: "", type: "", required: "true", source_participant: "", source_name: "" }])).toEqual({
      ok: false,
      error: "workflow output verdict needs a source participant and name",
    });
  });

  it("assembles a canonical workflow content payload", () => {
    const result = buildWorkflowContent({
      summary: "review flow",
      participants: asParticipantInputs(participantRows),
      inputs: asIoInputs([{ name: "task", description: "", type: "", required: "true", source_participant: "", source_name: "" }]),
      outputs: asIoInputs(outputRows),
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value["content_schema"]).toBe("studio.library.workflow/v1");
    expect(result.value["summary"]).toBe("review flow");
    expect((result.value["participants"] as unknown[]).length).toBe(2);
  });
});

describe("row editors", () => {
  it("expose data-field attributes read back by readRows", () => {
    expect(dependencyRowHtml()).toContain('data-field="stable_key"');
    expect(participantRowHtml()).toContain('data-field="participant_id"');
    expect(ioRowHtml("input")).toContain('data-field="name"');
    expect(ioRowHtml("output")).toContain('data-field="source_participant"');
    expect(ioRowHtml("input")).not.toContain('data-field="source_participant"');
  });

  it("escapes values in the kind option list", () => {
    expect(kindOptionsHtml("workflow")).toContain('value="workflow" selected');
  });
});
