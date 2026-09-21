/**
 * Runtime server origin (Desktop only).
 *
 * The web build reads its API base from `VITE_STUDIO_API_URL` and never sets
 * an override, so its behaviour is unchanged. The Desktop shell sets the user
 * origin it allowed in its CSP at start-up (see `desktopShell.ts`); the value
 * is non-secret and only ever comes from the shell, validated there.
 */
let override: string | null = null;

export function setServerOriginOverride(origin: string | null): void {
  override = origin === null || origin.trim() === "" ? null : origin.trim().replace(/\/+$/, "");
}

export function getServerOriginOverride(): string | null {
  return override;
}
