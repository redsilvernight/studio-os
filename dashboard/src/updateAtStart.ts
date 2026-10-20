import type { Platform } from "./platform/types";
import { installUpdateOnce, resetUpdateInstallerForTests, updateErrorMessage } from "./updateInstaller";

const BANNER_ID = "desktop-update-banner";
export const APPLICATION_SETTINGS_HASH = "#/configuration/application";
type UpdatePlatform = Pick<Platform, "checkForUpdate" | "installUpdate" | "restartDesktop">;

let available: string | null = null;
let updater: UpdatePlatform | null = null;
let phase: "available" | "installing" | "restarting" | "error" = "available";
let failure = "";

export async function checkUpdateAtStart(platform: UpdatePlatform): Promise<void> {
  const result = await platform.checkForUpdate().catch(() => null);
  if (result === null || !result.ok || result.status.state !== "available") return;
  updater = platform;
  available = result.status.version;
  paintUpdateBanner(document);
}

async function install(root: Document): Promise<void> {
  if (updater === null || phase === "installing" || phase === "restarting") return;
  const retry = phase === "error";
  phase = "installing";
  paintUpdateBanner(root);
  if (retry) {
    const checked = await updater.checkForUpdate().catch(() => null);
    if (checked === null || !checked.ok || checked.status.state !== "available") {
      phase = "error";
      failure = checked !== null && !checked.ok
        ? updateErrorMessage(checked.code)
        : "La mise à jour n'a pas pu être retrouvée. Réessayez lorsque le serveur est disponible.";
      paintUpdateBanner(root);
      return;
    }
    available = checked.status.version;
  }
  const result = await installUpdateOnce(updater);
  phase = result.ok ? "restarting" : "error";
  failure = result.ok ? "" : updateErrorMessage(result.code);
  paintUpdateBanner(root);
}

export function paintUpdateBanner(root: Document): void {
  if (available === null) return;
  const banner = root.getElementById(BANNER_ID);
  if (banner === null) return;
  banner.replaceChildren();
  banner.hidden = false;
  banner.setAttribute("aria-busy", String(phase === "installing"));
  const text = root.createElement("span");
  text.textContent = phase === "installing"
    ? `Version ${available} : téléchargement, vérification et installation en cours. L'application redémarrera automatiquement.`
    : phase === "restarting"
      ? `Version ${available} installée. Redémarrage de l'application nécessaire.`
      : phase === "error" ? failure : `Une mise à jour de l'application est disponible (${available}).`;
  if (phase === "error") text.setAttribute("role", "alert");
  banner.append(text, " ");
  if (phase === "installing") {
    const progress = root.createElement("progress");
    progress.setAttribute("aria-label", "Installation de la mise à jour en cours");
    banner.append(progress);
  }
  const button = root.createElement("button");
  button.type = "button";
  button.className = "ds-btn ds-btn--sm";
  button.dataset.testid = "update-install";
  button.disabled = phase === "installing";
  button.textContent = phase === "installing" ? "Installation en cours…"
    : phase === "restarting" ? "Redémarrer l'application"
      : phase === "error" ? "Réessayer l'installation" : "Installer";
  button.addEventListener("click", () => {
    if (phase !== "restarting") {
      void install(root);
      return;
    }
    button.disabled = true;
    void updater?.restartDesktop().then((started) => {
      if (!started) {
        text.textContent = "Fermez puis rouvrez l'application pour utiliser la version installée.";
        button.disabled = false;
      }
    });
  });
  banner.append(button);
}

export function resetUpdateAtStartForTests(): void {
  available = null;
  updater = null;
  phase = "available";
  failure = "";
  resetUpdateInstallerForTests();
}
