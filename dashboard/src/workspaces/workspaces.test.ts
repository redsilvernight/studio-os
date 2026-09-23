/**
 * P5 — Workspace Manager : tests DOM-free des libellés, du parseur fermé et
 * des rendus (divulgation progressive, pas de jargon, échappement).
 */
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  P5_WORKSPACE_ROUTE,
  WORKSPACE_ACTIONS,
  WORKSPACE_HEALTHS,
  toWorkspaceViewModel,
  workspaceActionLabel,
  workspaceDetailHtml,
  workspaceFlowStepsHtml,
  workspaceFlowTitle,
  workspaceHealthLabel,
  workspaceListHtml,
  workspaceNavEntry,
  type WorkspaceViewModel,
} from "./workspaces";

const localDir = resolve(__dirname, "..", "..", "..", "contracts", "local");
const canonicalStatuses = readdirSync(resolve(localDir, "fixtures", "valid"))
  .filter((name) => name.startsWith("workspace.status."))
  .map((name) => ({
    name,
    ...(JSON.parse(readFileSync(resolve(localDir, "fixtures", "valid", name), "utf8")) as {
      data: Record<string, unknown>;
    }),
  }));
const workspaceStatusSchema = JSON.parse(
  readFileSync(resolve(localDir, "schemas", "WorkspaceStatus.json"), "utf8"),
) as { $defs: Record<string, { enum?: string[] }> };

const view: WorkspaceViewModel = {
  workspaceId: "11111111-1111-4111-8111-111111111111",
  projectName: "Jeu Phare",
  folderName: "jeu-phare",
  health: "valid",
  action: "none",
  candidateFolder: null,
  repoCount: 1,
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

describe("toWorkspaceViewModel (derived from the canonical P1 WorkspaceStatus)", () => {
  it("has no silent drift from the P1 health and action vocabularies", () => {
    expect([...WORKSPACE_HEALTHS].sort()).toEqual([...(workspaceStatusSchema.$defs.WorkspaceHealth?.enum ?? [])].sort());
    expect([...WORKSPACE_ACTIONS].sort()).toEqual([...(workspaceStatusSchema.$defs.WorkspaceAction?.enum ?? [])].sort());
  });

  it("derives a view model from every canonical fixture", () => {
    expect(canonicalStatuses.length).toBe(WORKSPACE_HEALTHS.length);
    for (const { name, data } of canonicalStatuses) {
      const model = toWorkspaceViewModel(data);
      expect(model, name).not.toBeNull();
      expect(model?.workspaceId, name).toBe(data.workspace_id);
      expect(model?.health, name).toBe(data.health);
      expect(model?.action, name).toBe(data.action);
    }
  });

  it("reads the project, folder and features of a valid workspace", () => {
    const valid = canonicalStatuses.find(({ data }) => data.health === "valid")!;
    const model = toWorkspaceViewModel(valid.data)!;
    expect(model.projectName).toBe("demo-game");
    expect(model.folderName).toBe("demo-game");
    expect(model.repoCount).toBe(1);
    expect(model.features.find((f) => f.name === "Surveillance")?.on).toBe(true);
    expect(model.watchSummary).not.toBeNull();
  });

  it("proposes the candidate root of a moved workspace", () => {
    const moved = canonicalStatuses.find(({ data }) => data.health === "moved")!;
    expect(toWorkspaceViewModel(moved.data)?.candidateFolder).toBe("D:/Projects/demo-game");
  });

  it("refuses the former camelCase shape", () => {
    expect(
      toWorkspaceViewModel({
        workspaceId: "w",
        projectName: "p",
        folderName: "f",
        health: "valid",
        action: "none",
      }),
    ).toBeNull();
  });

  it("rejects unknown payloads without rendering", () => {
    expect(toWorkspaceViewModel(null)).toBeNull();
    expect(toWorkspaceViewModel([])).toBeNull();
    expect(toWorkspaceViewModel({})).toBeNull();
    expect(toWorkspaceViewModel({ workspace_id: "w", health: "mystery", action: "none" })).toBeNull();
    expect(toWorkspaceViewModel({ workspace_id: "w", health: "valid", action: "explode" })).toBeNull();
    expect(toWorkspaceViewModel({ workspace_id: "w", health: "valid", action: "none", config: "x" })).toBeNull();
  });

  it("never copies secrets or paths from the config into the view", () => {
    const valid = canonicalStatuses.find(({ data }) => data.health === "valid")!;
    const html = workspaceDetailHtml(toWorkspaceViewModel(valid.data)!);
    expect(html).not.toContain("lookup_key");
    expect(html).not.toContain("studio-os.machine");
    expect(html).not.toContain("C:/Work");
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
    expect(html).toContain("Dépôts");
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
