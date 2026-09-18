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
  inspectorFormHtml,
  identityHtml,
  skillsTableHtml,
  rawJsonHtml,
  safeResponseJson,
} from "./inspector";
import { dsEmptyState, dsSkeleton } from "../ds/ds";

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

const overrideFixture = { targetKind: "agent_definition", stableKey: "", runtimeId: "", machineId: "", harnessRef: "", providerRef: "", modelRef: "" };

describe("buildResolutionRequest", () => {
  it("requires an AgentDefinition stable key", () => {
    expect(buildResolutionRequest({ stableKey: "  ", projectId: "", enableOverride: false, override: overrideFixture })).toEqual({
      ok: false,
      error: "an AgentDefinition stable key is required",
    });
  });

  it("builds a plain request with no ephemeral override", () => {
    const built = buildResolutionRequest({ stableKey: "review-helper", projectId: "", enableOverride: false, override: overrideFixture });
    expect(built).toEqual({ ok: true, value: { stable_key: "review-helper", session_overrides: [] } });
  });

  it("adds a temporary session override without any persistence field", () => {
    const built = buildResolutionRequest({
      stableKey: "review-helper",
      projectId: "p1",
      enableOverride: true,
      override: { ...overrideFixture, targetKind: "model_profile", stableKey: "review-profile", runtimeId: "rt1" },
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
      override: { ...overrideFixture, stableKey: "review-helper" },
    });
    expect(built).toEqual({ ok: false, error: "session override needs a runtime id or at least one inline anchor" });
  });

  it("rejects an invalid target kind", () => {
    const built = buildResolutionRequest({
      stableKey: "review-helper",
      projectId: "",
      enableOverride: true,
      override: { ...overrideFixture, targetKind: "invalid_kind", stableKey: "review-profile", runtimeId: "rt1" },
    });
    expect(built.ok).toBe(false);
    if (!built.ok) expect(built.error).toContain("must be agent_definition or model_profile");
  });
});

describe("inspectorFormHtml", () => {
  it("renders form with stable key input and datalist", () => {
    const html = inspectorFormHtml("review-helper", "p1", ["review-helper", "other-agent"]);
    expect(html).toContain('name="stable_key"');
    expect(html).toContain('value="review-helper"');
    expect(html).toContain('id="agent-keys"');
    expect(html).toContain("other-agent");
  });

  it("renders project id input", () => {
    const html = inspectorFormHtml(null, "p1", []);
    expect(html).toContain('name="project_id"');
    expect(html).toContain('value="p1"');
  });

  it("renders the ephemeral session override section collapsed, with contract fields only", () => {
    const html = inspectorFormHtml(null, null, []);
    expect(html).toContain("<details");
    expect(html).toContain("Remplacement de session éphémère");
    for (const field of ["enable_override", "override_target_kind", "override_stable_key", "override_runtime_id", "override_machine_id", "override_harness_ref", "override_provider_ref", "override_model_ref"]) {
      expect(html).toContain(`name="${field}"`);
    }
    expect(html).toContain("session_overrides");
  });

  it("uses French labels and keeps technical ids canonical", () => {
    const html = inspectorFormHtml(null, null, []);
    expect(html).toContain("Clé stable AgentDefinition");
    expect(html).toContain("ID Projet");
    expect(html).toContain("Résoudre");
    expect(html).toContain("POST /resolutions");
  });

  it("has no inline styles or event handlers (CSP)", () => {
    const html = inspectorFormHtml(null, null, []);
    expect(html).not.toMatch(/style\s*=/i);
    expect(html).not.toMatch(/on\w+\s*=/i);
    expect(html).not.toMatch(/javascript:/i);
  });
});

