import { describe, expect, it } from "vitest";
import {
  ANCHOR_REQUIRED_ERROR,
  buildBindingCreate,
  buildBindingCreateTarget,
  buildRuntimeCreate,
  buildRuntimeUpdate,
  capabilityFieldsHtml,
  declaredCapabilityGaps,
  harnessFieldHtml,
  machineFieldHtml,
  machineOptionsFrom,
  metadataLinesFrom,
  parseMetadataLines,
  readCapabilities,
  type RuntimeUpdateBaseline,
} from "./configForms";
import type { FormReader } from "./libraryForms";

function reader(values: Record<string, string>, checks: Record<string, boolean> = {}): FormReader {
  return {
    text: (name: string) => values[name] ?? "",
    checked: (name: string) => checks[name] ?? false,
  };
}

describe("parseMetadataLines", () => {
  it("parses key=value lines and ignores blank lines", () => {
    expect(parseMetadataLines("region=eu\n\n note = hello ")).toEqual({ ok: true, value: { region: "eu", note: "hello" } });
  });

  it("reports the malformed line number instead of ignoring it", () => {
    expect(parseMetadataLines("region=eu\n\nmalformed")).toEqual({
      ok: false,
      error: "métadonnées, ligne 3 : format attendu clé=valeur",
      field: "metadata",
    });
    expect(parseMetadataLines("=value").ok).toBe(false);
  });

  it("round-trips primitive metadata as lines", () => {
    expect(metadataLinesFrom({ region: "eu", nested: { a: 1 }, n: 2 })).toBe("region=eu\nn=2");
  });
});

describe("readCapabilities", () => {
  it("keeps open strings and structured booleans", () => {
    const capabilities = readCapabilities(reader({ cap_reasoning: "high", cap_tools: "shell, git", cap_context_window: "128000" }, { cap_coding: true }));
    expect(capabilities).toEqual({
      ok: true,
      value: { coding: true, tools: ["shell", "git"], local: false, reasoning: "high", context_window: 128000 },
    });
  });

  it("rejects a non-integer or non-positive context window", () => {
    for (const raw of ["12.5", "0", "-3", "abc"]) {
      expect(readCapabilities(reader({ cap_context_window: raw }))).toEqual({
        ok: false,
        error: "la fenêtre de contexte doit être un entier positif",
        field: "cap_context_window",
      });
    }
  });

  it("rejects a tool name containing a space", () => {
    const result = readCapabilities(reader({ cap_tools: "shell, web search" }));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.field).toBe("cap_tools");
    expect(result.error).toContain("web search");
  });
});

describe("capability and machine fields", () => {
  it("pre-fills capability inputs and keeps HTML hints", () => {
    const html = capabilityFieldsHtml(false, { coding: true, tools: ["shell", "git"], local: false, context_window: 64000 });
    expect(html).toContain('value="64000"');
    expect(html).toContain('value="shell,git"');
    expect(html).toContain('min="1"');
    expect(html).toContain("pattern=");
    expect(html).toMatch(/name="cap_coding" type="checkbox" checked/);
  });

  it("labels machines by display name and nests a tool under its workstation", () => {
    const options = machineOptionsFrom([
      { id: "ws", display_name: "Atelier" },
      { id: "tool", display_name: "opencode", workstation_id: "ws" },
      { id: "orphan", display_name: " ", workstation_id: "missing" },
    ]);
    expect(options).toEqual([
      { id: "ws", label: "Atelier" },
      { id: "tool", label: "Atelier › opencode" },
      { id: "orphan", label: "Poste sans nom" },
    ]);
  });

  it("renders a machine select with a remote option, or degrades to a text input", () => {
    const select = machineFieldHtml([{ id: "ws", label: "Atelier" }], "ws");
    expect(select).toContain("<select name=\"machine_id\"");
    expect(select).toContain("Aucun poste (cible distante)");
    expect(select).toContain('<option value="ws" selected>Atelier</option>');
    expect(select).not.toContain("uuid");
    const unknown = machineFieldHtml([{ id: "ws", label: "Atelier" }], "gone");
    expect(unknown).toContain('<option value="gone" selected>');
    const fallback = machineFieldHtml(null, "m-1");
    expect(fallback).toContain('<input name="machine_id" value="m-1"');
  });

  it("suggests harness ids through an open datalist", () => {
    const html = harnessFieldHtml("h-list", "custom");
    expect(html).toContain('list="h-list"');
    expect(html).toContain('value="custom"');
    for (const harness of ["claude-code", "opencode", "codex"]) expect(html).toContain(`<option value="${harness}">`);
    expect(html).toContain("Outil (harness)");
  });
});

