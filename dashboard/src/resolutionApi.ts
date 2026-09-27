/**
 * P12 — canonical Resolution client (P7/DEC-0071, P5/DEC-0069).
 *
 * The dashboard has exactly one way to learn "what would Studi'OS use": call
 * `POST /resolutions` and render the canonical `ResolvedAgentDefinition`. This
 * module adds no precedence, no runtime selection and no compatibility check —
 * only transport plus a read-only view of the server's structured failure.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";
import type { LibraryKind, RuntimeLevel } from "./libraryFormat";

export type AgentResolutionRequest = components["schemas"]["AgentResolutionRequest"];
export type SessionRuntimeOverride = components["schemas"]["SessionRuntimeOverride"];
export type ResolvedAgentDefinition = components["schemas"]["ResolvedAgentDefinition"];
export type ResolvedAgent = components["schemas"]["ResolvedAgent"];
export type ResolvedRule = components["schemas"]["ResolvedRule"];
export type ResolvedSkill = components["schemas"]["ResolvedSkill"];
export type ResolvedModelProfile = components["schemas"]["ResolvedModelProfile"];
export type ResolvedRuntime = components["schemas"]["ResolvedRuntime"];
export type PreservedReference = components["schemas"]["PreservedReference"];

/** Pure read — safe to retry, no `Idempotency-Key` (DEC-0071 §5). */
export function postResolution(
  client: StudioClient,
  input: AgentResolutionRequest,
): Promise<ResolvedAgentDefinition> {
  return client.POST("/api/v1/resolutions", { body: input }).then((result) => {
    if (result.response.ok && result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  });
}

export interface ResolutionErrorView {
  status: number;
  code: string | null;
  message: string;
  reason: string | null;
  bindingLevel: RuntimeLevel | null;
  matchedKind: LibraryKind | null;
  matchedStableKey: string | null;
  unsatisfied: string[];
  /** P5 guarantees a structured failure rather than a fallback to a lower
   *  binding — the UI states this explicitly. */
  noFallback: boolean;
  isAuth: boolean;
  /** 403: valid session, refused right (never shown as an auth error). */
  forbidden: boolean;
  /** 403 from project isolation (no access to the project). */
  projectAccessDenied: boolean;
  notFound: boolean;
}

function recordOf(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function stringField(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  return typeof value === "string" ? value : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/** Read-only view of a canonical resolution failure, from `ApiError.details`. */
export function resolutionErrorView(error: unknown): ResolutionErrorView {
  if (error instanceof ApiError) {
    const details = recordOf(error.details);
    const code = error.errorCode;
    return {
      status: error.status,
      code,
      message: error.message,
      reason: stringField(details, "reason"),
      bindingLevel: stringField(details, "level") as RuntimeLevel | null,
      matchedKind: stringField(details, "matched_kind") as LibraryKind | null,
      matchedStableKey: stringField(details, "matched_stable_key"),
      unsatisfied: stringList(details["unsatisfied"]),
      noFallback: code === "runtime_incompatible",
      isAuth: error.isAuth,
      forbidden: error.isForbidden,
      projectAccessDenied: error.isProjectAccessDenied,
      notFound: error.status === 404,
    };
  }
  return {
    status: 0,
    code: null,
    message: error instanceof Error ? error.message : String(error),
    reason: null,
    bindingLevel: null,
    matchedKind: null,
    matchedStableKey: null,
    unsatisfied: [],
    noFallback: false,
    isAuth: false,
    forbidden: false,
    projectAccessDenied: false,
    notFound: false,
  };
}

/** The binding level the server reports as the winner, or `null` (no binding). */
export function winningBindingLevel(resolved: ResolvedAgentDefinition): RuntimeLevel | null {
  return resolved.runtime?.level ?? null;
}
