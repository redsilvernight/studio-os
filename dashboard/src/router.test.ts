import { describe, expect, it } from "vitest";
import { parseRoute } from "./router";

describe("parseRoute", () => {
  it("defaults to the dashboard", () => {
    expect(parseRoute("")).toEqual({ name: "dashboard" });
    expect(parseRoute("#/")).toEqual({ name: "dashboard" });
  });

  it("routes unknown hashes to notFound, no longer silently to the dashboard (UI-2, DEC-0079)", () => {
    expect(parseRoute("#/unknown")).toEqual({ name: "notFound", hash: "#/unknown" });
  });

  it("parses projects and project tabs", () => {
    expect(parseRoute("#/projects")).toEqual({ name: "projects" });
    expect(parseRoute("#/projects/abc")).toEqual({ name: "project", id: "abc", tab: "overview" });
    expect(parseRoute("#/projects/abc/tasks")).toEqual({ name: "project", id: "abc", tab: "tasks" });
    expect(parseRoute("#/projects/abc/claims")).toEqual({ name: "project", id: "abc", tab: "claims" });
    expect(parseRoute("#/projects/abc/roadmap")).toEqual({ name: "project", id: "abc", tab: "roadmap" });
  });

  it("parses a targeted roadmap and rejects deeper roadmap paths", () => {
    expect(parseRoute("#/projects/abc/roadmap/r1")).toEqual({ name: "project", id: "abc", tab: "roadmap", roadmapId: "r1" });
    expect(parseRoute("#/projects/abc/roadmap/r%201")).toEqual({ name: "project", id: "abc", tab: "roadmap", roadmapId: "r 1" });
    expect(parseRoute("#/projects/abc/roadmap/r1/extra")).toEqual({ name: "notFound", hash: "#/projects/abc/roadmap/r1/extra" });
    expect(parseRoute("#/projects/abc/tasks/r1")).toEqual({ name: "project", id: "abc", tab: "tasks" });
  });

  it("parses the UI-4 workspace tabs and falls back to overview otherwise", () => {
    expect(parseRoute("#/projects/abc/activity")).toEqual({ name: "project", id: "abc", tab: "activity" });
    expect(parseRoute("#/projects/abc/decisions")).toEqual({ name: "project", id: "abc", tab: "decisions" });
    expect(parseRoute("#/projects/abc/unknown")).toEqual({ name: "project", id: "abc", tab: "overview" });
  });

  it("parses tasks and task detail", () => {
    expect(parseRoute("#/tasks")).toEqual({ name: "tasks" });
    expect(parseRoute("#/tasks/t-1")).toEqual({ name: "task", id: "t-1" });
  });

  it("parses the DASH-4/DASH-5 screens", () => {
    expect(parseRoute("#/machines")).toEqual({ name: "machines" });
    expect(parseRoute("#/decisions")).toEqual({ name: "decisions" });
    expect(parseRoute("#/transfers")).toEqual({ name: "transfers" });
    expect(parseRoute("#/machines/extra")).toEqual({ name: "notFound", hash: "#/machines/extra" });
  });

  it("parses the UI-6 Agents routes (detail utiles, pas de détail vide)", () => {
    expect(parseRoute("#/agents")).toEqual({ name: "agents" });
    expect(parseRoute("#/agents/a-1")).toEqual({ name: "agent", id: "a-1" });
    expect(parseRoute("#/agents/a%2Fb")).toEqual({ name: "agent", id: "a/b" });
    expect(parseRoute("#/agents/a/b")).toEqual({ name: "notFound", hash: "#/agents/a/b" });
  });

  it("parses the P12 Library routes", () => {
    expect(parseRoute("#/library")).toEqual({ name: "library", kind: null });
    expect(parseRoute("#/library/rules")).toEqual({ name: "library", kind: "rules" });
    expect(parseRoute("#/library/skills")).toEqual({ name: "library", kind: "skills" });
    expect(parseRoute("#/library/agent-definitions")).toEqual({ name: "library", kind: "agent-definitions" });
    expect(parseRoute("#/library/workflows")).toEqual({ name: "library", kind: "workflows" });
    expect(parseRoute("#/library/model-profiles")).toEqual({ name: "library", kind: "model-profiles" });
    expect(parseRoute("#/library/rules/abc")).toEqual({ name: "libraryDetail", kind: "rules", id: "abc" });
    expect(parseRoute("#/library/nope")).toEqual({ name: "notFound", hash: "#/library/nope" });
  });

  it("parses the P12 Configuration routes", () => {
    expect(parseRoute("#/configuration")).toEqual({ name: "configRuntimes" });
    expect(parseRoute("#/configuration/runtimes")).toEqual({ name: "configRuntimes" });
    expect(parseRoute("#/configuration/runtimes/rt1")).toEqual({ name: "configRuntime", id: "rt1" });
    expect(parseRoute("#/configuration/bindings")).toEqual({ name: "configBindings" });
    expect(parseRoute("#/configuration/application")).toEqual({ name: "configApplication" });
    expect(parseRoute("#/configuration/integrations")).toEqual({ name: "configIntegrations" });
    expect(parseRoute("#/configuration/integrations/11111111-2222-4333-8444-555555555555")).toEqual({
      name: "configIntegrations",
      workspaceId: "11111111-2222-4333-8444-555555555555",
    });
    expect(parseRoute("#/configuration/project")).toEqual({ name: "configProject", tab: "resources" });
    expect(parseRoute("#/configuration/project/locks")).toEqual({ name: "configProject", tab: "locks" });
    expect(parseRoute("#/configuration/project/overrides")).toEqual({ name: "configProject", tab: "overrides" });
  });

  it("parses the Resolution Inspector routes", () => {
    expect(parseRoute("#/inspector")).toEqual({ name: "inspector", stableKey: null });
    expect(parseRoute("#/inspector/review-helper")).toEqual({ name: "inspector", stableKey: "review-helper" });
    expect(parseRoute("#/inspector/a%2Fb")).toEqual({ name: "inspector", stableKey: "a/b" });
  });

  it("parses the internal UI-1 Design System route (DEC-0078, no nav entry)", () => {
    expect(parseRoute("#/design-system")).toEqual({ name: "designSystem" });
    expect(parseRoute("#/design-system/extra")).toEqual({ name: "notFound", hash: "#/design-system/extra" });
  });

  it("parses the P11 first-run assistant route (desktop only, no nav entry)", () => {
    expect(parseRoute("#/bienvenue")).toEqual({ name: "onboarding" });
    expect(parseRoute("#/bienvenue/extra")).toEqual({ name: "notFound", hash: "#/bienvenue/extra" });
  });
});
