/**
 * Canonical HTTP client (DASH-0).
 *
 * Thin wrapper over fetch with generated OpenAPI types (openapi-fetch).
 * - Injects `Authorization: Bearer <token>` from the in-memory store.
 * - Maps HTTP errors to a machine-readable ApiError (status + error_code
 *   when the backend provides one, else the raw detail string).
 * - No business logic lives here: the backend stays the source of truth.
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./openapi-schema";
import { getToken } from "./auth";
import { observedFetch } from "./apiEvents";
import { clientNegotiationHeaders } from "./clientIdentity";
import { getServerOriginOverride } from "./runtimeConfig";

export interface ApiErrorDetails {
  status: number;
  errorCode: string | null;
  message: string;
  /** Present on 409 version_conflict: the live server version to re-read. */
  serverVersion: number | null;
  /** Raw structured `detail` object when the backend sent one (e.g. the
   *  `runtime_incompatible` level/unsatisfied fields). Never a secret. */
  details?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string | null;
  readonly serverVersion: number | null;
  readonly details: unknown;

  constructor(details: ApiErrorDetails) {
    super(details.message);
    this.name = "ApiError";
    this.status = details.status;
    this.errorCode = details.errorCode;
    this.serverVersion = details.serverVersion;
    this.details = details.details ?? null;
  }

  get isAuth(): boolean {
    return this.status === 401 || this.status === 403;
  }
}

const bearer: Middleware = {
  async onRequest({ request }) {
    const token = getToken();
    if (token !== null) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    for (const [name, value] of Object.entries(clientNegotiationHeaders())) {
      request.headers.set(name, value);
    }
    return request;
  },
};

export function parseErrorBody(status: number, body: unknown): ApiErrorDetails {
  const fallback: ApiErrorDetails = { status, errorCode: null, message: `HTTP ${status}`, serverVersion: null };
  if (typeof body === "string") {
    return { ...fallback, message: body === "" ? `HTTP ${status}` : body };
  }
  if (body !== null && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return { ...fallback, message: detail === "" ? `HTTP ${status}` : detail };
    }
    if (detail !== null && typeof detail === "object" && "error_code" in detail) {
      const record = detail as { error_code?: unknown; server_version?: unknown };
      const code = typeof record.error_code === "string" ? record.error_code : null;
      const serverVersion =
        typeof record.server_version === "number" ? record.server_version : null;
      return {
        status,
        errorCode: code,
        serverVersion,
        details: detail,
        message: code !== null ? `${code} (HTTP ${status})` : `HTTP ${status}`,
      };
    }
  }
  return fallback;
}

export type StudioClient = ReturnType<typeof createClient<paths>>;

export function createApiClient(baseUrl: string): StudioClient {
  const client = createClient<paths>({ baseUrl, fetch: observedFetch });
  client.use(bearer);
  return client;
}

/** Base URL for same-origin-or-configured calls (used by the SSE client).
 *  A runtime server origin (Desktop) wins over the build-time value. */
export function apiBaseUrl(): string {
  const runtime = getServerOriginOverride();
  if (runtime !== null) return runtime;
  const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env ?? {};
  return (env["VITE_STUDIO_API_URL"] ?? "").trim().replace(/\/+$/, "");
}

export function requireToken(): string {
  const token = getToken();
  if (token === null)
    throw new ApiError({ status: 401, errorCode: null, message: "missing machine token", serverVersion: null });
  return token;
}
