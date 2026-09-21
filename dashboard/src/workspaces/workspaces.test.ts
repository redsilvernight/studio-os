/**
 * P5 — Workspace Manager : tests DOM-free des libellés, du parseur fermé et
 * des rendus (divulgation progressive, pas de jargon, échappement).
 */
import { describe, expect, it } from "vitest";
import {
  P5_WORKSPACE_ROUTE,
  parseWorkspaceStatus,
  workspaceActionLabel,
  workspaceDetailHtml,
  workspaceFlowStepsHtml,
  workspaceFlowTitle,
  workspaceHealthLabel,
  workspaceListHtml,
  workspaceNavEntry,
  type WorkspaceStatusView,
} from "./workspaces";

const view: WorkspaceStatusView = {
  workspaceId: "11111111-1111-4111-8111-111111111111",
  projectName: "Jeu Phare",
  folderName: "jeu-phare",
  health: "valid",
  action: "none",
  candidateFolder: null,
  git: { branch: "main", detached: false, remote: null },
  features: [{ name: "Surveillance", on: false }],
  watchSummary: null,
};

describe("workspaceHealthLabel", () => {
  it("labels every health in plain language", () => {
    expect(workspaceHealthLabel("valid")).toBe("Prêt");
    expect(workspaceHealthLabel("config_missing")).toBe("À configurer");
    expect(workspaceHealthLabel("config_invalid")).toBe("À réparer");
    expect(workspaceHealthLabel("moved")).toBe("Dossier déplacé");
    expect(workspaceHealthLabel("inaccessible")).toBe("Inaccessible");
    expect(workspaceHealthLabel("project_unavailable")).toBe("Projet retiré du serveur");
  });
});

describe("workspaceActionLabel", () => {
  it("stays silent when nothing is expected", () => {
    expect(workspaceActionLabel("none")).toBe("");
  });

  it("never promises deletion on detach", () => {
    expect(workspaceActionLabel("detach_workspace")).toContain("rien ne sera supprimé");
  });
});

describe("parseWorkspaceStatus", () => {
  it("rejects unknown payloads without rendering", () => {
    expect(parseWorkspaceStatus(null)).toBeNull();
    expect(parseWorkspaceStatus({})).toBeNull();
    expect(parseWorkspaceStatus({ ...view, health: "mystery" })).toBeNull();
    expect(parseWorkspaceStatus({ ...view, action: "explode" })).toBeNull();
  });

  it("drops unknown fields instead of displaying them", () => {
    const parsed = parseWorkspaceStatus({ ...view, machineCredential: "x".repeat(40) });
    expect(parsed).not.toBeNull();
    expect(workspaceDetailHtml(parsed!)).not.toContain("x".repeat(40));
  });

  it("accepts a minimal valid payload", () => {
    const parsed = parseWorkspaceStatus({
      workspaceId: "w",
      projectName: "p",
      folderName: "f",
      health: "moved",
      action: "confirm_relocation",
      candidateFolder: "ailleurs",
    });
    expect(parsed?.candidateFolder).toBe("ailleurs");
    expect(parsed?.git).toBeNull();
  });
});

describe("workspaceListHtml", () => {
  it("shows an empty state without jargon", () => {
    const html = workspaceListHtml([]);
    expect(html).toContain("Aucun dossier lié");
  });

  it("escapes names", () => {
    const html = workspaceListHtml([{ ...view, projectName: "<script>" }]);
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });
});

describe("workspaceDetailHtml", () => {
  it("discloses details progressively", () => {
    const html = workspaceDetailHtml(view);
    expect(html).toContain("<details");
    expect(html).toContain("Dépôt");
    expect(html).toContain("Fonctions locales");
  });

  it("shows the relocation candidate when the folder moved", () => {
    const html = workspaceDetailHtml({ ...view, health: "moved", candidateFolder: "D:/nouveau" });
    expect(html).toContain("Dossier déplacé");
    expect(html).toContain("D:/nouveau");
  });

  it("stays readable when everything is off", () => {
    const html = workspaceDetailHtml({ ...view, features: [] });
    expect(html).toContain("Tout est coupé");
  });
});

describe("flows", () => {
  it("titles every flow without jargon", () => {
    expect(workspaceFlowTitle("existing_project_without_folder")).toBe("Projet sans dossier");
    expect(workspaceFlowTitle("non_git_folder")).toBe("Dossier simple");
  });

  it("renders steps as an ordered list", () => {
    const html = workspaceFlowStepsHtml("associate_local_folder", ["Choisissez", "Confirmez"]);
    expect(html).toContain("<ol>");
    expect(html).toContain("Confirmez");
  });
});

describe("navigation entry", () => {
  it("exposes an isolated mount point for P3", () => {
    expect(workspaceNavEntry()).toEqual({ hash: P5_WORKSPACE_ROUTE, label: "Dossiers" });
  });
});
