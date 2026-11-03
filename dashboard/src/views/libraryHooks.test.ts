import { describe, expect, it } from "vitest";
import { kindFromSlug, libraryKindHref } from "../libraryFormat";
import { parseRoute } from "../router";
import type { LibraryVersion } from "../libraryApi";
import { libraryRootHtml, versionContentHtml } from "./library";

const hook = (content: Record<string, unknown>): LibraryVersion => ({
  id: "v1", resource_id: "h1", version: 1, title: "Hook",
  description: null, content, dependencies: [], created_by_user_id: null,
  created_at: "2026-10-11T10:00:00Z",
});

const content = {
  content_schema: "studio.library.hook/v1", event: "pre_tool", matcher: "Read",
  mode: "advisory", timeout_seconds: 30, description: "Vérifie les outils",
  scripts: [{ os: "windows", shell: "pwsh", body: "Write-Output 'ok'" }, { os: "linux", shell: "bash", body: "echo ok" }],
};

describe("Bibliothèque Hooks", () => {
  it("ouvre les listes et détails depuis le sixième type", () => {
    expect(kindFromSlug("hooks")?.kind).toBe("hook");
    expect(libraryKindHref("hook", "h1")).toBe("#/library/hooks/h1");
    expect(parseRoute("#/library/hooks")).toEqual({ name: "library", kind: "hooks" });
    expect(parseRoute("#/library/hooks/h1")).toEqual({ name: "libraryDetail", kind: "hooks", id: "h1" });
    expect(libraryRootHtml()).toContain('href="#/library/hooks"');
  });

  it("présente toutes les variantes de script dans le détail", () => {
    const html = versionContentHtml("hook", hook(content));
    for (const value of ["pre_tool", "Read", "30", "windows", "pwsh", "linux", "bash", "echo ok"]) {
      expect(html).toContain(value);
    }
    expect(html).toContain("Vérifie les outils");
    expect(html).not.toContain("studio.library.workflow/v1");
  });

  it("échappe le contenu exécutable et les métadonnées", () => {
    const html = versionContentHtml("hook", hook({
      ...content, matcher: '<img src=x onerror="alert(1)">',
      description: "<script>alert(2)</script>",
      scripts: [{ os: "any", shell: "node", body: "<script>alert(3)</script>" }],
    }));
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;script&gt;alert(3)&lt;/script&gt;");
    expect(html).toContain("&lt;img");
  });

  it("tolère les champs optionnels absents et signale un schéma erroné", () => {
    const { matcher: _matcher, description: _description, ...minimal } = content;
    expect(versionContentHtml("hook", hook(minimal))).not.toContain("undefined");
    expect(versionContentHtml("hook", hook({ content_schema: "wrong" }))).toContain("Contenu non canonique");
  });

  it("présente les valeurs par défaut du contrat quand elles sont omises", () => {
    const html = versionContentHtml("hook", hook({ content_schema: "studio.library.hook/v1", event: "session_start", scripts: [{ shell: "pwsh", body: "Write-Output 'ok'" }] }));
    expect(html).toContain("advisory");
    expect(html).toContain("30 secondes");
    expect(html).toContain("Script any");
    expect(html).toContain("Aucun filtre");
  });
});
