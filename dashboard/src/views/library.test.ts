import { describe, expect, it } from "vitest";
import {
  dependenciesTableHtml,
  libraryTabsHtml,
  locksTableHtml,
  resourcesTableHtml,
  shadowNoteHtml,
  versionContentHtml,
  versionsTableHtml,
} from "./library";
import type { LibraryProjectLock, LibraryResource, LibraryVersion } from "../libraryApi";

const resource = (overrides: Partial<LibraryResource>): LibraryResource =>
  ({
    id: "11111111-1111-4111-8111-111111111111",
    kind: "rule",
    stable_key: "coding-standard",
    scope: "studio",
    status: "active",
    active_version: 3,
    owner_user_id: null,
    project_id: null,
    created_by_user_id: null,
    version: 5,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  }) as unknown as LibraryResource;

const version = (content: Record<string, unknown>, overrides: Partial<LibraryVersion> = {}): LibraryVersion =>
  ({
    id: "22222222-2222-4222-8222-222222222222",
    resource_id: "11111111-1111-4111-8111-111111111111",
    version: 3,
    title: "v3",
    description: null,
    content,
    dependencies: [],
    created_by_user_id: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }) as unknown as LibraryVersion;

describe("libraryTabsHtml", () => {
  it("lists the five human kinds and marks the active one", () => {
    const html = libraryTabsHtml("workflows");
    expect(html).toContain(">Rules<");
    expect(html).toContain(">Skills<");
    expect(html).toContain(">Agent Definitions<");
    expect(html).toContain(">Workflows<");
    expect(html).toContain(">Model Profiles<");
    expect(html).toContain('href="#/library/workflows"');
    expect(html).toMatch(/class="tab active" href="#\/library\/workflows"/);
  });
});

describe("shadowNoteHtml", () => {
  it("says nothing when keys are unique per scope", () => {
    expect(shadowNoteHtml([resource({ stable_key: "a" }), resource({ stable_key: "b" })])).toBe("");
  });

  it("warns on same (kind, stable_key) across scopes without deciding a winner", () => {
    const html = shadowNoteHtml([resource({ stable_key: "a", scope: "user" }), resource({ stable_key: "a", scope: "studio" })]);
    expect(html).toContain("more than one scope");
    expect(html).toContain("does not decide which one is effective");
    expect(html).toContain("#/inspector");
  });
});

describe("resourcesTableHtml", () => {
  it("shows scope, active version and status, and links to the detail", () => {
    const html = resourcesTableHtml([resource({ scope: "project", project_id: "p1", active_version: 4, status: "active" })]);
    expect(html).toContain("Project");
    expect(html).toContain("v4");
    expect(html).toContain("Active");
    expect(html).toContain("#/library/rules/11111111-1111-4111-8111-111111111111");
  });

  it("renders an empty state", () => {
    expect(resourcesTableHtml([])).toContain("No resources of this kind");
  });
});

describe("versionsTableHtml", () => {
  it("marks the active version and lists newest first", () => {
    const html = versionsTableHtml(
      [version({}, { version: 2 }), version({}, { version: 3, title: "v3" })],
      3,
    );
    expect(html).toContain("active");
    expect(html.indexOf("v3")).toBeLessThan(html.indexOf("v2"));
  });
});

describe("locksTableHtml", () => {
  it("renders the locked version and a release action", () => {
    const lock = {
      id: "33333333-3333-4333-8333-333333333333",
      project_id: "44444444-4444-4444-8444-444444444444",
      resource_id: "11111111-1111-4111-8111-111111111111",
      locked_version: 2,
      created_by_user_id: null,
      created_at: "2026-01-01T00:00:00Z",
    } as unknown as LibraryProjectLock;
    const html = locksTableHtml([lock]);
    expect(html).toContain("v2");
    expect(html).toContain('data-release-lock="33333333-3333-4333-8333-333333333333"');
  });
});

describe("dependenciesTableHtml", () => {
  it("labels the pinned kind, version and relation", () => {
    const html = dependenciesTableHtml([{ kind: "skill", stable_key: "code-review", version: 5, relation: "uses_skill" }]);
    expect(html).toContain("Skill");
    expect(html).toContain("code-review");
    expect(html).toContain("v5");
    expect(html).toContain("uses skill");
  });
});

describe("versionContentHtml", () => {
  it("renders rule text readably and escaped", () => {
    const html = versionContentHtml("rule", version({ content_schema: "studio.library.rule/v1", text: "<b>be safe</b>" }));
    expect(html).toContain("content_schema: studio.library.rule/v1");
    expect(html).toContain("&lt;b&gt;be safe&lt;/b&gt;");
    expect(html).not.toContain("<b>be safe</b>");
  });

  it("renders model profile requirements", () => {
    const html = versionContentHtml("model_profile", version({ content_schema: "studio.library.model_profile/v1", requirements: { coding: true } }));
    expect(html).toContain("Coding");
  });

  it("renders workflow participants and declared edges", () => {
    const html = versionContentHtml(
      "workflow",
      version({
        content_schema: "studio.library.workflow/v1",
        participants: [
          { participant_id: "implementer", agent_stable_key: "impl", depends_on: [], inputs: [], outputs: [] },
          { participant_id: "tester", agent_stable_key: "test", depends_on: ["implementer"], inputs: [], outputs: [] },
        ],
        inputs: [],
        outputs: [],
      }),
    );
    expect(html).toContain("implementer");
    expect(html).toContain("tester");
    expect(html).toContain("implementer → tester");
    expect(html).toContain("never executes this workflow");
  });

  it("degrades when workflow content is not canonical", () => {
    expect(versionContentHtml("workflow", version({}))).toContain("not in the canonical");
  });
});
