import { describe, expect, it } from "vitest";
import { nextStep, ONBOARDING_STEPS, previousStep, stepById, STEP_ORDER } from "./steps";

describe("onboarding steps", () => {
  it("covers the workstation-only journey in order", () => {
    expect(STEP_ORDER).toEqual([
      "bienvenue",
      "connexion",
      "verification",
      "final",
      "termine",
    ]);
  });

  it("configures only the workstation: every step is required, no project or folder", () => {
    const required = ONBOARDING_STEPS.filter((step) => step.required).map((step) => step.id);
    expect(required).toEqual(["bienvenue", "connexion", "verification", "final", "termine"]);
    for (const id of ["projet", "dossier", "memoire", "environnement", "assistant"] as const) {
      expect(() => stepById(id as never)).toThrow("unknown onboarding step");
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

  it("the ready screen points at per-folder setup without requiring it", () => {
    expect(stepById("final").intro).toContain("Dossiers du projet");
  });

  it("walks forward and backward within bounds", () => {
    expect(nextStep("bienvenue")).toBe("connexion");
    expect(nextStep("verification")).toBe("final");
    expect(nextStep("termine")).toBeNull();
    expect(previousStep("bienvenue")).toBeNull();
    expect(previousStep("final")).toBe("verification");
  });
});
