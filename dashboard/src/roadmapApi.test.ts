import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import {
  createApiRoadmapDataSource,
  toApiDocument,
  toViewRoadmap,
} from "./roadmapApi";
import type { RoadmapDocument } from "./roadmapTypes";

type Fake = Record<"GET" | "POST", ReturnType<typeof vi.fn>>;
const fakeClient = (impl: Fake): StudioClient => impl as unknown as StudioClient;
const emptyFake = (): Fake => ({ GET: vi.fn(), POST: vi.fn() });

const ok = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 200 } as Response,
});
const fail = (
  status: number,
  error: unknown,
): { data?: undefined; error: unknown; response: Response } => ({
  error,
  response: { ok: false, status } as Response,
});

const SUMMARY = {
  id: "r1",
  project_id: "p1",
  title: "Plan",
  status: "active",
  revision_no: 2,
  approved_revision_no: 1,
  progress: { done: 1, total: 2, skipped: 0, ratio: 0.5 },
  current_step_key: "P0.1",
};

const DETAIL = {
  ...SUMMARY,
  version: 7,
  phases: [
    {
      id: "ph1",
      roadmap_id: "r1",
      key: "P0",
      position: 0,
      title: "Phase",
      progress: { done: 1, total: 2, skipped: 0, ratio: 0.5 },
      steps: [
        {
          id: "st1",
          roadmap_id: "r1",
          phase_id: "ph1",
          key: "P0.1",
          position: 0,
          title: "Step",
          state: "done",
          available: true,
        },
      ],
    },
  ],
};

const DOCUMENT: RoadmapDocument = {
  format: "studio.roadmap/v1",
  title: "Plan",
  objective: null,
  context: null,
  metadata: {},
  phases: [
    {
      key: "P0",
      title: "Phase",
      objective: null,
      steps: [
        {
          key: "P0.1",
          title: "Step",
          objective: null,
          context: null,
          instructions: null,
          acceptance_criteria: ["ok"],
          notes: null,
          metadata: {},
          depends_on: [],
          tasks: [],
        },
      ],
    },
  ],
  exported_at: null,
  revision_no: null,
};

describe("toViewRoadmap", () => {
  it("maps the canonical detail onto the dashboard view model", () => {
    const view = toViewRoadmap(DETAIL as never);
    expect(view.id).toBe("r1");
    expect(view.status).toBe("active");
    expect(view.phases?.[0]?.steps?.[0]).toMatchObject({ key: "P0.1", state: "done" });
  });
});

describe("toApiDocument", () => {
  it("keeps the neutral format without ids or status", () => {
    const api = toApiDocument(DOCUMENT);
    expect(api).toMatchObject({ format: "studio.roadmap/v1", title: "Plan" });
    expect(api).not.toHaveProperty("id");
    expect(api).not.toHaveProperty("status");
  });
});

describe("createApiRoadmapDataSource.load", () => {
  it("answers null when the project has no roadmap", async () => {
    const GET = vi.fn().mockResolvedValue(ok([]));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET }));
    await expect(source.load("p1")).resolves.toBeNull();
    expect(GET).toHaveBeenCalledWith("/api/v1/projects/{project_id}/roadmaps", {
      params: { path: { project_id: "p1" } },
    });
  });

  it("prefers the active roadmap then reads its detail", async () => {
    const GET = vi
      .fn()
      .mockResolvedValueOnce(ok([{ ...SUMMARY, id: "draft-1", status: "draft" }, SUMMARY]))
      .mockResolvedValueOnce(ok(DETAIL));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET }));
    const roadmap = await source.load("p1");
    expect(roadmap?.id).toBe("r1");
    expect(GET).toHaveBeenCalledWith("/api/v1/roadmaps/{roadmap_id}", {
      params: { path: { roadmap_id: "r1" } },
    });
  });

  it("surfaces API errors instead of inventing state", async () => {
    const GET = vi.fn().mockResolvedValue(fail(404, { detail: { error_code: "not_found" } }));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET }));
    await expect(source.load("missing")).rejects.toThrow();
  });
});

