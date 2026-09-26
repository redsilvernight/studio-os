/**
 * Which client family this Dashboard bundle declares to the API (C1).
 *
 * Defaults to `dashboard`; the Desktop shell switches it to `desktop` once it
 * knows it runs inside the Tauri webview. Kept in its own module so `api.ts`
 * can read it without importing the platform adapter (no import cycle).
 */
import { CLIENT_VERSION, type ClientFamily } from "./clientCompatibility";

let family: ClientFamily = "dashboard";

export function setClientFamily(next: ClientFamily): void {
  family = next;
}

export function getClientFamily(): ClientFamily {
  return family;
}

/** The additive negotiation headers sent on every `/api/v1` call. */
export function clientNegotiationHeaders(): Record<string, string> {
  return { "X-Studio-Client": family, "X-Studio-Client-Version": CLIENT_VERSION };
}