describe("resolutionResultHtml", () => {
  it("renders identity, rules, skills, profile, runtime and provenance", () => {
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
    expect(html).toContain("Pourquoi cette version");
    expect(html).toContain("Quel binding a gagné");
  });

  it("cross-links rules/skills/profile to Library and the runtime to Settings", () => {
    const html = resolutionResultHtml(resolved());
    expect(html).toContain("#/library/rules/r1");
    expect(html).toContain("#/library/skills/s1");
    expect(html).toContain("#/library/model-profiles/m1");
    expect(html).toContain("#/configuration/runtimes/rt1");
  });

  it("prints the server's winner even when local data would suggest otherwise", () => {
    const html = resolutionResultHtml(resolved());
    expect(html).toContain("project override");
    expect(html).not.toMatch(/\buser\b/i);
  });

  it("wraps sections in ds-panel with stable accessible headings", () => {
    const html = resolutionResultHtml(resolved());
    expect(html).toContain('class="ds-panel inspector-section"');
    for (const id of ["inspector-identity", "inspector-model-profile", "inspector-runtime", "inspector-compatibility", "inspector-provenance", "inspector-rules", "inspector-skills"]) {
      expect(html).toContain(`id="${id}"`);
    }
  });

  it("keeps raw JSON secondary inside a details element", () => {
    const html = resolutionResultHtml(resolved());
    expect(html).toContain("<details");
    expect(html).toContain("Données brutes (JSON filtré)");
    expect(html).toContain('<pre class="code">');
  });
});

describe("runtimeHtml / modelProfileHtml", () => {
  it("distinguishes 'no binding selected' from a failure", () => {
    const html = runtimeHtml(null);
    expect(html).toContain("Aucun binding runtime sélectionné");
    expect(html).toContain("résultat valide");
  });

  it("says a missing ModelProfile means no capability requirement", () => {
    expect(modelProfileHtml(null)).toContain("Aucun ModelProfile lié");
    expect(modelProfileHtml(null)).toContain("n'exprime aucune exigence");
  });

  it("renders runtime refs, declared capabilities and a Settings link", () => {
    const html = runtimeHtml(resolved().runtime);
    expect(html).toContain("project override");
    expect(html).toContain("rt1");
    expect(html).toContain("opencode");
    expect(html).toContain("provider_a");
    expect(html).toContain("model_a");
    expect(html).toContain("#/configuration/runtimes/rt1");
  });

  it("shows a machine identity and links to Machines (no machine detail route)", () => {
    const fixture = resolved();
    fixture.runtime!.target.machine_id = "m-1234567890abcdef";
    const html = runtimeHtml(fixture.runtime);
    expect(html).toContain("Machine :");
    expect(html).toContain("#/machines");
    expect(html).not.toContain("#/machines/");
  });

  it("renders inline anchors when no runtime registry id", () => {
    const fixture = resolved();
    fixture.runtime!.target = { ...fixture.runtime!.target, runtime_id: null, harness_ref: "custom-harness", provider_ref: "custom-provider", model_ref: "custom-model" };
    const html = runtimeHtml(fixture.runtime);
    expect(html).not.toContain("#/configuration/runtimes/");
    expect(html).toContain("custom-harness");
    expect(html).toContain("custom-provider");
    expect(html).toContain("custom-model");
  });
});

describe("compatibilityComparisonHtml", () => {
  it("reports the canonical Compatible verdict with requirements and capabilities", () => {
    const html = compatibilityComparisonHtml(resolved());
    expect(html).toContain("Exigences (ModelProfile)");
    expect(html).toContain("Capacités runtime (déclarées)");
    expect(html).toContain("Compatible");
    expect(html).toContain("status ok");
  });

  it("prints the server's unsatisfied list as Incompatible", () => {
    const fixture = resolved();
    fixture.runtime!.compatible = false;
    fixture.runtime!.unsatisfied = ["capability_x", "capability_y"];
    const html = compatibilityComparisonHtml(fixture);
    expect(html).toContain("Incompatible");
    expect(html).toContain("capability_x");
    expect(html).toContain("capability_y");
    expect(html).toContain("status bad");
  });

  it("does not evaluate compatibility without a runtime", () => {
    const fixture = resolved();
    fixture.runtime = null;
    expect(compatibilityComparisonHtml(fixture)).toContain("n'est pas évaluée");
  });

  it("unknown is never shown as Compatible", () => {
    const fixture = resolved();
    fixture.runtime = null;
    const html = compatibilityComparisonHtml(fixture);
    expect(html).not.toContain("Compatible");
    expect(html).not.toContain("status ok");
  });

  it("never invents a numeric score", () => {
    const html = compatibilityComparisonHtml(resolved());
    expect(html).not.toMatch(/\d+%/);
    expect(html).not.toContain("score");
  });
});