describe("createApiRoadmapDataSource.replaceDocument", () => {
  it("imports the document as a draft with an idempotency key", async () => {
    const POST = vi.fn().mockResolvedValue({ data: DETAIL, response: { ok: true, status: 201 } as Response });
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), POST }));
    const roadmap = await source.replaceDocument("p1", DOCUMENT);
    expect(roadmap.status).toBe("active");
    expect(POST).toHaveBeenCalledWith(
      "/api/v1/roadmaps/import",
      expect.objectContaining({
        body: expect.objectContaining({ project_id: "p1", submit: false }),
      }),
    );
    const header = (POST.mock.calls[0] as [string, { params: { header: Record<string, string> } }])[1]
      .params.header["Idempotency-Key"];
    expect(typeof header).toBe("string");
  });

  it("refuses an invalid document before any call", async () => {
    const POST = vi.fn();
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), POST }));
    await expect(source.replaceDocument("p1", { format: "nope" } as never)).rejects.toThrow();
    expect(POST).not.toHaveBeenCalled();
  });
});

const REVISION = {
  id: "rev3",
  roadmap_id: "r1",
  revision_no: 3,
  kind: "proposal",
  status: "pending",
  base_revision_no: 1,
  summary: "Clarifier",
  provenance: {
    origin: "ai_proposal",
    actor_type: "agent",
    actor_id: "a1",
    agent_id: "a1",
    machine_id: "m1",
    at: "2026-01-01T00:00:00+00:00",
  },
  reviewed_by_user_id: null,
  reviewed_at: null,
  review_comment: null,
};

const DIFF = {
  base_revision_no: 1,
  proposal_revision_no: 3,
  entries: [{ scope: "step", key: "P0.1", change: "changed", fields: ["title"] }],
};

describe("createApiRoadmapDataSource.loadPendingProposal", () => {
  it("answers null without an active roadmap", async () => {
    const GET = vi.fn().mockResolvedValue(ok([{ ...SUMMARY, status: "draft" }]));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET }));
    await expect(source.loadPendingProposal("p1")).resolves.toBeNull();
    expect(GET).toHaveBeenCalledTimes(1);
  });

  it("reads the pending revision and its diff by key", async () => {
    const GET = vi
      .fn()
      .mockResolvedValueOnce(ok([SUMMARY]))
      .mockResolvedValueOnce(ok([REVISION]))
      .mockResolvedValueOnce(ok(DETAIL))
      .mockResolvedValueOnce(ok(DIFF));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET }));
    const proposal = await source.loadPendingProposal("p1");
    expect(proposal?.revision.revision_no).toBe(3);
    expect(proposal?.roadmapVersion).toBe(7);
    expect(proposal?.diff.entries[0]).toMatchObject({ key: "P0.1", change: "changed" });
    expect(GET).toHaveBeenCalledWith("/api/v1/roadmaps/{roadmap_id}/revisions", {
      params: { path: { roadmap_id: "r1" }, query: { kind: "proposal", status: "pending" } },
    });
    expect(GET).toHaveBeenCalledWith(
      "/api/v1/roadmaps/{roadmap_id}/proposals/{revision_no}/diff",
      { params: { path: { roadmap_id: "r1", revision_no: 3 } } },
    );
  });
});

describe("createApiRoadmapDataSource.reviewProposalRevision", () => {
  it("reviews with the roadmap version just read", async () => {
    const GET = vi.fn().mockResolvedValueOnce(ok([SUMMARY])).mockResolvedValueOnce(ok(DETAIL));
    const POST = vi
      .fn()
      .mockResolvedValue(ok({ ...DETAIL, revision_no: 3, approved_revision_no: 3 }));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET, POST }));
    const roadmap = await source.reviewProposalRevision("p1", 3, "approve");
    expect(roadmap?.approved_revision_no).toBe(3);
    expect(POST).toHaveBeenCalledWith(
      "/api/v1/roadmaps/{roadmap_id}/proposals/{revision_no}/review",
      expect.objectContaining({
        params: { path: { roadmap_id: "r1", revision_no: 3 } },
        body: expect.objectContaining({ decision: "approve", expected_version: 7 }),
      }),
    );
  });

  it("passes the comment through and answers null without an active roadmap", async () => {
    const GET = vi.fn().mockResolvedValue(ok([{ ...SUMMARY, status: "draft" }]));
    const POST = vi.fn();
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET, POST }));
    await expect(source.reviewProposalRevision("p1", 3, "reject", "Hors périmètre")).resolves.toBeNull();
    expect(POST).not.toHaveBeenCalled();
  });
});

