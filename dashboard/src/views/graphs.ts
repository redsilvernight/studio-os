import { getPlatform, type Platform } from "../platform";
import type { GraphPage, GraphNodeRef } from "../platform/generated/local-contracts.generated";
import { dsPageHeader, dsStateHtml, dsTechDetails } from "../ds/ds";
import { esc, isOfflineError } from "../ui";
import { loadOnboardingState } from "../onboarding/state";
import { GraphCollection, nodeKey } from "../graphs/model";
import { createLocalGraphSource, STATE_LABELS, type GraphDataSource, type GraphKind, type SourceStatus } from "../graphs/provider";
import { mountGraphViewer } from "../graphs/viewer";
import type { FixtureSize } from "../graphs/fixtures";
import "../graphs/viewer.css";

export interface GraphPageOptions {
  platform?: Platform;
  workspaceId?: string;
  sources?: GraphDataSource[];
  projectionPages?: GraphPage[];
}

const titles: Record<GraphKind, string> = { knowledge: "Graphe de connaissances", code: "Graphe de code", project: "Graphe du projet" };

const descriptions: Record<GraphKind, string> = {
  knowledge: "Éléments, relations et provenance, sans ouverture auto.",
  code: "Éléments, relations et provenance, sans ouverture auto.",
  project: "Projection des sources disponibles et de leurs références explicites.",
};

/** Identifiant du bouton « Réessayer » partagé par les états du graphe. */
const GRAPH_RETRY_ID = "graph-retry";

/**
 * Réseau coupé : le statut de connexion du shell passe déjà en dégradé, on
 * ne pose donc qu'une seule action de reprise ici — pas de seconde bannière.
 */
function offlineStateHtml(error?: unknown): string {
  return dsStateHtml("offline", {
    title: "Serveur injoignable",
    message:
      error instanceof Error && error.message !== ""
        ? `Les sources du poste n'ont pas pu être jointes. ${error.message}`
        : "Les sources du poste n'ont pas pu être jointes. La file locale reste active et la reprise se fera au retour du réseau.",
    action: { label: "Réessayer", id: GRAPH_RETRY_ID },
    details: [{ label: "Vue", value: "Sources locales du dossier sélectionné ; aucune donnée n'est inventée hors ligne." }],
  });
}

/**
 * Colonne de contexte : règle de liaison, repli sans dossier, puis les
 * détails que le flux n'affiche plus (curseurs de pagination, fournisseurs).
 * Aucun état de source ici — la carte principale les porte une seule fois.
 */
function graphContextHtml(hasWorkspace: boolean): string {
  const noWorkspace =
    hasWorkspace
      ? ""
      : `<div><h2>Sans dossier</h2><p>Aucun dossier actif : <a href="#/workspaces">ouvrez les dossiers</a>, ou explorez une démonstration ci-dessus.</p></div>`;
  return (
    `<aside class="ds-card tool-context" aria-label="Contexte du graphe">` +
    `<div><h2>Règle de liaison</h2><p>Un lien entre sources n'apparaît que si une référence explicite est fournie. Tâches, roadmap, décisions et Git ne sont pas reliés automatiquement.</p></div>` +
    noWorkspace +
    `<div>` +
    dsTechDetails(
      [
        { label: "Pagination", value: "La liste reprend là où elle s'est arrêtée (« Résultats suivants ») ; les curseurs restent internes." },
        { label: "Fournisseurs", value: "Sources locales du dossier sélectionné, jamais le réseau." },
        { label: "Démonstrations", value: "Jeux de données fictifs : aucun fichier du poste n'est lu." },
      ],
      "Détails techniques — curseurs et fournisseurs",
    ) +
    `</div>` +
    `</aside>`
  );
}

