/**
 * P62a-ui-3panes — Comparaison trois volets (base, override, nouveau commun)
 * + aperçu du résultat de fusion.
 *
 * Le moteur de fusion vit côté Python
 * (`packages/studio-client/src/studio_client/library_merge.py`) et n'est
 * pas réimplémenté ici : cette UI affiche des données fournies en
 * props/état (base, ours, theirs, résultat, conflits). Aucune route API
 * de fusion n'existe côté serveur, donc aucune n'est appelée : les données
 * arrivent par un fournisseur injectable (`LibraryMergeProvider`, p. ex.
 * `staticMergeProvider` en test/démo). Voir `LIBRARY_MERGE_NO_API_NOTE`.
 *
 * Accessibilité : les trois volets et l'aperçu sont des régions
 * focalisables (`tabindex="0"`, `role="region"`, labels ARIA français) —
 * Tab suffit. Les flèches ← → (et ↑ ↓, Début, Fin) déplacent le focus
 * d'un volet à l'autre (`bindLibraryMerge`, amélioration progressive).
 */

import { describeError, esc } from "../ui";
import { dsBadge, dsStatus } from "../ds/ds";

/* ------------------------------------------------------------------ */
/* Données : miroir strict du contrat Python (textes + conflits).      */
/* ------------------------------------------------------------------ */

export interface LibraryMergeInputs {
  /** Commun d'origine (base). */
  base: string;
  /** Ma version (override). */
  ours: string;
  /** Nouveau commun (theirs). */
  theirs: string;
}

export interface LibraryMergeConflict {
  /** Ligne 1-based du marqueur d'ouverture dans le contenu fusionné. */
  startLine: number;
  /** Début 0-based (demi-ouvert) dans la base normalisée. */
  baseStart: number;
  /** Fin 0-based (demi-ouverte) dans la base normalisée. */
  baseEnd: number;
  base: string;
  ours: string;
  theirs: string;
}

export interface LibraryMergeResult {
  content: string;
  conflicts: LibraryMergeConflict[];
}

export interface LibraryMergeData {
  inputs: LibraryMergeInputs;
  result: LibraryMergeResult;
}

/* ------------------------------------------------------------------ */
/* Fournisseur injectable : aucune route API inventée.                 */
/* ------------------------------------------------------------------ */

/**
 * Aucune route API de fusion n'existe : le serveur n'expose ni les trois
 * textes (base, override, nouveau commun) ni le résultat calculé. Cette UI
 * ne devine donc aucune URL et n'appelle rien toute seule — le conteneur
 * injecte un `LibraryMergeProvider` qui fournit des `LibraryMergeData`
 * déjà calculées (p. ex. par le moteur Python via un futur endpoint).
 */
export const LIBRARY_MERGE_NO_API_NOTE =
  "Aucune route API de fusion : données injectées par un fournisseur, moteur Python non réexécuté ici.";

export interface LibraryMergeProvider {
  readonly label: string;
  load(): Promise<LibraryMergeData>;
}

/** Fournisseur en mémoire : tests, démos, conteneurs sans backend. */
export function staticMergeProvider(data: LibraryMergeData, label = "fournisseur statique"): LibraryMergeProvider {
  return {
    label,
    load: () => Promise.resolve(data),
  };
}

/* ------------------------------------------------------------------ */
/* Rendu pur (DOM-free, testable).                                     */
/* ------------------------------------------------------------------ */

function paneHtml(id: string, title: string, detail: string, text: string): string {
  return (
    `<section class="library-merge-pane" id="${id}" tabindex="0" role="region" aria-label="${esc(title)} — ${esc(detail)}">` +
    `<h3>${esc(title)}</h3><p class="ds-list-sub">${esc(detail)}</p>` +
    (text === "" ? `<p class="ds-list-sub">Vide.</p>` : `<pre class="library-merge-text mono">${esc(text)}</pre>`) +
    `</section>`
  );
}

function conflictsHtml(result: LibraryMergeResult): string {
  if (result.conflicts.length === 0) {
    return dsStatus("success", "Aucun conflit : le résultat ci-dessus s'applique tel quel.");
  }
  const items = result.conflicts
    .map((conflict, index) => {
      const anchor = `library-merge-conflict-${index + 1}`;
      return (
        `<li><h4>Conflit ${index + 1} — ligne ${conflict.startLine}</h4>` +
        `<p><a href="#${anchor}">Voir dans l'aperçu</a></p>` +
        `<div class="library-merge-conflict-texts">` +
        `<div><h5>Base commune</h5><pre class="mono">${esc(conflict.base) === "" ? "—" : esc(conflict.base)}</pre></div>` +
        `<div><h5>Ma version</h5><pre class="mono">${esc(conflict.ours) === "" ? "—" : esc(conflict.ours)}</pre></div>` +
        `<div><h5>Nouveau commun</h5><pre class="mono">${esc(conflict.theirs) === "" ? "—" : esc(conflict.theirs)}</pre></div>` +
        `</div></li>`
      );
    })
    .join("");
  return (
    `<p role="status">${dsBadge(`${result.conflicts.length} conflit(s)`, "warning")} ` +
    `Trancher chaque bloc puis créer une nouvelle version — rien n'est appliqué automatiquement.</p>` +
    `<ol class="library-merge-conflicts">${items}</ol>`
  );
}

