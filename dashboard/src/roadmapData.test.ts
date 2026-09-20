import { describe, expect, it } from "vitest";
import { createFixtureRoadmapDataSource } from "./roadmapData";
import { contractRoadmapDocuments, roadmapFixtureProjectIds } from "./roadmapFixtures";

describe("fixture/session-only roadmap data source", () => {
  it("exposes every documented UI case without an API", async () => {
    const source = createFixtureRoadmapDataSource();
    await expect(source.load(roadmapFixtureProjectIds.noRoadmap)).resolves.toBeNull();
    await expect(source.load(roadmapFixtureProjectIds.empty)).resolves.toMatchObject({ phases: [] });
    await expect(source.load(roadmapFixtureProjectIds.draft)).resolves.toMatchObject({ status: "draft" });
    await expect(source.load(roadmapFixtureProjectIds.proposed)).resolves.toMatchObject({ status: "proposed" });
    await expect(source.load(roadmapFixtureProjectIds.active)).resolves.toMatchObject({ status: "active" });
    await expect(source.load(roadmapFixtureProjectIds.completed)).resolves.toMatchObject({ status: "completed" });
    const blocked = await source.load(roadmapFixtureProjectIds.blocked);
    expect(blocked?.phases?.[0]?.steps?.[0]?.state).toBe("blocked");
    await expect(source.load(roadmapFixtureProjectIds.partial)).resolves.toMatchObject({ title: "Roadmap partielle" });
    const large = await source.load(roadmapFixtureProjectIds.large);
    expect(large?.phases).toHaveLength(30);
    expect(large?.phases?.flatMap((phase) => phase.steps ?? [])).toHaveLength(300);
  });

  it("returns isolated clones", async () => {
    const source = createFixtureRoadmapDataSource();
    const first = await source.load(roadmapFixtureProjectIds.draft);
    if (first === null) throw new Error("fixture missing");
    first.title = "mutated";
    first.phases?.splice(0);
    const second = await source.load(roadmapFixtureProjectIds.draft);
    expect(second?.title).not.toBe("mutated");
    expect(second?.phases?.length).toBeGreaterThan(0);
  });

  it("replaces a document in session after strict validation", async () => {
    const source = createFixtureRoadmapDataSource();
    const document = contractRoadmapDocuments[0];
    if (document === undefined) throw new Error("fixture missing");
    const replaced = await source.replaceDocument("new-project", document);
    expect(replaced).toMatchObject({ project_id: "new-project", title: document.title, status: "draft" });
    expect((await source.load("new-project"))?.phases?.[0]?.steps?.[0]?.linked_tasks).toEqual([]);
    await expect(source.replaceDocument("new-project", { ...document, format: "bad" } as never)).rejects.toThrow(/unsupported format/);
  });

  it("reviews only proposals and requires comments for requested changes", async () => {
    const source = createFixtureRoadmapDataSource();
    await expect(source.reviewProposal(roadmapFixtureProjectIds.proposed, "approve")).resolves.toMatchObject({
      status: "active",
      approved_revision_no: 1,
    });
    await expect(source.reviewProposal(roadmapFixtureProjectIds.draft, "approve")).rejects.toThrow(/proposed/);

    const second = createFixtureRoadmapDataSource();
    await expect(second.reviewProposal(roadmapFixtureProjectIds.proposed, "request_changes")).rejects.toThrow(/comment/);
    await expect(second.reviewProposal(roadmapFixtureProjectIds.proposed, "request_changes", "Clarifier P1")).resolves.toMatchObject({ status: "draft" });

    const third = createFixtureRoadmapDataSource();
    await expect(third.reviewProposal(roadmapFixtureProjectIds.proposed, "reject", "Hors périmètre")).resolves.toMatchObject({ status: "archived" });
    await expect(third.reviewProposal(roadmapFixtureProjectIds.noRoadmap, "approve")).resolves.toBeNull();
  });
});
