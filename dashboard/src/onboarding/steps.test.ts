import { describe, expect, it } from "vitest";
import { nextStep, ONBOARDING_STEPS, previousStep, stepById, STEP_ORDER } from "./steps";

describe("onboarding steps", () => {
  it("covers the full journey in order", () => {
    expect(STEP_ORDER).toEqual([
      "bienvenue",
      "connexion",
      "verification",
      "projet",
      "dossier",
      "memoire",
      "environnement",
      "assistant",
      "final",
      "termine",
    ]);
  });

  it("only the connected setup is required; git, memory, graph and harnesses stay optional", () => {
    const required = ONBOARDING_STEPS.filter((step) => step.required).map((step) => step.id);
    expect(required).toEqual(["bienvenue", "connexion", "verification", "projet", "dossier", "final", "termine"]);
    for (const id of ["memoire", "environnement", "assistant"] as const) {
      expect(stepById(id).required).toBe(false);
    }
  });

  it("steps use user words, never product internals", () => {
    const banned = ["MCP", "démon", "daemon", "Graphify", "Vault", "token", "UUID", "sidecar", "keyring"];
    for (const step of ONBOARDING_STEPS) {
      for (const word of banned) {
        expect(`${step.title} ${step.heading} ${step.intro}`).not.toContain(word);
      }
      expect(step.heading.length).toBeGreaterThan(0);
      expect(step.intro.length).toBeGreaterThan(0);
    }
  });

  it("walks forward and backward within bounds", () => {
    expect(nextStep("bienvenue")).toBe("connexion");
    expect(nextStep("termine")).toBeNull();
    expect(previousStep("bienvenue")).toBeNull();
    expect(previousStep("final")).toBe("assistant");
  });
});
