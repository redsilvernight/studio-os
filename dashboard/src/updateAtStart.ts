/**
 * Desktop: one update check at start-up, announced by a non-blocking banner
 * that leads to Réglages › Application. Nothing is downloaded or installed
 * here; installing stays an explicit gesture on that page. Offline, not
 * configured or up to date: silence.
 */
import type { Platform } from "./platform/types";

const BANNER_ID = "client-update-banner";
export const APPLICATION_SETTINGS_HASH = "#/configuration/application";

let available: string | null = null;

export async function checkUpdateAtStart(platform: Pick<Platform, "checkForUpdate">): Promise<void> {
  const result = await platform.checkForUpdate().catch(() => null);
  if (result === null || !result.ok || result.status.state !== "available") return;
  available = result.status.version;
  paintUpdateBanner(document);
}

/** Show the banner in a freshly mounted shell when an update was found. */
export function paintUpdateBanner(root: Document): void {
  if (available === null) return;
  const banner = root.getElementById(BANNER_ID);
  if (banner === null) return;
  const link = root.createElement("a");
  link.href = APPLICATION_SETTINGS_HASH;
  link.textContent = "Installer depuis Réglages › Application";
  link.dataset.testid = "update-available-link";
  banner.replaceChildren(`Une mise à jour de l'application est disponible (${available}). `, link);
  banner.hidden = false;
}

export function resetUpdateAtStartForTests(): void {
  available = null;
}