describe("rulesTableHtml / skillsTableHtml", () => {
  it("shows the dependency path provenance and Library link", () => {
    const html = rulesTableHtml(resolved().rules);
    expect(html).toContain("applies rule");
    expect(html).toContain("review-helper");
    expect(html).toContain("#/library/rules/r1");
    expect(html).toContain('class="ds-table-wrap"');
  });

  it("renders a French empty state for both", () => {
    expect(rulesTableHtml([])).toContain("Aucune règle résolue");
    expect(skillsTableHtml([])).toContain("Aucune compétence résolue");
    expect(rulesTableHtml([])).toContain("ds-empty");
  });

  it("shows the deprecated badge when applicable", () => {
    const fixture = resolved();
    fixture.rules![0]!.deprecated = true;
    const html = rulesTableHtml(fixture.rules);
    expect(html).toContain("deprecated");
    expect(html).toContain("status bad");
  });

  it("links skills to the Library with their provenance reason", () => {
    const html = skillsTableHtml(resolved().skills);
    expect(html).toContain("code-review");
    expect(html).toContain("#/library/skills/s1");
    expect(html).toContain("version pin");
  });
});

describe("provenanceReasonsHtml", () => {
  it("answers why for version, rule, skill, profile and binding", () => {
    const html = provenanceReasonsHtml(resolved());
    expect(html).toContain("Pourquoi cette version");
    expect(html).toContain("Pourquoi la règle coding-standard");
    expect(html).toContain("Pourquoi la compétence code-review");
    expect(html).toContain("Pourquoi ce ModelProfile");
    expect(html).toContain("Quel binding a gagné");
    expect(html).toContain("project override");
    expect(html).toContain("runtime binding");
  });

  it("says no binding won when the server selected none", () => {
    const fixture = resolved();
    fixture.runtime = null;
    expect(provenanceReasonsHtml(fixture)).toContain("pas de binding runtime applicable");
  });

  it("surfaces a session override source", () => {
    const fixture = resolved();
    fixture.runtime!.provenance = { source: "session_override", binding_level: "session", via: "agent_definition:review-helper", locked: false };
    expect(provenanceReasonsHtml(fixture)).toContain("temporary session override");
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
    expect(html).toContain("Aucun repli automatique");
    expect(html).toContain('role="alert"');
  });

  it("renders a masked 404 without revealing ownership", () => {
    const error = new ApiError(parseErrorBody(404, { detail: { error_code: "definition_not_found" } }));
    const html = resolutionFailureHtml(resolutionErrorView(error));
    expect(html).toContain("Non trouvé");
    expect(html).not.toMatch(/own/i);
    expect(html).not.toMatch(/propriété/i);
  });

  it("renders an invalid_resolution_input reason", () => {
    const error = new ApiError(parseErrorBody(422, { detail: { error_code: "invalid_resolution_input", reason: "duplicate_session_override" } }));
    expect(resolutionFailureHtml(resolutionErrorView(error))).toContain("duplicate_session_override");
  });

  it("renders an auth error with its status", () => {
    const error = new ApiError(parseErrorBody(401, { detail: { error_code: "unauthorized", message: "Invalid token" } }));
    const html = resolutionFailureHtml(resolutionErrorView(error));
    expect(html).toContain("Non autorisé");
    expect(html).toContain("401");
  });

  it("renders a generic server error with code and message", () => {
    const error = new ApiError(parseErrorBody(500, { detail: { error_code: "internal_error", message: "Server error" } }));
    const html = resolutionFailureHtml(resolutionErrorView(error));
    expect(html).toContain("internal_error");
    expect(html).toContain("internal_error (HTTP 500)");
  });

  it("returns empty string on success (resolved provided)", () => {
    const view = resolutionErrorView(new ApiError(parseErrorBody(422, { detail: { error_code: "runtime_incompatible" } })));
    expect(resolutionFailureHtml(view, resolved())).toBe("");
  });
});

describe("identityHtml", () => {
  it("renders identity with version, origin, scope and a Library link", () => {
    const html = identityHtml(resolved());
    expect(html).toContain("review-helper");
    expect(html).toContain("v4");
    expect(html).toContain("project lock");
    expect(html).toContain("Studio");
    expect(html).toContain("#/library/agent-definitions/a1");
  });

  it("shows a deprecated badge when applicable", () => {
    const fixture = resolved();
    fixture.agent.deprecated = true;
    expect(identityHtml(fixture)).toContain("status bad");
  });
});

