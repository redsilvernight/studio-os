/**
 * Persistent Desktop session (DEC-0142, TECH/04 « Session persistante »).
 *
 * Only where the platform has an OS secret store (the Desktop); the browser
 * never keeps anything beyond the in-memory JWT.
 * - Sign-in asks for `persistent: true` and keeps the refresh token in the vault.
 * - At start-up a stored token is exchanged for a fresh JWT.
 * - The JWT is renewed shortly before it expires. Rotations are single-flight:
 *   presenting an already consumed token revokes the whole session.
 * - A refused refresh (401) forgets the token; an unreachable server keeps it.
 * - Sign-out revokes the session server-side, then forgets the token.
 */
import { apiBaseUrl } from "./api";
import { observedFetch } from "./apiEvents";
import { setToken } from "./auth";
import { joinUrl } from "./config";
import type { SessionVault } from "./platform/types";

export type RefreshOutcome = "refreshed" | "refused" | "unreachable" | "none";

export interface TokenBody {
  access_token?: unknown;
  expires_in?: unknown;
  refresh_token?: unknown;
}

/** Renew this long before the JWT expires. */
export const RENEW_MARGIN_S = 60;
/** Retry delay when a scheduled renewal could not reach the server. */
export const RETRY_DELAY_S = 30;

let vault: SessionVault | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;
let inflight: Promise<RefreshOutcome> | null = null;

export function configurePersistentSession(next: SessionVault | null): void {
  cancelRenewal();
  inflight = null;
  vault = next;
}

/** True when sign-in should ask for a persistent session. */
export function persistentSessionAvailable(): boolean {
  return vault !== null;
}

export function cancelRenewal(): void {
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

function scheduleRenewal(delayS: number): void {
  cancelRenewal();
  timer = setTimeout(() => {
    timer = null;
    void refreshSession().then((outcome) => {
      if (outcome === "unreachable") scheduleRenewal(RETRY_DELAY_S);
    });
  }, Math.max(delayS, 1) * 1000);
}

function renewalDelay(expiresIn: unknown): number {
  const lifetime = typeof expiresIn === "number" && expiresIn > 0 ? expiresIn : 15 * 60;
  return Math.max(lifetime - RENEW_MARGIN_S, lifetime / 2);
}

/**
 * Adopt a successful `POST /auth/token` or `/auth/refresh` answer: the JWT in
 * memory, the refresh token in the vault, the next renewal scheduled. Returns
 * false when the answer carries no JWT.
 */
export async function acceptTokens(body: TokenBody): Promise<boolean> {
  if (typeof body.access_token !== "string" || body.access_token === "") return false;
  setToken(body.access_token);
  if (vault === null || typeof body.refresh_token !== "string" || body.refresh_token === "") {
    return true;
  }
  // A token that could not be kept must not survive either: the vault would
  // otherwise hold the consumed predecessor, whose replay ends the session.
  if (!(await vault.store(body.refresh_token))) await vault.clear();
  scheduleRenewal(renewalDelay(body.expires_in));
  return true;
}

async function rotate(): Promise<RefreshOutcome> {
  if (vault === null) return "none";
  const secret = await vault.load();
  if (secret === null) return "none";
  let response: Response;
  try {
    response = await observedFetch(joinUrl(apiBaseUrl(), "/api/v1/auth/refresh"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: secret }),
    });
  } catch {
    return "unreachable";
  }
  if (response.status === 401) {
    cancelRenewal();
    await vault.clear();
    return "refused";
  }
  // 429, 5xx, 426: the token was not consumed; keep it for a later attempt.
  if (!response.ok) return "unreachable";
  const body = (await response.json().catch(() => ({}))) as TokenBody;
  return (await acceptTokens(body)) ? "refreshed" : "unreachable";
}

/** Exchange the stored refresh token for a new JWT, one rotation at a time. */
export function refreshSession(): Promise<RefreshOutcome> {
  inflight ??= rotate().finally(() => {
    inflight = null;
  });
  return inflight;
}

/** Start-up: sign in silently from the vault. */
export async function resumeSession(): Promise<boolean> {
  return (await refreshSession()) === "refreshed";
}

/** Sign-out: revoke the session server-side (best effort), then forget it. */
export async function endPersistentSession(): Promise<void> {
  cancelRenewal();
  if (vault === null) return;
  await inflight?.catch(() => undefined);
  const secret = await vault.load();
  await vault.clear();
  if (secret === null) return;
  try {
    await observedFetch(joinUrl(apiBaseUrl(), "/api/v1/auth/logout"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: secret }),
    });
  } catch {
    // Offline sign-out: the token is gone locally and expires server-side.
  }
}
