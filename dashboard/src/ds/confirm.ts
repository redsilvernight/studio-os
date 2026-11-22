import { dsModalHtml, openDsDialog } from "./ds";

export interface ConfirmDsOptions {
  /** Libellé du bouton de confirmation (défaut « Confirmer »). */
  confirmLabel?: string;
  /** Action destructive : bouton de confirmation en rouge. */
  danger?: boolean;
  /** Titre du dialogue (défaut « Confirmer l'action »). */
  title?: string;
}

let confirmSeq = 0;

/**
 * Remplace window.confirm : dialogue ds (focus piégé, Échap = annuler),
 * promesse résolue à true (Confirmer) ou false (Annuler, Échap, clic hors
 * dialogue). Le message est du texte brut. Le dialogue est retiré du DOM
 * une fois résolu.
 */
export function confirmDs(message: string, options: ConfirmDsOptions = {}): Promise<boolean> {
  const id = `ds-confirm-${(confirmSeq += 1)}`;
  const host = document.createElement("div");
  host.innerHTML = dsModalHtml({
    id,
    title: options.title ?? "Confirmer l'action",
    body: "<p data-ds-confirm-message></p>",
    actions: [
      { label: "Annuler", id: `${id}-cancel` },
      { label: options.confirmLabel ?? "Confirmer", id: `${id}-ok`, variant: options.danger === true ? "danger" : "primary" },
    ],
  });
  const message_ = host.querySelector("[data-ds-confirm-message]");
  if (message_ !== null) message_.textContent = message;
  host.querySelector(`#${id}-ok`)?.setAttribute("data-ds-confirm", "ok");
  host.querySelector(`#${id}-cancel`)?.setAttribute("data-ds-confirm", "cancel");
  document.body.append(host);
  const overlay = host.querySelector<HTMLElement>(`#${id}`) as HTMLElement;
  const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  return new Promise<boolean>((resolve) => {
    let observer: MutationObserver | null = null;
    const finish = (value: boolean): void => {
      observer?.disconnect();
      host.remove();
      if (trigger !== null && trigger.isConnected) trigger.focus();
      resolve(value);
    };
    // Les boutons portent data-ds-close : le clic ferme (hidden) ; on lit le
    // bouton cliqué en phase de capture, avant la fermeture.
    overlay.addEventListener(
      "click",
      (event) => {
        const target = event.target instanceof Element ? event.target.closest("[data-ds-confirm]") : null;
        if (target !== null) finish(target.getAttribute("data-ds-confirm") === "ok");
      },
      true,
    );
    // Échap ou toute autre fermeture : annuler.
    observer = new MutationObserver(() => {
      if (overlay.hasAttribute("hidden")) finish(false);
    });
    observer.observe(overlay, { attributes: true, attributeFilter: ["hidden"] });
    openDsDialog(document.body, id, trigger);
  });
}