describe("declaredCapabilityGaps", () => {
  const requirement = { coding: true, context_window_min: 100000, tools_required: ["shell", "git"], local_compatible: true };

  it("lists every declared mismatch", () => {
    const gaps = declaredCapabilityGaps(requirement, { coding: false, tools: ["git"], local: false, context_window: 32000 });
    expect(gaps.map((gap) => gap.key)).toEqual(["coding", "context_window_min", "tool:shell", "local_compatible"]);
    expect(gaps[1]).toEqual({ key: "context_window_min", label: "Fenêtre de contexte", required: "≥ 100000", declared: "32000" });
  });

  it("reports an undeclared context window", () => {
    const gaps = declaredCapabilityGaps({ coding: false, tools_required: [], local_compatible: false, context_window_min: 8000 }, { coding: false, tools: [], local: false });
    expect(gaps).toEqual([{ key: "context_window_min", label: "Fenêtre de contexte", required: "≥ 8000", declared: "non déclarée" }]);
  });

  it("returns nothing when the runtime meets the requirement or none is declared", () => {
    expect(declaredCapabilityGaps(requirement, { coding: true, tools: ["shell", "git"], local: true, context_window: 200000 })).toEqual([]);
    expect(declaredCapabilityGaps(null, { coding: false, tools: [], local: false })).toEqual([]);
  });
});

describe("buildRuntimeCreate", () => {
  it("requires at least one anchor", () => {
    expect(buildRuntimeCreate(reader({}))).toEqual({ ok: false, error: ANCHOR_REQUIRED_ERROR, field: "harness_ref" });
  });

  it("declares capabilities and accepts open refs", () => {
    const result = buildRuntimeCreate(reader({ harness_ref: "any-harness", provider_ref: "any-provider", model_ref: "any-model", metadata: "region=eu" }));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.capability_source).toBe("declared");
    expect(result.value.harness_ref).toBe("any-harness");
    expect(result.value.runtime_metadata).toEqual({ region: "eu" });
  });

  it("surfaces field validation errors", () => {
    expect(buildRuntimeCreate(reader({ harness_ref: "h", metadata: "ok=1\nbad" }))).toMatchObject({ ok: false, field: "metadata" });
    expect(buildRuntimeCreate(reader({ harness_ref: "h", cap_context_window: "1.5" }))).toMatchObject({ ok: false, field: "cap_context_window" });
  });
});

describe("buildRuntimeUpdate", () => {
  const baseline: RuntimeUpdateBaseline = {
    machine_id: "m-1",
    harness_ref: "harness-a",
    provider_ref: "provider-a",
    model_ref: "model-a",
    capabilities: { coding: true, tools: ["shell"], local: false },
    runtime_metadata: { region: "eu" },
  };
  const unchanged = {
    machine_id: "m-1",
    harness_ref: "harness-a",
    provider_ref: "provider-a",
    model_ref: "model-a",
    cap_tools: "shell",
    metadata: "region=eu",
    expected_version: "3",
  };
  const coding = { cap_coding: true };

  it("sends only the changed fields", () => {
    const result = buildRuntimeUpdate(reader({ ...unchanged, model_ref: "model-b" }, coding), baseline);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.expected_version).toBe(3);
    expect(result.value.update).toEqual({ detach_machine: false, model_ref: "model-b" });
  });

  it("refuses an empty update", () => {
    expect(buildRuntimeUpdate(reader(unchanged, coding), baseline)).toEqual({ ok: false, error: "aucune modification à enregistrer" });
  });

  it("detaches the machine when « Aucun poste » is chosen and moves it otherwise", () => {
    const detached = buildRuntimeUpdate(reader({ ...unchanged, machine_id: "" }, coding), baseline);
    expect(detached.ok && detached.value.update).toEqual({ detach_machine: true });
    const moved = buildRuntimeUpdate(reader({ ...unchanged, machine_id: "m-2" }, coding), baseline);
    expect(moved.ok && moved.value.update).toEqual({ detach_machine: false, machine_id: "m-2" });
  });

  it("includes capabilities and metadata only when they differ", () => {
    const result = buildRuntimeUpdate(reader({ ...unchanged, cap_tools: "shell,git", metadata: "region=us" }, coding), baseline);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.update.capabilities?.tools).toEqual(["shell", "git"]);
    expect(result.value.update.runtime_metadata).toEqual({ region: "us" });
    expect(result.value.update.harness_ref).toBeUndefined();
  });

  it("refuses to clear a reference the API cannot erase", () => {
    expect(buildRuntimeUpdate(reader({ ...unchanged, provider_ref: "" }, coding), baseline)).toMatchObject({ ok: false, field: "provider_ref" });
  });

  it("rejects a missing expected_version", () => {
    expect(buildRuntimeUpdate(reader({ ...unchanged, model_ref: "model-b", expected_version: "" }, coding), baseline)).toEqual({
      ok: false,
      error: "la version attendue (Avancé) doit être un entier ≥ 1",
      field: "expected_version",
    });
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
      error: "le niveau doit être user, project_override, project_default ou studio_default",
      field: "level",
    });
  });

  it("requires a project for project levels", () => {
    expect(buildBindingCreate(reader({ ...base, level: "project_override", project_id: "" }))).toEqual({
      ok: false,
      error: "project_override exige un ID de projet",
      field: "project_id",
    });
  });

  it("requires an anchor when no registry id is given", () => {
    expect(buildBindingCreate(reader({ ...base, runtime_id: "" }))).toEqual({
      ok: false,
      error: "choisissez un runtime enregistré, ou au moins un ancrage direct (poste, outil, fournisseur ou modèle)",
      field: "runtime_id",
    });
  });
});