describe("createApiRoadmapDataSource.reviewProposal", () => {
  it("answers null when nothing is proposed", async () => {
    const GET = vi.fn().mockResolvedValue(ok([SUMMARY]));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET }));
    await expect(source.reviewProposal("p1", "approve")).resolves.toBeNull();
  });

  it("reviews with the version just read", async () => {
    const proposed = { ...SUMMARY, id: "r9", status: "proposed" };
    const GET = vi.fn().mockResolvedValueOnce(ok([proposed])).mockResolvedValueOnce(ok({ ...DETAIL, id: "r9" }));
    const POST = vi.fn().mockResolvedValue(ok({ ...DETAIL, id: "r9", status: "active" }));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET, POST }));
    const roadmap = await source.reviewProposal("p1", "approve");
    expect(roadmap?.status).toBe("active");
    expect(POST).toHaveBeenCalledWith(
      "/api/v1/roadmaps/{roadmap_id}/transitions",
      expect.objectContaining({
        body: expect.objectContaining({ transition: "approve", expected_version: 7 }),
      }),
    );
  });
});

describe("createApiRoadmapDataSource.transitionRoadmap", () => {
  it("sends the lifecycle transition with the version held by the view", async () => {
    const GET = vi.fn();
    const POST = vi.fn().mockResolvedValue(ok({ ...DETAIL, status: "active", version: 8 }));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET, POST }));
    const view = toViewRoadmap({ ...DETAIL, status: "completed", version: 7 } as never);
    const roadmap = await source.transitionRoadmap(view, "reopen", "Étape oubliée");
    expect(roadmap.status).toBe("active");
    expect(GET).not.toHaveBeenCalled();
    expect(POST).toHaveBeenCalledWith("/api/v1/roadmaps/{roadmap_id}/transitions", {
      params: { path: { roadmap_id: "r1" } },
      body: { transition: "reopen", expected_version: 7, comment: "Étape oubliée" },
    });
  });

  it("keeps a 409 structured for the view", async () => {
    const POST = vi.fn().mockResolvedValue(fail(409, { detail: { error_code: "invalid_state" } }));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), POST }));
    const view = toViewRoadmap({ ...DETAIL, version: 7 } as never);
    await expect(source.transitionRoadmap(view, "complete")).rejects.toMatchObject({ errorCode: "invalid_state" });
  });
});

describe("createApiRoadmapDataSource with a targeted roadmap", () => {
  const PROPOSED = { ...SUMMARY, id: "r9", title: "Bootstrap", status: "proposed" };

  it("loads the requested proposed roadmap instead of the active one", async () => {
    const GET = vi
      .fn()
      .mockResolvedValueOnce(ok([SUMMARY, PROPOSED]))
      .mockResolvedValueOnce(ok({ ...DETAIL, id: "r9", status: "proposed" }));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET }));
    const roadmap = await source.load("p1", "r9");
    expect(roadmap?.id).toBe("r9");
    expect(GET).toHaveBeenLastCalledWith("/api/v1/roadmaps/{roadmap_id}", {
      params: { path: { roadmap_id: "r9" } },
    });
  });

  it("ignores an id that is not a roadmap of the project", async () => {
    const GET = vi.fn().mockResolvedValueOnce(ok([SUMMARY, PROPOSED])).mockResolvedValueOnce(ok(DETAIL));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET }));
    const roadmap = await source.load("p1", "foreign");
    expect(roadmap?.id).toBe("r1");
  });

  it("lists every roadmap for the switcher", async () => {
    const GET = vi.fn().mockResolvedValue(ok([SUMMARY, PROPOSED]));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET }));
    await expect(source.listRoadmaps?.("p1")).resolves.toEqual([
      { id: "r1", title: "Plan", status: "active" },
      { id: "r9", title: "Bootstrap", status: "proposed" },
    ]);
  });

  it("reads a pending revision only on the displayed roadmap, never on another one", async () => {
    const GET = vi.fn().mockResolvedValue(ok([SUMMARY, PROPOSED]));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET }));
    await expect(source.loadPendingProposal("p1", "r9")).resolves.toBeNull();
    expect(GET).toHaveBeenCalledTimes(1);
  });

  it("reviews the displayed proposed roadmap, not the first proposed one", async () => {
    const other = { ...PROPOSED, id: "r8" };
    const GET = vi
      .fn()
      .mockResolvedValueOnce(ok([SUMMARY, other, PROPOSED]))
      .mockResolvedValueOnce(ok({ ...DETAIL, id: "r9" }));
    const POST = vi.fn().mockResolvedValue(ok({ ...DETAIL, id: "r9", status: "active" }));
    const source = createApiRoadmapDataSource(fakeClient({ ...emptyFake(), GET, POST }));
    await source.reviewProposal("p1", "approve", undefined, "r9");
    expect(POST).toHaveBeenCalledWith(
      "/api/v1/roadmaps/{roadmap_id}/transitions",
      expect.objectContaining({ params: { path: { roadmap_id: "r9" } } }),
    );
  });
});