export function mountGraphPage(root: HTMLElement, kind: GraphKind, options: GraphPageOptions = {}): { ready: Promise<void>; dispose(): void } {
  const platform = options.platform ?? getPlatform();
  // Sans dossier dans l'URL (lien de la barre latérale), reprendre celui retenu par l'onboarding.
  const workspaceId = options.workspaceId ?? (platform.mode === "web" ? undefined : loadOnboardingState().workspaceId);
  const suffix = workspaceId ? `/${encodeURIComponent(workspaceId)}` : "";
  root.innerHTML = `<p class="ds-eyebrow">Administration · Dossier actif</p>${dsPageHeader(titles[kind], descriptions[kind])}
    <nav class="graph-tabs" aria-label="Vues de graphe">${Object.entries(titles).map(([key, title]) => `<a class="ds-btn" href="#/graphs/${key}${suffix}" ${key === kind ? 'aria-current="page"' : ""}>${title}</a>`).join("")}</nav>
    <div class="tool-columns">
    <div class="tool-main">
    <section class="ds-card graph-page">
      <div class="graph-page-controls"><label>Source affichée <select data-graph-demo><option value="local">Sources du dossier</option><option value="small">Démonstration · petit graphe</option><option value="medium">Démonstration · 1 000 nœuds</option><option value="large">Démonstration · 30 000 nœuds</option><option value="partial">Démonstration · graphe partiel</option><option value="empty">Démonstration · graphe vide</option></select></label><button class="ds-btn ds-btn--primary" type="button" data-reload>Actualiser</button></div>
      <p data-origin></p><div data-source-status role="status" aria-live="polite"></div>
      <div data-operation-status role="status" aria-live="polite"></div>
      <form data-source-search hidden><label>Rechercher dans les sources <input name="query" maxlength="200" required autocomplete="off"></label><button class="ds-btn" type="submit">Rechercher dans les sources</button></form>
      <div data-source-results></div><div data-viewer></div>
    </section>
    </div>${graphContextHtml(workspaceId !== undefined)}</div>`;
  const select = root.querySelector<HTMLSelectElement>("[data-graph-demo]")!;
  const statusRoot = root.querySelector<HTMLElement>("[data-source-status]")!;
  const operationRoot = root.querySelector<HTMLElement>("[data-operation-status]")!;
  const origin = root.querySelector<HTMLElement>("[data-origin]")!;
  const viewerRoot = root.querySelector<HTMLElement>("[data-viewer]")!;
  const resultsRoot = root.querySelector<HTMLElement>("[data-source-results]")!;
  const searchForm = root.querySelector<HTMLFormElement>("[data-source-search]")!;
  let generation = 0;
  let searchGeneration = 0;
  let collection = new GraphCollection();
  let sources: GraphDataSource[] = [];
  let cursors = new Map<GraphDataSource, string>();
  let owners = new Map<string, GraphDataSource>();
  let expansionCursors = new Map<string, string>();
  let viewer: ReturnType<typeof mountGraphViewer> | undefined;
  let busy = false;

  async function operation(action: () => Promise<void>): Promise<void> {
    if (busy) return;
    const current = generation;
    busy = true;
    operationRoot.textContent = "Chargement…";
    try {
      await action();
      if (current === generation) {
        operationRoot.textContent = "";
        viewer?.update(collection.snapshot());
      }
    } catch (error) {
      if (current === generation) operationRoot.textContent = error instanceof Error ? error.message : "Le chargement a échoué.";
    } finally { if (current === generation) busy = false; }
  }

  async function expand(ref: GraphNodeRef): Promise<void> {
    const owner = owners.get(ref.source_id);
    if (!owner) { operationRoot.textContent = "La source de cette référence n’est pas disponible."; return; }
    const current = generation;
    await operation(async () => {
      const key = nodeKey(ref);
      const page = await owner.expand(ref, expansionCursors.get(key));
      if (current !== generation) return;
      collection.add(page, "expand");
      if (page.next_cursor) expansionCursors.set(key, page.next_cursor); else expansionCursors.delete(key);
    });
  }

  async function more(): Promise<void> {
    const current = generation;
    await operation(async () => {
      const entry = cursors.entries().next().value as [GraphDataSource, string] | undefined;
      if (!entry) return;
      const [source, cursor] = entry;
      const page = await source.page(cursor);
      if (current !== generation) return;
      if (page.next_cursor === cursor) throw new Error("La source a répété son curseur. Rechargez le graphe.");
      collection.add(page);
      if (page.next_cursor) cursors.set(source, page.next_cursor); else cursors.delete(source);
    });
  }

  async function load(): Promise<void> {
    const current = ++generation;
    ++searchGeneration;
    viewer?.dispose(); viewer = undefined;
    collection = new GraphCollection(); sources = []; cursors = new Map(); owners = new Map(); expansionCursors = new Map(); busy = false;
    viewerRoot.replaceChildren(); resultsRoot.replaceChildren(); operationRoot.textContent = "";
    searchForm.hidden = true;
    statusRoot.textContent = STATE_LABELS.loading;
    let projections = options.projectionPages ?? [];
    const demo = select.value !== "local";
    origin.textContent = demo ? "Démonstration — données fictives. Aucun fichier local n’est lu." : "Sources locales du dossier sélectionné.";
    try {
      if (demo) {
        const fixtures = await import("../graphs/fixtures");
        if (current !== generation) return;
        const size = select.value as FixtureSize;
        sources = (kind === "project" ? ["knowledge", "code"] as const : [kind]).map((source) => fixtures.createFixtureGraphSource(source, size));
        projections = kind === "project" && (size === "small" || size === "partial") ? [fixtures.projectionFixturePage()] : [];
      } else if (options.sources) {
        sources = options.sources;
      } else if (platform.mode === "web") {
        statusRoot.textContent = "Disponible dans Studi’OS Desktop lorsque cette source locale est activée.";
        origin.textContent = "Les sources locales ne sont pas accessibles depuis le navigateur.";
        return;
      } else if (!workspaceId) {
        statusRoot.innerHTML = 'Aucun dossier actif pour ce graphe. <a href="#/workspaces">Ouvrir les dossiers</a>. Vous pouvez explorer une démonstration.';
        return;
      } else {
        sources = (kind === "project" ? ["knowledge", "code"] as const : [kind]).map((source) => createLocalGraphSource(platform, source, workspaceId));
      }
      const reports: { label: string; status: SourceStatus }[] = [];
      const available: GraphDataSource[] = [];
      let offline = false;
      for (const source of sources) {
        try {
          const status = await source.status();
          if (current !== generation) return;
          reports.push({ label: source.label, status });
          if (status.state === "ready" || status.state === "stale") {
            const page = await source.page();
            if (current !== generation) return;
            collection.add(page);
            owners.set(page.source.source_id, source);
            if (page.next_cursor) cursors.set(source, page.next_cursor);
            available.push(source);
          }
        } catch (error) {
          if (current !== generation) return;
          offline ||= isOfflineError(error);
          reports.push({ label: source.label, status: { state: "error", message: error instanceof Error ? error.message : "Erreur de chargement." } });
        }
      }
      if (current !== generation) return;
      sources = available;
      for (const projection of projections) collection.add(projection);
      statusRoot.innerHTML = reports.map(({ label, status }) => `<p data-state="${esc(status.state)}">${esc(label)} : ${esc(STATE_LABELS[status.state])}${status.progress != null ? ` ${esc(status.progress)} %` : ""}${status.message ? ` ${esc(status.message)}` : ""}</p>`).join("");
      if (offline) statusRoot.insertAdjacentHTML("afterbegin", offlineStateHtml());
      if (available.length || projections.length) viewer = mountGraphViewer(viewerRoot, collection.snapshot(), { onExpand: expand, onMore: more, canLoadMore: () => cursors.size > 0 });
      searchForm.hidden = available.length === 0;
    } catch (error) {
      if (current !== generation) return;
      statusRoot.innerHTML = isOfflineError(error)
        ? offlineStateHtml(error)
        : dsStateHtml("error", {
            title: "Graphe indisponible",
            message: error instanceof Error ? error.message : "Erreur de chargement.",
            action: { label: "Réessayer", id: GRAPH_RETRY_ID },
            details: [{ label: "Source", value: `Vue ${kind} du dossier sélectionné.` }],
          });
    }
  }

  async function search(query: string, sourceCursors?: Map<GraphDataSource, string>): Promise<void> {
    const current = ++searchGeneration;
    const graphGeneration = generation;
    resultsRoot.textContent = "Recherche…";
    const targets = sources.filter((source) => !sourceCursors || sourceCursors.has(source));
    const answers = await Promise.allSettled(targets.map(async (source) => ({ source, result: await source.search(query, sourceCursors?.get(source)) })));
    if (current !== searchGeneration || graphGeneration !== generation) return;
    resultsRoot.replaceChildren();
    const next = new Map<GraphDataSource, string>();
    for (let i = 0; i < answers.length; i++) {
      const answer = answers[i]!;
      const heading = document.createElement("h2"); heading.textContent = targets[i]!.label;
      resultsRoot.append(heading);
      if (answer.status === "rejected") {
        const message = document.createElement("p"); message.textContent = "Recherche indisponible dans cette source."; resultsRoot.append(message); continue;
      }
      const { source, result } = answer.value;
      const summary = document.createElement("p");
      summary.textContent = `${result.hits.length} résultat(s)${result.partial ? " — résultats partiels" : ""}. Les références sont affichées sans ouverture automatique.`;
      resultsRoot.append(summary);
      const list = document.createElement("ul");
      for (const hit of result.hits) {
        const row = document.createElement("li");
        row.textContent = `${hit.label} ${hit.uri}`;
        if (hit.ref) {
          const button = document.createElement("button"); button.type = "button"; button.className = "ds-btn"; button.textContent = "Charger dans le graphe";
          button.addEventListener("click", () => { void expand(hit.ref!); }); row.append(button);
        }
        list.append(row);
      }
      resultsRoot.append(list);
      if (result.nextCursor) next.set(source, result.nextCursor);
    }
    if (next.size) {
      const button = document.createElement("button"); button.type = "button"; button.className = "ds-btn"; button.textContent = "Résultats suivants";
      button.addEventListener("click", () => { void search(query, next); }); resultsRoot.append(button);
    }
  }
  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = (new FormData(searchForm).get("query") as string ?? "").trim();
    if (query) void search(query);
  });
  select.addEventListener("change", () => { void load(); });
  root.querySelector("[data-reload]")!.addEventListener("click", () => { void load(); });
  // Les états (hors ligne, erreur) proposent « Réessayer » : un seul câblage.
  statusRoot.addEventListener("click", (event) => {
    if ((event.target as Element | null)?.closest(`#${GRAPH_RETRY_ID}`) === null) return;
    void load();
  });
  const ready = load();
  return { ready, dispose() { generation++; searchGeneration++; viewer?.dispose(); } };
}

export function renderGraphs(root: HTMLElement, kind: GraphKind, options: GraphPageOptions = {}): void {
  mountGraphPage(root, kind, options);
}
