/**
 * C1 compatibility surfaces: a non-blocking advisory banner (a newer client
 * exists, grace window) and a blocking screen when the server refuses this
 * build (426). All text comes from the server's structured detail; nothing is
 * HTML-injected (textContent only, never innerHTML).
 */
import { advisoryText, upgradeRequiredText, type UpgradeInfo } from "./clientCompatibility";

const ADVISORY_ID = "client-update-banner";
const BLOCKING_ID = "client-upgrade-required";

/** Show the advisory banner if present and there is something to say. */
export function showClientUpdateAdvisory(latest: string | null): void {
  const text = advisoryText(latest);
  if (text === null) return;
  const banner = document.getElementById(ADVISORY_ID);
  if (banner === null) return;
  banner.textContent = text;
  banner.hidden = false;
}

export function resetClientUpdateAdvisory(): void {
  const banner = document.getElementById(ADVISORY_ID);
  if (banner === null) return;
  banner.hidden = true;
  banner.textContent = "";
}

/**
 * The server refused this build: show a blocking, non-dismissable screen. It
 * never offers a retry (retrying the same build is pointless) and never claims
 * a code signature — updating is the only way forward.
 */
export function showClientUpgradeRequired(info: UpgradeInfo): void {
  let overlay = document.getElementById(BLOCKING_ID);
  if (overlay === null) {
    overlay = document.createElement("div");
    overlay.id = BLOCKING_ID;
    overlay.className = "ds-overlay client-upgrade-required";
    overlay.setAttribute("role", "alertdialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "client-upgrade-required-title");

    const panel = document.createElement("div");
    panel.className = "ds-overlay-panel client-upgrade-required-panel";

    const title = document.createElement("h1");
    title.id = "client-upgrade-required-title";
    title.textContent = "Mise à jour requise";

    const body = document.createElement("p");
    body.id = "client-upgrade-required-body";

    panel.append(title, body);
    overlay.append(panel);
    document.body.append(overlay);
  }
  const body = overlay.querySelector<HTMLParagraphElement>(`#${BLOCKING_ID}-body`);
  if (body !== null) body.textContent = upgradeRequiredText(info);
  overlay.querySelector<HTMLHeadingElement>(`#${BLOCKING_ID}-title`)?.focus?.();
}
