import type { Platform, UpdateErrorCode } from "./platform/types";

const UPDATE_ERRORS: Record<UpdateErrorCode, string> = {
  not_configured: "Les mises à jour ne sont pas activées dans cette version de l'application.",
  network: "Le serveur de mises à jour est injoignable. Vérifiez votre connexion puis réessayez.",
  invalid_metadata: "La réponse du serveur de mises à jour n'est pas exploitable. Rien n'a été modifié.",
  invalid_signature: "La signature de la mise à jour est invalide : elle a été refusée. Rien n'a été modifié.",
  install_failed: "L'installation de la mise à jour a échoué. La version actuelle reste en place.",
  failed: "La mise à jour a échoué. La version actuelle reste en place.",
};

export function updateErrorMessage(code: UpdateErrorCode): string {
  return UPDATE_ERRORS[code];
}

type InstallResult = Awaited<ReturnType<Platform["installUpdate"]>>;
let installation: Promise<InstallResult> | null = null;

export function installUpdateOnce(platform: Pick<Platform, "installUpdate">): Promise<InstallResult> {
  if (installation !== null) return installation;
  installation = Promise.resolve()
    .then(() => platform.installUpdate())
    .catch((): InstallResult => ({ ok: false, code: "failed" }))
    .then((result) => {
      if (!result.ok) installation = null;
      return result;
    });
  return installation;
}

export function resetUpdateInstallerForTests(): void {
  installation = null;
}
