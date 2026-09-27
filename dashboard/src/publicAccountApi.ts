/**
 * A5 — Public account flows (A4 / DEC-0109, TECH/02 « Inscription publique
 * et récupération de compte »). No Bearer: these calls run before login.
 *
 * Every failure is reduced to a fixed `AccountErrorKind`; screens show a
 * fixed French message per kind, never the server's text. Responses are
 * non-discriminating by design (202 whether the address exists or not).
 */
import type { StudioClient } from "./api";
import { newUuid } from "./ui";

export type AccountErrorKind =
  | "registration_unavailable"
  | "password_recovery_unavailable"
  | "invalid_or_expired_token"
  | "rate_limited"
  | "invalid_input"
  | "conflict"
  | "network"
  | "server";

export type AccountOutcome = { ok: true } | { ok: false; kind: AccountErrorKind };

function errorCode(body: unknown): string | null {
  if (body === null || typeof body !== "object" || !("detail" in body)) return null;
  const detail = (body as { detail: unknown }).detail;
  if (detail === null || typeof detail !== "object" || !("error_code" in detail)) return null;
  const code = (detail as { error_code: unknown }).error_code;
  return typeof code === "string" ? code : null;
}

export function classifyAccountError(status: number, body: unknown): AccountErrorKind {
  const code = errorCode(body);
  if (code === "registration_unavailable" || code === "password_recovery_unavailable" || code === "invalid_or_expired_token") {
    return code;
  }
  if (status === 429) return "rate_limited";
  if (status === 409) return "conflict";
  if (status === 422) return "invalid_input";
  return "server";
}

/**
 * One Idempotency-Key per logical request: a retry of the same payload (after
 * a network error) replays the same key, a new payload or a reset gets a new one.
 */
export interface IdempotencyKeyer {
  keyFor(payload: string): string;
  reset(): void;
}

export function createIdempotencyKeyer(generate: () => string = newUuid): IdempotencyKeyer {
  let last: { payload: string; key: string } | null = null;
  return {
    keyFor(payload) {
      if (last === null || last.payload !== payload) last = { payload, key: generate() };
      return last.key;
    },
    reset() {
      last = null;
    },
  };
}

async function settle(call: () => Promise<{ error?: unknown; response: Response }>): Promise<AccountOutcome> {
  let result: { error?: unknown; response: Response };
  try {
    result = await call();
  } catch {
    return { ok: false, kind: "network" };
  }
  if (result.response.ok) return { ok: true };
  return { ok: false, kind: classifyAccountError(result.response.status, result.error) };
}

export type EmailFlow = "register" | "resend" | "forgot";

const EMAIL_PATHS = {
  register: "/api/v1/auth/register",
  resend: "/api/v1/auth/resend-verification",
  forgot: "/api/v1/auth/forgot-password",
} as const;

export function requestEmailFlow(client: StudioClient, flow: EmailFlow, email: string, key: string): Promise<AccountOutcome> {
  return settle(() =>
    client.POST(EMAIL_PATHS[flow], {
      params: { header: { "Idempotency-Key": key } },
      body: { email },
    }),
  );
}

export function verifyEmail(
  client: StudioClient,
  input: { token: string; password: string; display_name: string },
): Promise<AccountOutcome> {
  return settle(() => client.POST("/api/v1/auth/verify-email", { body: input }));
}

export function resetPassword(client: StudioClient, input: { token: string; new_password: string }): Promise<AccountOutcome> {
  return settle(() => client.POST("/api/v1/auth/reset-password", { body: input }));
}

/** Server rule (TECH/02): 12 characters minimum, 72 UTF-8 bytes maximum. */
export function passwordProblem(password: string, confirmation: string): string | null {
  if ([...password].length < 12) return "Le mot de passe doit contenir au moins 12 caractères.";
  if (new TextEncoder().encode(password).length > 72) return "Le mot de passe est trop long (72 octets maximum).";
  if (password !== confirmation) return "Les deux mots de passe ne correspondent pas.";
  return null;
}
