import { describe, expect, it } from "vitest";
import type { WorkspaceStatus } from "../platform/generated/local-contracts.generated";
import { findLinkedWorkspace } from "./api";

const item = (workspace_id: string, project_id: string, workspace_root: string): WorkspaceStatus =>
  ({ workspace_id, health: "valid", config: { workspace_id, project_id, roots: { workspace_root, repo_roots: [] } } }) as unknown as WorkspaceStatus;

describe("findLinkedWorkspace", () => {
  const items = [item("a", "p1", "C:\\Projets\\Demo"), item("b", "p2", "C:\\Autre")];

  it("retrouve l'association du même dossier pour le même projet, quelle que soit la casse ou le séparateur", () => {
    expect(findLinkedWorkspace(items, "p1", "c:/projets/demo/")?.workspace_id).toBe("a");
  });

  it("ignore un autre projet ou un autre dossier", () => {
    expect(findLinkedWorkspace(items, "p2", "C:\\Projets\\Demo")).toBeUndefined();
    expect(findLinkedWorkspace(items, "p1", "C:\\Projets\\Demo2")).toBeUndefined();
  });
});
