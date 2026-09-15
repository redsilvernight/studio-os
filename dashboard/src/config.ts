/**
 * API base-URL resolution (DASH-0).
 *
 * No VPS/localhost/domain is hardcoded in application logic: the base URL
 * comes from `VITE_STUDIO_API_URL` (build/dev time). An empty value means
 * same-origin (relative `/api/v1/...` calls), which is the future
 * Caddy/FastAPI deployment. Local dev against a remote API sets the env var.
 */

export function resolveApiUrl(envValue: string | undefined): string {
  const raw = (envValue ?? "").trim();
  if (raw === "") return "";
  return raw.replace(/\/+$/, "");
}

export function joinUrl(base: string, path: string): string {
  if (base === "") return path;
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}
