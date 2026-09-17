import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import { postResolution, resolutionErrorView, winningBindingLevel, type ResolvedAgentDefinition } from "./resolutionApi";

type Fake = Record<"POST", ReturnType<typeof vi.fn>>;
const fakeClient = (impl: Fake): StudioClient => impl as unknown as StudioClient;

const ok = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 200 } as Response,
});
const fail = (status: number, error: unknown): { data?: undefined; error: unknown; response: Response } => ({
  error,
  response: { ok: false, status } as Response,
});

describe("postResolution", () => {
  it("POSTs the canonical request without inventing an Idempotency-Key (pure read)", async () => {
    const POST = vi.fn().mockResolvedValue(ok({ agent: { stable_key: "review-helper" } }));
    await postResolution(fakeClient({ POST }), { stable_key: "review-helper", session_overrides: [] });
    expect(POST).toHaveBeenCalledWith("/api/v1/resolutions", {
      body: { stable_key: "review-helper", session_overrides: [] },
    });
    expect(POST).toHaveBeenCalledTimes(1);
  });

  it("returns the canonical response verbatim", async () => {
    const POST = vi.fn().mockResolvedValue(ok({ agent: { stable_key: "x", version: 4 } }));
    const resolved = await postResolution(fakeClient({ POST }), { stable_key: "x", session_overrides: [] });
    expect(resolved.agent.stable_key).toBe("x");
  });

  it("maps 404 definition_not_found", async () => {
    const POST = vi.fn().mockResolvedValue(fail(404, { detail: { error_code: "definition_not_found" } }));
    await expect(postResolution(fakeClient({ POST }), { stable_key: "nope", session_overrides: [] })).rejects.toMatchObject({
      status: 404,
      errorCode: "definition_not_found",
    });
  });
});

describe("resolutionErrorView", () => {
  it("exposes the structured runtime_incompatible details with no fallback", () => {
    const error = new ApiError(
      parseErrorBody(422, {
        detail: {
          error_code: "runtime_incompatible",
          level: "project_override",
          matched_kind: "agent_definition",
          matched_stable_key: "review-helper",
          unsatisfied: ["capability_x", "tag_y"],
        },
      }),
    );
    const view = resolutionErrorView(error);
    expect(view.code).toBe("runtime_incompatible");
    expect(view.bindingLevel).toBe("project_override");
    expect(view.matchedKind).toBe("agent_definition");
    expect(view.matchedStableKey).toBe("review-helper");
    expect(view.unsatisfied).toEqual(["capability_x", "tag_y"]);
    expect(view.noFallback).toBe(true);
  });

  it("keeps a masked 404 non-oracle", () => {
    const error = new ApiError(parseErrorBody(404, { detail: { error_code: "definition_not_found" } }));
    const view = resolutionErrorView(error);
    expect(view.notFound).toBe(true);
    expect(view.status).toBe(404);
  });

  it("exposes the invalid_resolution_input reason", () => {
    const error = new ApiError(
      parseErrorBody(422, { detail: { error_code: "invalid_resolution_input", reason: "duplicate_session_override" } }),
    );
    const view = resolutionErrorView(error);
    expect(view.code).toBe("invalid_resolution_input");
    expect(view.reason).toBe("duplicate_session_override");
    expect(view.noFallback).toBe(false);
  });

  it("flags auth failures", () => {
    const error = new ApiError(parseErrorBody(403, { detail: { error_code: "forbidden" } }));
    expect(resolutionErrorView(error).isAuth).toBe(true);
  });

  it("degrades gracefully on a non-ApiError", () => {
    const view = resolutionErrorView(new Error("boom"));
    expect(view.status).toBe(0);
    expect(view.code).toBeNull();
    expect(view.message).toBe("boom");
  });
});

describe("winningBindingLevel", () => {
  it("reads the winner from the server response, never computes one", () => {
    const resolved = { runtime: { level: "project_override" } } as unknown as ResolvedAgentDefinition;
    expect(winningBindingLevel(resolved)).toBe("project_override");
  });

  it("returns null when the server selected no runtime", () => {
    expect(winningBindingLevel({ runtime: null } as unknown as ResolvedAgentDefinition)).toBeNull();
  });
});
