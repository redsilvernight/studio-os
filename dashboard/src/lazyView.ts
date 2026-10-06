/**
 * Chargement différé des vues (task d5c1183f).
 *
 * Seul le shell, le routeur et l'écran de connexion sont dans le chunk
 * d'entrée ; chaque route importe sa vue à la demande. Un chunk qui ne se
 * charge pas (réseau coupé, déploiement qui a remplacé les fichiers hachés)
 * ne doit ni laisser une page blanche ni échouer silencieusement : on peint
 * un état d'erreur explicite, annoncé comme alerte. L'action est un
 * rechargement de la page (hash conservé, donc deep link préservé) : le
 * navigateur mémorise l'échec d'un `import()` pour une même URL, un simple
 * re-rendu rejouerait la même erreur ; le rechargement couvre aussi le
 * déploiement qui a remplacé les fichiers hachés.
 */
import { dsPageHeader, dsStateHtml } from "./ds/ds";

export class ViewLoadError extends Error {
  constructor(cause: unknown) {
    super("Impossible de charger cette page.", { cause });
    this.name = "ViewLoadError";
  }
}

/** `await lazyView(() => import("./views/x"))` — le rejet devient `ViewLoadError`. */
export async function lazyView<T>(importer: () => Promise<T>): Promise<T> {
  try {
    return await importer();
  } catch (error) {
    throw new ViewLoadError(error);
  }
}

export const VIEW_LOAD_RETRY_ID = "view-load-retry";

export function viewLoadErrorHtml(): string {
  return (
    dsPageHeader("Page indisponible", "Le contenu de cette page n'a pas pu être téléchargé.") +
    dsStateHtml("error", {
      title: "Chargement impossible",
      message: "Vérifiez votre connexion puis rechargez la page. Votre session devra peut-être être rouverte.",
      action: { label: "Recharger la page", id: VIEW_LOAD_RETRY_ID },
    })
  );
}

export function renderViewLoadError(view: HTMLElement, reload: () => void): void {
  view.innerHTML = viewLoadErrorHtml();
  view.querySelector(`#${VIEW_LOAD_RETRY_ID}`)?.addEventListener("click", reload);
}