describe("raw data safety (allowlist, no secrets)", () => {
  it("safeResponseJson contains only safe fields", () => {
    const json = safeResponseJson(resolved());
    expect(json).toContain("resource_id");
    expect(json).toContain("stable_key");
    expect(json).toContain("version");
    expect(json).toContain("provenance");
    expect(json).toContain("requirements");
  });

  it("never leaks secrets or credentials, even in raw data", () => {
    const haystacks = [safeResponseJson(resolved()), rawJsonHtml(resolved())].join("\n").toLowerCase();
    for (const forbidden of ["secret", "password", "token", "authorization", "credential", "api_key", "apikey", "bearer"]) {
      expect(haystacks).not.toContain(forbidden);
    }
  });

  it("wraps raw data in a details element", () => {
    const html = rawJsonHtml(resolved());
    expect(html).toContain('<details class="editor inspector-raw">');
    expect(html).toContain("Données brutes (JSON filtré)");
    expect(html).toContain('<pre class="code">');
  });
});

describe("French UI / CSP", () => {
  it("user-facing text is in French", () => {
    const html = resolutionResultHtml(resolved());
    expect(html).toContain("Identité résolue");
    expect(html).toContain("Runtime sélectionné");
    expect(html).toContain("Compatibilité");
    expect(html).toContain("Pourquoi ce résultat");
  });

  it("keeps technical ids in canonical form", () => {
    const html = resolutionResultHtml(resolved());
    for (const value of ["review-helper", "coding-standard", "code-review", "review-profile", "rt1", "opencode", "provider_a", "model_a", "project_override", "runtime_binding"]) {
      expect(html).toContain(value);
    }
  });

  it("has no inline styles, handlers or javascript: URLs", () => {
    const html = resolutionResultHtml(resolved());
    expect(html).not.toMatch(/style\s*=/i);
    expect(html).not.toMatch(/on\w+\s*=/i);
    expect(html).not.toMatch(/javascript:/i);
  });
});

describe("Empty / Loading / Error structural states", () => {
  it("empty state explains purpose and offers an action", () => {
    const html = dsEmptyState("Aucune inspection lancée", "Choisissez un champ puis lancez une résolution.", { label: "Nouvelle inspection", href: "#/inspector" });
    expect(html).toContain("Aucune inspection lancée");
    expect(html).toContain("Nouvelle inspection");
  });

  it("loading skeleton announces itself to assistive tech", () => {
    const html = dsSkeleton(4);
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain('aria-label="Chargement en cours"');
    expect(html).toContain("ds-sr-only");
  });

  it("errors use role=alert and the danger notice", () => {
    const error = new ApiError(parseErrorBody(422, { detail: { error_code: "runtime_incompatible" } }));
    const html = resolutionFailureHtml(resolutionErrorView(error));
    expect(html).toContain('role="alert"');
    expect(html).toContain("ds-notice--danger");
  });
});

describe("Accessibility and responsive structure", () => {
  it("result sections expose an accessible heading hierarchy", () => {
    const html = resolutionResultHtml(resolved());
    expect(html).toMatch(/<h2[^>]*id="inspector-identity"/);
    expect(html).toMatch(/<h2[^>]*id="inspector-runtime"/);
    expect(html).toMatch(/<h2[^>]*id="inspector-compatibility"/);
    expect(html).toMatch(/<h2[^>]*id="inspector-provenance"/);
  });

  it("compatibility labels are textual, never colour-only", () => {
    const ok = compatibilityComparisonHtml(resolved());
    expect(ok).toContain("Compatible");
    const fixture = resolved();
    fixture.runtime!.unsatisfied = ["capability_x"];
    expect(compatibilityComparisonHtml(fixture)).toContain("Incompatible");
  });

  it("tables are wrapped for local horizontal scroll", () => {
    expect(rulesTableHtml(resolved().rules)).toContain('class="ds-table-wrap"');
    expect(skillsTableHtml(resolved().skills)).toContain('class="ds-table-wrap"');
    expect(compatibilityComparisonHtml(resolved())).toContain('class="ds-table-wrap"');
  });
});
