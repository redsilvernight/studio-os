import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import { resolveReview } from "./reviewApi";

const fakeClient = (PATCH: ReturnType<typeof vi.fn>): StudioClient => ({ PATCH } as unknown as StudioClient);

const ok = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 200 } as Response,
});

describe("resolveReview", () => {
  it("PATCHes the ai-work entry with the resolution status", async () => {
    const PATCH = vi.fn().mockResolvedValue(ok({ id: "w1", status: "approved" }));
    await resolveReview(fakeClient(PATCH), "w1", "approved");
    expect(PATCH).toHaveBeenCalledWith("/api/v1/ai-work/{work_id}", {
      params: { path: { work_id: "w1" } },
      body: { status: "approved" },
    });
  });

  it("surfaces 403 for a non-admin (server rule, never pre-judged)", async () => {
    const PATCH = vi.fn().mockResolvedValue({
      error: { detail: { error_code: "forbidden" } },
      response: { ok: false, status: 403 } as Response,
    });
    await expect(resolveReview(fakeClient(PATCH), "w1", "changes_requested")).rejects.toMatchObject({
      status: 403,
      errorCode: "forbidden",
    });
  });
});
