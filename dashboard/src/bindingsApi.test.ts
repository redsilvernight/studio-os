import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import {
  createRuntimeBinding,
  deleteRuntimeBinding,
  getRuntimeBinding,
  listRuntimeBindings,
  STORED_RUNTIME_LEVELS,
} from "./bindingsApi";

type Fake = Record<"GET" | "POST" | "DELETE", ReturnType<typeof vi.fn>>;
const fakeClient = (impl: Fake): StudioClient => impl as unknown as StudioClient;
const emptyFake = (): Fake => ({ GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn() });

const ok = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 200 } as Response,
});
const created = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 201 } as Response,
});
const fail = (status: number, error: unknown): { data?: undefined; error: unknown; response: Response } => ({
  error,
  response: { ok: false, status } as Response,
});

describe("STORED_RUNTIME_LEVELS", () => {
  it("never offers the ephemeral session level for storage", () => {
    expect(STORED_RUNTIME_LEVELS).toEqual(["user", "project_override", "project_default", "studio_default"]);
    expect(STORED_RUNTIME_LEVELS).not.toContain("session");
  });
});

describe("listRuntimeBindings", () => {
  it("sends level/project/kind/stable_key filters", async () => {
    const GET = vi.fn().mockResolvedValue(ok([]));
    await listRuntimeBindings(fakeClient({ ...emptyFake(), GET }), {
      level: "project_override",
      projectId: "p1",
      kind: "agent_definition",
      stableKey: "review-helper",
    });
    expect(GET).toHaveBeenCalledWith("/api/v1/runtime-bindings", {
      params: {
        query: { level: "project_override", project_id: "p1", kind: "agent_definition", stable_key: "review-helper" },
      },
    });
  });
});

describe("createRuntimeBinding", () => {
  it("posts the level + logical key + target with an Idempotency-Key", async () => {
    const POST = vi.fn().mockResolvedValue(created({ id: "b1" }));
    const body = {
      level: "user" as const,
      project_id: null,
      target_kind: "agent_definition" as const,
      target_stable_key: "review-helper",
      target: { runtime_id: "rt1", capabilities: { coding: false, tools: [], local: false } },
    };
    await createRuntimeBinding(fakeClient({ ...emptyFake(), POST }), body, "k1");
    expect(POST).toHaveBeenCalledWith("/api/v1/runtime-bindings", {
      params: { header: { "Idempotency-Key": "k1" } },
      body,
    });
  });

  it("surfaces already_bound 409", async () => {
    const POST = vi.fn().mockResolvedValue(fail(409, { detail: { error_code: "already_bound" } }));
    await expect(
      createRuntimeBinding(fakeClient({ ...emptyFake(), POST }), {
        level: "user",
        project_id: null,
        target_kind: "model_profile",
        target_stable_key: "p",
        target: { runtime_id: "rt1", capabilities: { coding: false, tools: [], local: false } },
      }),
    ).rejects.toMatchObject({ errorCode: "already_bound" });
  });
});

describe("getRuntimeBinding / deleteRuntimeBinding", () => {
  it("reads and releases a binding by id", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ id: "b1" }));
    await getRuntimeBinding(fakeClient({ ...emptyFake(), GET }), "b1");
    expect(GET).toHaveBeenCalledWith("/api/v1/runtime-bindings/{binding_id}", { params: { path: { binding_id: "b1" } } });

    const DELETE = vi.fn().mockResolvedValue(ok({ id: "b1" }));
    await deleteRuntimeBinding(fakeClient({ ...emptyFake(), DELETE }), "b1");
    expect(DELETE).toHaveBeenCalledWith("/api/v1/runtime-bindings/{binding_id}", {
      params: { path: { binding_id: "b1" } },
    });
  });
});
