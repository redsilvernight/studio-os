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
