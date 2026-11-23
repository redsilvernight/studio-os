// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from "vitest";
import { renderHelp } from "./help";
import { renderSubscription } from "./subscription";
import { resetStudioStoreForTests, setStudios } from "../studioStore";

beforeEach(() => {
  resetStudioStoreForTests();
});

describe("subscription (R2-coque)", () => {
  it("shows the plan and status to the owner", () => {
    setStudios([{ id: "a", name: "Atelier Phare", slug: "phare", plan: "Gratuit", status: "active", role: "owner" }]);
    const view = document.createElement("div");
    renderSubscription(view, "owner");
    expect(view.innerHTML).toContain("Abonnement");
    expect(view.innerHTML).toContain("Atelier Phare");
    expect(view.innerHTML).toContain("Gratuit");
    expect(view.innerHTML).toContain("Actif");
  });

  it("explains the restriction to non-owners instead of failing", () => {
    setStudios([{ id: "a", name: "Atelier Phare", slug: "phare", plan: "Pro", status: "active", role: "member" }]);
    const view = document.createElement("div");
    renderSubscription(view, "member");
    expect(view.innerHTML).toContain("Réservé au propriétaire");
    expect(view.innerHTML).not.toMatch(/role="alert"/);
  });

  it("flags suspended studios in text", () => {
    setStudios([{ id: "a", name: "Atelier Phare", slug: "phare", plan: "Pro", status: "suspended", role: "owner" }]);
    const view = document.createElement("div");
    renderSubscription(view, "owner");
    expect(view.innerHTML).toContain("Suspendu");
  });
});

describe("help (R2-coque)", () => {
  it("documents roles and limits in French", () => {
    const view = document.createElement("div");
    renderHelp(view);
    expect(view.innerHTML).toContain("Aide");
    expect(view.innerHTML).toContain("Propriétaire");
    expect(view.innerHTML).toContain("Lecture seule");
    expect(view.innerHTML).toContain("#/abonnement");
  });
});
