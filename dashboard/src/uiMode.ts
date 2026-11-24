/**
 * Mode d'affichage (R2-modes) : « simple » (défaut, tout nouveau compte) ou
 * « expert ». Expert ajoute (identifiants copiables, termes techniques) sans
 * jamais retirer ni déplacer un élément du mode Simple : mêmes routes, mêmes
 * données, même navigation. Le choix se mémorise sur le poste, sans
 * identifiant ni secret ; une valeur illisible vaut « simple ».
 */
export type UiMode = "simple" | "expert";

export const UI_MODE_STORAGE_KEY = "studio-os.ui-mode";

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function storage(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function loadUiMode(store: StorageLike | null = storage()): UiMode {
  try {
    return store?.getItem(UI_MODE_STORAGE_KEY) === "expert" ? "expert" : "simple";
  } catch {
    return "simple";
  }
}

/** Mémorise le mode ; un stockage indisponible ne bloque jamais l'interface. */
export function saveUiMode(mode: UiMode, store: StorageLike | null = storage()): void {
  try {
    store?.setItem(UI_MODE_STORAGE_KEY, mode);
  } catch {
    // Quota ou navigation privée : le choix n'est simplement pas mémorisé.
  }
}

export function toggledUiMode(mode: UiMode): UiMode {
  return mode === "expert" ? "simple" : "expert";
}

/** Expose le mode au CSS (`[data-ui-mode="expert"]`) et aux tests. */
export function applyUiMode(mode: UiMode, root: HTMLElement = document.documentElement): void {
  root.dataset["uiMode"] = mode;
}

/** Bascule, mémorise, applique et notifie (`ui-mode-change`) ; renvoie le nouveau mode. */
export function switchUiMode(mode: UiMode): UiMode {
  saveUiMode(mode);
  applyUiMode(mode);
  document.dispatchEvent(new CustomEvent("ui-mode-change", { detail: mode }));
  return mode;
}

/** Terme courant (mode Simple) → terme technique affiché à côté en mode Expert. */
const EXPERT_TERMS: Readonly<Record<string, string>> = {
  "Aujourd'hui": "Accueil",
  "Plan": "Roadmap",
  "Notes": "Vault",
  "Savoir-faire": "Bibliothèque",
  "Réglages": "Configuration",
  "Fichiers occupés": "Réservations",
  "Moteur IA": "Runtime",
  "Moteurs IA": "Runtimes",
  "Affectations": "Bindings",
};

const TECH_BLOCKS = "details.ds-tech, details.settings-technical";
const TERM_MARK = "data-lx-tech";
const OPENED_MARK = "data-expert-opened";

/**
 * Expert : annote les titres du terme technique et ouvre les « Détails
 * techniques » (identifiants visibles). Simple : retire l'annotation et
 * referme ce qu'Expert avait ouvert. Idempotent ; ne retire ni ne déplace rien.
 */
export function enhanceForMode(mode: UiMode, root: ParentNode = document): void {
  for (const mark of Array.from(root.querySelectorAll(`[${TERM_MARK}]`))) {
    if (mode === "simple") mark.remove();
  }
  for (const block of Array.from(root.querySelectorAll<HTMLDetailsElement>(TECH_BLOCKS))) {
    if (mode === "expert" && !block.open) {
      block.open = true;
      block.setAttribute(OPENED_MARK, "");
    } else if (mode === "simple" && block.hasAttribute(OPENED_MARK)) {
      block.open = false;
      block.removeAttribute(OPENED_MARK);
    }
  }
  if (mode !== "expert") return;
  for (const heading of Array.from(root.querySelectorAll("h1, h2, h3"))) {
    if (heading.querySelector(`[${TERM_MARK}]`) !== null) continue;
    const technical = EXPERT_TERMS[(heading.textContent ?? "").trim()];
    if (technical === undefined) continue;
    const span = document.createElement("span");
    span.setAttribute(TERM_MARK, "");
    span.className = "lx-tech";
    span.textContent = ` (${technical})`;
    heading.appendChild(span);
  }
}

/** Applique le mode courant à chaque rendu (observateur) et à `ui-mode-change`. */
export function watchExpertMode(root: HTMLElement, current: () => UiMode): void {
  let queued = false;
  const run = (): void => {
    queued = false;
    observer.disconnect();
    enhanceForMode(current(), root);
    observer.observe(root, { childList: true, subtree: true });
  };
  const observer = new MutationObserver(() => {
    if (!queued) {
      queued = true;
      queueMicrotask(run);
    }
  });
  document.addEventListener("ui-mode-change", run);
  run();
}
