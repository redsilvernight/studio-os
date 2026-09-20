/**
 * Paramètres › Application — identité de l'application.
 *
 * Affiche seulement ce que le runtime courant sait de lui-même : produit,
 * version Desktop, mode (web ou desktop) et version du protocole local.
 * En mode web, aucune disponibilité Desktop n'est simulée. Ce n'est pas le
 * panneau de diagnostic (P3) : aucun état de daemon ni de secret ici.
 */
import { getPlatform, type DesktopInfo, type Platform } from "../platform";
import { esc } from "../ui";
import { dsPageHeader } from "../ds/ds";
import { configTabsHtml } from "./configuration";
import "./configuration.css";

const DESCRIPTION = "Identité et version de l'application qui exécute ce tableau de bord.";

function row(label: string, value: string): string {
  return `<div class="settings-ref"><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
}

export function applicationPageHtml(mode: "web" | "desktop", info: DesktopInfo | null, failure?: string): string {
  const head = `${dsPageHeader("Paramètres", DESCRIPTION)}${configTabsHtml("application")}`;
  let body: string;
  if (mode === "desktop" && info) {
    body =
      `<dl class="settings-refs" data-testid="application-identity">` +
      row("Application", esc(info.product)) +
      row("Version Desktop", `<code class="mono">${esc(info.desktop_version)}</code>`) +
      row("Mode", "Desktop") +
      row("Protocole local", `<code class="mono">${esc(info.protocol)}</code>`) +
      `</dl>`;
  } else if (mode === "desktop") {
    body =
      `<div class="state error" role="alert" data-testid="application-error">` +
      `Impossible de lire l'identité Desktop${failure ? ` : ${esc(failure)}` : ""}.</div>`;
  } else {
    body =
      `<dl class="settings-refs" data-testid="application-identity">` +
      row("Application", "Studi'OS Dashboard") +
      row("Mode", "Web") +
      `</dl>` +
      `<p class="settings-intro">Application Desktop non utilisée : ce tableau de bord s'exécute dans un navigateur.</p>`;
  }
  return `<div class="settings">${head}<section class="settings-domain"><h2>Application</h2>${body}</section></div>`;
}

export async function renderApplication(root: HTMLElement, platform: Platform = getPlatform()): Promise<void> {
  if (platform.mode === "web") {
    root.innerHTML = applicationPageHtml("web", null);
    return;
  }
  try {
    const info = await platform.desktopInfo();
    root.innerHTML = applicationPageHtml("desktop", info);
  } catch (error) {
    root.innerHTML = applicationPageHtml("desktop", null, error instanceof Error ? error.message : undefined);
  }
}
