/**
 * P62a-ui-3panes — Comparaison trois volets (base, override, nouveau commun)
 * + aperçu du résultat de fusion. P62b : choix bloc par bloc et compteur de
 * conflits restants. P62c : résultat éditable, publication en une confirmation.
 *
 * Le serveur calcule l'aperçu à partir des trois versions de la Library et
 * valide le résultat publié (schéma du kind, marqueurs) avant toute écriture.
 *
 * Accessibilité : les trois volets et l'aperçu sont des régions
 * focalisables (`tabindex="0"`, `role="region"`, labels ARIA français) —
 * Tab suffit. Les flèches ← → (et ↑ ↓, Début, Fin) déplacent le focus
 * d'un volet à l'autre (`bindLibraryMerge`, amélioration progressive).
 */

import { describeError, esc } from "../ui";
import { dsBadge, dsStatus } from "../ds/ds";
import type { LibraryMergeApply, LibraryMergePreview } from "../libraryApi";

/* ------------------------------------------------------------------ */
/* Données : miroir strict du contrat Python (textes + conflits).      */
/* ------------------------------------------------------------------ */

export type LibraryMergeData = LibraryMergePreview;
type LibraryMergeResult = LibraryMergeData["result"];
export type LibraryMergeChoiceInput = Pick<LibraryMergeApply, "choice" | "content">;

export interface LibraryMergeProvider {
  readonly label?: string;
  load(): Promise<LibraryMergeData>;
  /** Applique un choix (garder, fusionner, revenir au commun) ; l'historique est conservé. */
  apply?(input: LibraryMergeChoiceInput): Promise<void>;
}

/** Fournisseur en mémoire : tests, démos, conteneurs sans backend. */
export function staticMergeProvider(data: LibraryMergeData, label = "fournisseur statique"): LibraryMergeProvider {
  return {
    label,
    load: () => Promise.resolve(data),
  };
}

/* ------------------------------------------------------------------ */
/* Résolution par bloc (pure).                                         */
/* ------------------------------------------------------------------ */

export type HunkChoice = "ours" | "theirs" | "both" | "base";

const CONFLICT_MARKERS = ["<<<<<<<", "=======", ">>>>>>>"];

function terminated(text: string): string {
  return text === "" || text.endsWith("\n") ? text : `${text}\n`;
}

function newlines(text: string): number {
  return text.split("\n").length - 1;
}

/** Remplace chaque bloc choisi par son texte ; un bloc sans choix garde ses marqueurs. */
export function resolveMergeContent(result: LibraryMergeResult, choices: readonly (HunkChoice | null)[]): string {
  const starts = [0];
  for (let index = 0; index < result.content.length; index += 1) {
    if (result.content[index] === "\n") starts.push(index + 1);
  }
  let content = result.content;
  for (let index = result.conflicts.length - 1; index >= 0; index -= 1) {
    const choice = choices[index] ?? null;
    const conflict = result.conflicts[index];
    if (choice === null || conflict === undefined) continue;
    const first = conflict.start_line - 1;
    const size = 3 + newlines(terminated(conflict.ours)) + newlines(terminated(conflict.theirs));
    const replacement = choice === "both" ? terminated(conflict.ours) + conflict.theirs : conflict[choice];
    content = content.slice(0, starts[first]) + replacement + content.slice(starts[first + size] ?? content.length);
  }
  return content;
}

/** Nombre de blocs en conflit restant dans un texte (marqueurs d'ouverture). */
export function remainingConflicts(text: string): number {
  return text.split("\n").filter((line) => line.startsWith("<<<<<<<")).length;
}

