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

export interface ApiErrorDetails {
  status: number;
  errorCode: string | null;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string | null;

  constructor(details: ApiErrorDetails) {
    super(details.message);
    this.name = "ApiError";
    this.status = details.status;
    this.errorCode = details.errorCode;
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
    return request;
  },
};

export function parseErrorBody(status: number, body: unknown): ApiErrorDetails {
  if (typeof body === "string") {
    return { status, errorCode: null, message: body === "" ? `HTTP ${status}` : body };
  }
  if (body !== null && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return { status, errorCode: null, message: detail === "" ? `HTTP ${status}` : detail };
    }
    if (detail !== null && typeof detail === "object" && "error_code" in detail) {
      const code = (detail as { error_code: unknown }).error_code;
      return {
        status,
        errorCode: typeof code === "string" ? code : null,
        message: typeof code === "string" ? `${code} (HTTP ${status})` : `HTTP ${status}`,
      };
    }
  }
  return { status, errorCode: null, message: `HTTP ${status}` };
}

export type StudioClient = ReturnType<typeof createClient<paths>>;

export function createApiClient(baseUrl: string): StudioClient {
  const client = createClient<paths>({ baseUrl, fetch });
  client.use(bearer);
  return client;
}

/** Base URL for same-origin-or-configured calls (used by the SSE client). */
export function apiBaseUrl(): string {
  const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env ?? {};
  return (env["VITE_STUDIO_API_URL"] ?? "").trim().replace(/\/+$/, "");
}

export function requireToken(): string {
  const token = getToken();
  if (token === null) throw new ApiError({ status: 401, errorCode: null, message: "missing machine token" });
  return token;
}
