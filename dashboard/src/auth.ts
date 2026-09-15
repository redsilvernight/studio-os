/**
 * Machine-token session store (DASH-0 auth V0).
 *
 * Rules (TECH/04, DEC-0012):
 * - Bearer <machine-token>, entered manually by an admin/operator.
 * - Kept IN MEMORY only. Never written to localStorage/sessionStorage/
 *   cookies, never logged, never rendered back.
 * - `clearToken()` drops it from the frontend session; server-side
 *   revocation stays `POST /machines/{id}/revoke` (admin).
 */

let token: string | null = null;

export function setToken(value: string): void {
  const trimmed = value.trim();
  token = trimmed === "" ? null : trimmed;
}

export function getToken(): string | null {
  return token;
}

export function clearToken(): void {
  token = null;
}

export function hasToken(): boolean {
  return token !== null;
}