/** Raison bloquant la publication, ou null si le résultat est publiable. */
function mergeResultProblem(text: string): string | null {
  const remaining = remainingConflicts(text);
  if (remaining > 0) return `${remaining} conflit(s) restant(s) : choisissez un bloc pour chacun ou éditez le résultat.`;
  if (text.split("\n").some((line) => CONFLICT_MARKERS.some((marker) => line.startsWith(marker)))) {
    return "Le résultat contient encore des marqueurs de conflit.";
  }
  if (text.trim() === "") return "Le résultat est vide.";
  return null;
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

const HUNK_OPTIONS: readonly (readonly [HunkChoice, string])[] = [
  ["theirs", "Accepter le nouveau commun"],
  ["ours", "Rejeter (garder ma version)"],
  ["both", "Garder les deux"],
  ["base", "Revenir à la base"],
];

function hunkChoiceHtml(index: number): string {
  const options = HUNK_OPTIONS.map(
    ([value, label]) =>
      `<label><input type="radio" name="library-merge-hunk-${index}" value="${value}" data-merge-hunk="${index}"> ${esc(label)}</label>`,
  ).join("");
  return `<fieldset class="library-merge-choice"><legend>Choix pour le conflit ${index + 1}</legend>${options}</fieldset>`;
}

function conflictsHtml(result: LibraryMergeResult, canApply: boolean): string {
  if (result.conflicts.length === 0) {
    return dsStatus("success", "Aucun conflit : le résultat ci-dessus s'applique tel quel.");
  }
  const items = result.conflicts
    .map((conflict, index) => {
      return (
        `<li><h4>Conflit ${index + 1} — ligne ${conflict.start_line}</h4>` +
        `<p><button type="button" class="ds-btn" data-merge-conflict-link="${index + 1}">Voir dans l'aperçu</button></p>` +
        `<div class="library-merge-conflict-texts">` +
        `<div><h5>Base commune</h5><pre class="mono">${esc(conflict.base) === "" ? "—" : esc(conflict.base)}</pre></div>` +
        `<div><h5>Ma version</h5><pre class="mono">${esc(conflict.ours) === "" ? "—" : esc(conflict.ours)}</pre></div>` +
        `<div><h5>Nouveau commun</h5><pre class="mono">${esc(conflict.theirs) === "" ? "—" : esc(conflict.theirs)}</pre></div>` +
        `</div>${canApply ? hunkChoiceHtml(index) : ""}</li>`
      );
    })
    .join("");
  return (
    `<p role="status">${dsBadge(`${result.conflicts.length} conflit(s)`, "warning")} ` +
    `Les blocs en conflit apparaissent dans l’aperçu.</p>` +
    `<ol class="library-merge-conflicts">${items}</ol>`
  );
}

/** Marqueurs git-style ancrés dans l'aperçu pour les liens "Voir dans l'aperçu". */
function previewHtml(result: LibraryMergeResult): string {
  const lines = result.content.split("\n");
  const markers = new Map(result.conflicts.map((conflict, index) => [conflict.start_line, index + 1]));
  const rendered = lines
    .map((line, index) => {
      const marker = markers.get(index + 1);
      if (marker !== undefined) {
        return `<span class="library-merge-marker" tabindex="-1" id="library-merge-conflict-${marker}">${esc(line)}</span>`;
      }
      const trimmed = line.trimStart();
      if (trimmed.startsWith("=======") || trimmed.startsWith(">>>>>>>")) {
        return `<span class="library-merge-marker">${esc(line)}</span>`;
      }
      return esc(line);
    })
    .join("\n");
  return `<pre class="library-merge-text mono" tabindex="0">${rendered === "" ? "Vide." : rendered}</pre>`;
}

/** Trois volets + aperçu + conflits : HTML pur à partir de données fournies. */
export function libraryMergeHtml(data: LibraryMergeData, canApply = false): string {
  const { inputs, result } = data;
  return (
    `<div class="library-merge-panes" role="group" aria-label="Trois volets : base commune, ma version, nouveau commun" data-merge-panes>` +
    `${paneHtml("library-merge-base", "Base commune", "origine partagée", inputs.base)}` +
    `${paneHtml("library-merge-ours", "Ma version", "override publié", inputs.ours)}` +
    `${paneHtml("library-merge-theirs", "Nouveau commun", "commun mis à jour", inputs.theirs)}` +
    `</div>` +
    `<section aria-label="Aperçu du résultat" data-merge-preview><h3>Aperçu du résultat</h3>` +
    `${previewHtml(result)}</section>` +
    `<section aria-label="Conflits"><h3>Conflits</h3>${conflictsHtml(result, canApply)}</section>`
  );
}

function applyZoneHtml(content: string): string {
  const problem = mergeResultProblem(content);
  return (
    `<section class="library-merge-apply" aria-label="Appliquer la fusion" data-merge-apply-zone>` +
    `<h3>Résultat à publier</h3>` +
    `<p class="ds-list-sub">Changer un choix de bloc régénère le résultat. Le texte reste modifiable avant publication ; ` +
    `le serveur valide le schéma du kind et n'écrit rien en cas d'erreur.</p>` +
    `<label for="library-merge-result">Résultat de la fusion (modifiable)</label>` +
    `<textarea id="library-merge-result" class="library-merge-result mono" rows="12" spellcheck="false" data-merge-result>${esc(content)}</textarea>` +
    `<p role="status" data-merge-remaining>${remainingConflicts(content)} conflit(s) restant(s)</p>` +
    `<p class="ds-list-sub" data-merge-validation>${esc(problem ?? "Prêt à publier.")}</p>` +
    `<div class="library-merge-actions">` +
    `<button type="button" class="ds-btn ds-btn--primary ds-btn--sm" data-merge-publish${problem === null ? "" : " disabled"}>Publier le résultat</button>` +
    `<button type="button" class="ds-btn ds-btn--sm" data-merge-keep>Garder mon override</button>` +
    `<button type="button" class="ds-btn ds-btn--danger ds-btn--sm" data-merge-revert>Revenir au commun</button>` +
    `</div>` +
    `<p class="ds-list-sub">Revenir au commun déprécie mon override ; il reste dans l'historique et la sauvegarde locale se restaure avec <code>library restore</code>.</p>` +
    `<p role="alert" data-merge-msg></p></section>`
  );
}

/** Section complète : repliée, intégrable à la page détail. */
export function libraryMergeSectionHtml(merge: LibraryMergeData, canApply = false): string {
  const head =
    `<section class="ds-panel library-merge" aria-labelledby="library-merge-title">` +
    `<header><h2 id="library-merge-title">Comparaison trois volets</h2></header><div class="body">` +
    `<p class="ds-list-sub">Base commune (origine), ma version (override), nouveau commun — puis aperçu du résultat. ` +
    `Astuce clavier : Tab pour entrer dans un volet, flèches ← → pour passer d'un volet à l'autre.</p>`;
  return `${head}${libraryMergeHtml(merge, canApply)}${canApply ? applyZoneHtml(merge.result.content) : ""}</div></section>`;
}

/* ------------------------------------------------------------------ */
/* Comportements DOM (amélioration progressive, CSP : addEventListener). */
/* ------------------------------------------------------------------ */

const CONFIRMATIONS: Record<LibraryMergeChoiceInput["choice"], string> = {
  merge: "Publier ce résultat comme nouvelle version de mon override ?",
  keep_override: "Garder mon override tel quel et le rattacher au nouveau commun ?",
  revert_to_common: "Revenir au commun ? Mon override sera déprécié ; l'historique est conservé.",
};

function bindApplyZone(
  root: Document | HTMLElement,
  result: LibraryMergeResult,
  apply: (input: LibraryMergeChoiceInput) => Promise<void>,
): void {
  const editor = root.querySelector<HTMLTextAreaElement>("[data-merge-result]");
  const publish = root.querySelector<HTMLButtonElement>("[data-merge-publish]");
  if (editor === null || publish === null) return;
  const remaining = root.querySelector<HTMLElement>("[data-merge-remaining]");
  const validation = root.querySelector<HTMLElement>("[data-merge-validation]");
  const msg = root.querySelector<HTMLElement>("[data-merge-msg]");
  const buttons = [...root.querySelectorAll<HTMLButtonElement>("[data-merge-publish], [data-merge-keep], [data-merge-revert]")];
  const refresh = (): void => {
    const problem = mergeResultProblem(editor.value);
    if (remaining !== null) remaining.textContent = `${remainingConflicts(editor.value)} conflit(s) restant(s)`;
    if (validation !== null) validation.textContent = problem ?? "Prêt à publier.";
    publish.disabled = problem !== null;
  };
  const choices: (HunkChoice | null)[] = result.conflicts.map(() => null);
  for (const radio of root.querySelectorAll<HTMLInputElement>("[data-merge-hunk]")) {
    radio.addEventListener("change", () => {
      choices[Number(radio.dataset["mergeHunk"])] = radio.value as HunkChoice;
      editor.value = resolveMergeContent(result, choices);
      refresh();
    });
  }
  editor.addEventListener("input", refresh);
  const run = (input: LibraryMergeChoiceInput): void => {
    if (input.choice === "merge" && mergeResultProblem(editor.value) !== null) return;
    if (!window.confirm(CONFIRMATIONS[input.choice])) return;
    for (const button of buttons) button.disabled = true;
    if (msg !== null) msg.textContent = "";
    apply(input).catch((error: unknown) => {
      if (msg !== null) msg.textContent = describeError(error);
      for (const button of buttons) button.disabled = false;
      refresh();
    });
  };
  publish.addEventListener("click", () => { run({ choice: "merge", content: editor.value }); });
  root.querySelector("[data-merge-keep]")?.addEventListener("click", () => { run({ choice: "keep_override" }); });
  root.querySelector("[data-merge-revert]")?.addEventListener("click", () => { run({ choice: "revert_to_common" }); });
}

/** Flèches ← → ↑ ↓, Début, Fin entre les trois volets ; choix de fusion si `apply` est fourni. */
export function bindLibraryMerge(
  root: Document | HTMLElement,
  result?: LibraryMergeResult,
  apply?: (input: LibraryMergeChoiceInput) => Promise<void>,
): void {
  if (result !== undefined && apply !== undefined) bindApplyZone(root, result, apply);
  const scope = root.querySelector("[data-merge-panes]");
  if (scope === null) return;
  for (const button of root.querySelectorAll<HTMLButtonElement>("[data-merge-conflict-link]")) {
    button.addEventListener("click", () => {
      root.querySelector<HTMLElement>(`#library-merge-conflict-${button.dataset["mergeConflictLink"]}`)?.focus();
    });
  }
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
    `<p role="status">Chargement de la comparaison…</p></div></section>`;
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
  root.innerHTML = libraryMergeSectionHtml(data, provider.apply !== undefined);
  bindLibraryMerge(root, data.result, provider.apply?.bind(provider));
}
