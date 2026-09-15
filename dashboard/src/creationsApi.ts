/**
 * DASH-5 — quick-creation wrappers over the existing endpoints.
 *
 * Every replayable creation sends a fresh client-generated `Idempotency-Key`
 * (one per logical attempt, never reused) and the caller refetches afterwards:
 * the server stays the only writer, the dashboard never fabricates a result.
 * - `POST /projects` (admin/developer) — `ProjectCreate`
 * - `POST /tasks` (writer) — `TaskCreate`, server picks the readable id
 * - `POST /decisions` (writer) — `DecisionCreate`; the contract requires a
 *   proposer (`proposed_by_type` + `proposed_by_id`), so the human provides it
 *   (prefilled from the dashboard JWT's `sub` when the token is a JWT).
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import { newIdempotencyKey } from "./claimsApi";
import type { components } from "./openapi-schema";

export type Project = components["schemas"]["Project"];
export type ProjectCreate = components["schemas"]["ProjectCreate"];
export type Task = components["schemas"]["Task"];
export type TaskCreate = components["schemas"]["TaskCreate"];
export type Decision = components["schemas"]["Decision"];
export type DecisionCreate = components["schemas"]["DecisionCreate"];

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export function createProject(
  client: StudioClient,
  input: ProjectCreate,
  key: string = newIdempotencyKey(),
): Promise<Project> {
  return unwrap(
    client.POST("/api/v1/projects", {
      params: { header: { "Idempotency-Key": key } },
      body: input,
    }),
  );
}

export function createTask(
  client: StudioClient,
  input: TaskCreate,
  key: string = newIdempotencyKey(),
): Promise<Task> {
  return unwrap(
    client.POST("/api/v1/tasks", {
      params: { header: { "Idempotency-Key": key } },
      body: input,
    }),
  );
}

export function createDecision(
  client: StudioClient,
  input: DecisionCreate,
  key: string = newIdempotencyKey(),
): Promise<Decision> {
  return unwrap(
    client.POST("/api/v1/decisions", {
      params: { header: { "Idempotency-Key": key } },
      body: input,
    }),
  );
}

function base64UrlDecode(value: string): string | null {
  try {
    const padded = value.replace(/-/g, "+").replace(/_/g, "/");
    const remainder = padded.length % 4;
    const normalised = remainder === 0 ? padded : padded + "=".repeat(4 - remainder);
    return atob(normalised);
  } catch {
    return null;
  }
}

/**
 * Reads the `sub` (user id) claim out of a dashboard JWT without verifying the
 * signature — it is only a form prefill, never an authorization decision
 * (the server re-authenticates every call). Returns null for an opaque machine
 * token, which is not a JWT.
 */
export function decodeJwtSubject(token: string | null): string | null {
  if (token === null || token === "") return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const payload = base64UrlDecode(parts[1] ?? "");
  if (payload === null) return null;
  try {
    const parsed: unknown = JSON.parse(payload);
    if (parsed !== null && typeof parsed === "object" && "sub" in parsed) {
      const sub = (parsed as { sub?: unknown }).sub;
      return typeof sub === "string" && sub !== "" ? sub : null;
    }
    return null;
  } catch {
    return null;
  }
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value.trim());
}
