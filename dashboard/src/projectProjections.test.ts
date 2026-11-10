import { describe, expect, it } from "vitest";
import { projectProjectionsHtml } from "./projectProjections";
import type { ProjectProjectionsStatus } from "./projectProjections";

const WORKSPACE = "11111111-1111-4111-8111-111111111111";

const status = (): ProjectProjectionsStatus => ({
  updates: [
    {
      workspace_id: WORKSPACE,
      project_id: "22222222-2222-4222-8222-222222222222",
      checked_at: "2026-11-10T10:00:00Z",
      files: [{ path: ".claude/rules/<b>.md", state: "absent" }, { path: "AGENTS.md", state: "obsolete" }],
    },
  ],
});

describe("project projections section", () => {
  it("renders nothing when no repository is pending", () => {
    expect(projectProjectionsHtml(null, false)).toBe("");
    expect(projectProjectionsHtml({ updates: [] }, false)).toBe("");
  });

  it("asks for confirmation per repository and escapes file names", () => {
    const html = projectProjectionsHtml(status(), false);
    expect(html).toContain(`data-project-projections-apply="${WORKSPACE}"`);
    expect(html).toContain("Confirmer l'écriture dans le dépôt");
    expect(html).toContain("2 fichier(s)");
    expect(html).toContain("&lt;b&gt;");
    expect(html).not.toContain("<b>");
  });

  it("disables the confirmation while an operation runs", () => {
    expect(projectProjectionsHtml(status(), true)).toContain(" disabled");
  });
});
