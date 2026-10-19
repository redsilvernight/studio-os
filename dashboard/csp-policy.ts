/**
 * Dashboard Content-Security-Policy construction (DEC-0061).
 *
 * Single source of truth for the policy served in `vite preview` (Playwright
 * e2e) and mirrored at the Caddy edge (`docker/Caddyfile`). Enforced since
 * the Report-Only exit condition was met: e2e green and zero violation on
 * the production domain (DEC-0061, étape 9.3).
 *
 * Environment-dependent parameters (never hardcoded origins):
 * - `connectExtra`: additional `connect-src` origins — the pre-signed
 *   storage domain (direct MinIO/S3 uploads, DEC-0025) and, only when
 *   `VITE_STUDIO_API_URL` points cross-origin, that API origin. Prod
 *   same-origin deployments need only the storage domain.
 */
export const CSP_HEADER = "Content-Security-Policy";

export interface CspOptions {
  connectExtra?: string[];
}

export function buildDashboardCsp(options: CspOptions = {}): string {
  const connect = ["'self'", ...(options.connectExtra ?? [])].join(" ");
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src ${connect}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
  ].join("; ");
}