/** Marqueurs git-style ancrés dans l'aperçu pour les liens "Voir dans l'aperçu". */
function previewHtml(result: LibraryMergeResult): string {
  const lines = result.content.split("\n");
  let seen = 0;
  const rendered = lines
    .map((line) => {
      const trimmed = line.trimStart();
      if (trimmed.startsWith("<<<<<<<")) {
        seen += 1;
        return `<span class="library-merge-marker" id="library-merge-conflict-${seen}">${esc(line)}</span>`;
      }
      if (trimmed.startsWith("=======") || trimmed.startsWith(">>>>>>>")) {
        return `<span class="library-merge-marker">${esc(line)}</span>`;
      }
      return esc(line);
    })
    .join("\n");
  return `<pre class="library-merge-text mono" tabindex="0">${rendered === "" ? "Vide." : rendered}</pre>`;
}

/** Trois volets + aperçu + conflits : HTML pur à partir de données fournies. */
export function libraryMergeHtml(data: LibraryMergeData): string {
  const { inputs, result } = data;
  return (
    `<div class="library-merge-panes" role="group" aria-label="Trois volets : base commune, ma version, nouveau commun" data-merge-panes>` +
    `${paneHtml("library-merge-base", "Base commune", "origine partagée", inputs.base)}` +
    `${paneHtml("library-merge-ours", "Ma version", "override local", inputs.ours)}` +
    `${paneHtml("library-merge-theirs", "Nouveau commun", "commun mis à jour", inputs.theirs)}` +
    `</div>` +
    `<section aria-label="Aperçu du résultat" data-merge-preview><h3>Aperçu du résultat</h3>` +
    `<p class="ds-list-sub">Texte fusionné fourni (moteur Python, marqueurs git-style en cas de conflit).</p>` +
    `${previewHtml(result)}</section>` +
    `<section aria-label="Conflits"><h3>Conflits</h3>${conflictsHtml(result)}</section>`
  );
}

/** Section complète : repliée, intégrable à la page détail. */
export function libraryMergeSectionHtml(merge: LibraryMergeData | null): string {
  const head =
    `<section class="ds-panel library-merge" aria-labelledby="library-merge-title">` +
    `<header><h2 id="library-merge-title">Comparaison trois volets</h2></header><div class="body">` +
    `<p class="ds-list-sub">Base commune (origine), ma version (override), nouveau commun — puis aperçu du résultat. ` +
    `Astuce clavier : Tab pour entrer dans un volet, flèches ← → pour passer d'un volet à l'autre.</p>`;
  if (merge === null) {
    return (
      head +
      `<div class="ds-notice ds-notice--info" role="note" data-library-merge="unavailable">` +
      `<strong>Comparaison indisponible.</strong> ${esc(LIBRARY_MERGE_NO_API_NOTE)}</div>` +
      `</div></section>`
    );
  }
  return `${head}${libraryMergeHtml(merge)}</div></section>`;
}

/* ------------------------------------------------------------------ */
/* Comportements DOM (amélioration progressive, CSP : addEventListener). */
/* ------------------------------------------------------------------ */

/** Flèches ← → ↑ ↓, Début, Fin : déplace le focus entre les trois volets. */
export function bindLibraryMerge(root: Document | HTMLElement): void {
  const scope = root.querySelector("[data-merge-panes]");
  if (scope === null) return;
  scope.addEventListener("keydown", (event) => {
    if (!(event.target instanceof HTMLElement) || !event.target.classList.contains("library-merge-pane")) return;
    const key = (event as KeyboardEvent).key;
    const panes = [...scope.querySelectorAll<HTMLElement>(".library-merge-pane")];
    const index = panes.indexOf(event.target);
    if (index === -1) return;
    let next: number | null = null;
    if (key === "ArrowRight" || key === "ArrowDown") next = (index + 1) % panes.length;
    else if (key === "ArrowLeft" || key === "ArrowUp") next = (index - 1 + panes.length) % panes.length;
    else if (key === "Home") next = 0;
    else if (key === "End") next = panes.length - 1;
    if (next !== null) {
      event.preventDefault();
      panes[next]?.focus();
    }
  });
}

/** Peint la section via un fournisseur injecté (chargement, succès, erreur). */
export async function renderLibraryMerge(root: HTMLElement, provider: LibraryMergeProvider): Promise<void> {
  root.innerHTML =
    `<section class="ds-panel library-merge" aria-label="Comparaison trois volets"><div class="body">` +
    `<p role="status">Chargement de la comparaison (${esc(provider.label)})…</p></div></section>`;
  let data: LibraryMergeData;
  try {
    data = await provider.load();
  } catch (error) {
    root.innerHTML =
      `<section class="ds-panel library-merge" aria-label="Comparaison trois volets"><div class="body">` +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Comparaison indisponible.</strong>${esc(describeError(error))}</div>` +
      `</div></section>`;
    return;
  }
  root.innerHTML = libraryMergeSectionHtml(data);
  bindLibraryMerge(root);
}
