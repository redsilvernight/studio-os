/**
 * Vault › Atlas : vue spatiale des notes studio et projet (remplace l'ancien
 * onglet Graph).
 *
 * - Données : `GET /vault/tree` paginé et borné (`loadAtlasNotes`), liens
 *   typés et ancres `task:` / `path:` des résumés ; jamais de fixture.
 * - Rendu : moteur Canvas 2D maison (`createAtlasRenderer`), sans dépendance
 *   ni worker ; canevas sombre, couleurs lues dans les variables `--atlas-*`.
 * - Détail : panneau non modal à côté du canevas (voisins cliquables) ;
 *   « Ouvrir » mène à la note dans la vue Liste (`#/vault/{id}`).
 * - Accessibilité : la liste « Notes visibles » est l'alternative clavier
 *   au canevas ; `prefers-reduced-motion` coupe les vols de caméra.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { dsBadge, dsEmptyState, dsPageHeader, dsSkeleton } from "../ds/ds";
import { describeError, esc } from "../ui";
import type { components } from "../openapi-schema";
import type { VaultNoteStatus, VaultNoteType } from "../vaultApi";
import { loadAtlasNotes } from "../atlas/loader";
import { applyFilters, ATLAS_TYPE_ORDER, buildAtlasGraph, defaultFilters, layoutAtlas, NOTE_TYPE_TOKEN } from "../atlas/model";
import { createAtlasRenderer } from "../atlas/renderer";
import type { AtlasFilters, AtlasGraph, AtlasNode, AtlasPalette, AtlasRenderer, AtlasView } from "../atlas/types";
import { VAULT_STATUS_LABEL, VAULT_TYPE_LABEL, vaultModeNavHtml, vaultScopeLabel } from "./vault";
import "./vaultAtlas.css";

type Project = components["schemas"]["Project"];

export interface VaultAtlasContext {
  client: StudioClient;
  authed: boolean;
}

const HEADER_DESC = "Carte des notes du studio et des projets, avec leurs liens.";
/** Statuts filtrables (superseded a sa propre bascule, archived n'est pas chargé). */
const ATLAS_STATUSES: VaultNoteStatus[] = ["draft", "proposed", "validated"];
/** Plafond de la liste clavier : au-delà, affiner par recherche ou filtres. */
const VISIBLE_LIST_MAX = 60;

const LINK_LABEL: Record<string, string> = {
  links_to: "lie",
  relates_to: "en rapport",
  derived_from: "dérive de",
  supersedes: "remplace",
  anchor: "ancre",
};

function header(): string {
  return dsPageHeader("Vault", HEADER_DESC) + vaultModeNavHtml("atlas");
}

function nodeTitle(node: AtlasNode): string {
  if (node.kind === "satellite") return node.anchorType === "task" ? `Tâche ${node.label.slice(0, 8)}` : node.label;
  return node.title.trim() === "" ? node.slug : node.title;
}

function checkbox(name: string, value: string, label: string, checked: boolean): string {
  return `<label class="vault-atlas-check"><input type="checkbox" data-atlas-${name}="${esc(value)}"${checked ? " checked" : ""} /> ${esc(label)}</label>`;
}

export function atlasToolbarHtml(filters: AtlasFilters, projects: Project[], projectId: string | null): string {
  const projectOptions = [`<option value=""${projectId === null ? " selected" : ""}>Tous les projets accessibles</option>`]
    .concat(projects.map((p) => `<option value="${esc(p.id)}"${projectId === p.id ? " selected" : ""}>${esc(p.name)}</option>`))
    .join("");
  const types = ATLAS_TYPE_ORDER.map((type) =>
    checkbox("type", type, VAULT_TYPE_LABEL[type], filters.noteTypes.length === 0 || filters.noteTypes.includes(type)),
  ).join("");
  const statuses = ATLAS_STATUSES.map((status) =>
    checkbox("status", status, VAULT_STATUS_LABEL[status], filters.statuses.length === 0 || filters.statuses.includes(status)),
  ).join("");
  const scopes = (["studio", "project"] as const)
    .map((scope) => checkbox("scope", scope, scope === "studio" ? "Studio" : "Projet", filters.scopes.length === 0 || filters.scopes.includes(scope)))
    .join("");
  return `<div class="vault-atlas-toolbar" role="search" aria-label="Filtrer l'atlas">` +
    `<div class="ds-search"><span class="ds-search-icon" aria-hidden="true">⌕</span>` +
    `<label class="ds-sr-only" for="atlas-query">Rechercher dans l'atlas</label>` +
    `<input class="ds-input" type="search" id="atlas-query" value="${esc(filters.query)}" placeholder="Rechercher (plusieurs mots)…" autocomplete="off" /></div>` +
    `<label class="vault-filter"><span>Projet</span><select class="ds-select" id="atlas-project">${projectOptions}</select></label>` +
    `<button class="ds-btn ds-btn--sm" type="button" id="atlas-recenter">Recentrer</button>` +
    `<fieldset class="vault-atlas-group"><legend>Portée</legend>${scopes}</fieldset>` +
    `<fieldset class="vault-atlas-group"><legend>Type</legend>${types}</fieldset>` +
    `<fieldset class="vault-atlas-group"><legend>Statut</legend>${statuses}` +
    checkbox("toggle", "superseded", "Remplacées", filters.showSuperseded) +
    `</fieldset>` +
    `<fieldset class="vault-atlas-group"><legend>Ancres</legend>` +
    checkbox("toggle", "satellites", "Tâches et chemins", filters.showSatellites) +
    `</fieldset>` +
    `</div>`;
}

export function atlasLegendHtml(): string {
  const items = ATLAS_TYPE_ORDER.map(
    (type) => `<li><span class="vault-atlas-swatch" data-type="${esc(type)}" aria-hidden="true"></span>${esc(VAULT_TYPE_LABEL[type])}</li>`,
  ).join("");
  return `<ul class="vault-atlas-legend" aria-label="Légende">${items}` +
    `<li class="vault-atlas-legend-sep"><span class="vault-atlas-ring vault-atlas-ring--solid" aria-hidden="true"></span>Validée</li>` +
    `<li><span class="vault-atlas-ring vault-atlas-ring--dashed" aria-hidden="true"></span>Proposée</li>` +
    `<li><span class="vault-atlas-ring" aria-hidden="true"></span>Brouillon</li></ul>`;
}

export function atlasStatusLine(view: AtlasView, graph: AtlasGraph): string {
  const notes = view.clusters.length > 0
    ? view.clusters.reduce((sum, c) => sum + c.count, 0)
    : view.nodes.filter((n) => n.kind === "note").length;
  const parts = [`${notes} note(s) visible(s) sur ${graph.nodes.filter((n) => n.kind === "note").length}`];
  if (view.clusters.length > 0) parts.push(`regroupées en ${view.clusters.length} amas`);
  if (view.matches.size > 0) parts.push(`${view.matches.size} correspondance(s)`);
  if (graph.truncated) parts.push("chargement plafonné, affinez par projet");
  return `${parts.join(" — ")}.`;
}

/** Alternative clavier : correspondances d'abord, puis le reste, plafonné. */
export function atlasVisibleListHtml(view: AtlasView, selected: string | null): string {
  const notes = view.nodes.filter((n) => n.kind === "note");
  const ordered = view.matches.size > 0
    ? [...notes.filter((n) => view.matches.has(n.id)), ...notes.filter((n) => !view.matches.has(n.id))]
    : notes;
  if (ordered.length === 0) return `<p class="ds-list-sub">Aucune note visible avec ces filtres.</p>`;
  const items = ordered.slice(0, VISIBLE_LIST_MAX).map((node) =>
    `<li><button type="button" class="vault-atlas-item${node.id === selected ? " is-selected" : ""}" data-atlas-pick="${esc(node.id)}"${node.id === selected ? ' aria-current="true"' : ""}><span class="vault-atlas-dot" data-type="${esc(node.kind === "note" ? node.noteType : "anchor")}" aria-hidden="true"></span>${esc(nodeTitle(node))}</button></li>`,
  ).join("");
  const more = ordered.length > VISIBLE_LIST_MAX
    ? `<p class="ds-list-sub">${ordered.length - VISIBLE_LIST_MAX} autre(s) : affinez la recherche.</p>`
    : "";
  return `<ul class="vault-atlas-items" role="list">${items}</ul>${more}`;
}

export function atlasDetailHtml(graph: AtlasGraph, id: string | null): string {
  const node = id === null ? undefined : graph.byId.get(id);
  if (node === undefined) {
    return `<p class="ds-list-sub">Survolez ou sélectionnez une note pour voir ses liens.</p>`;
  }
  const neighborIds = [...(graph.neighbors.get(node.id) ?? [])];
  const kindOf = (other: string): string => {
    const edge = graph.edges.find((e) => (e.source === node.id && e.target === other) || (e.target === node.id && e.source === other));
    return edge === undefined ? "" : LINK_LABEL[edge.kind] ?? edge.kind;
  };
  const neighbors = neighborIds.length === 0
    ? `<p class="ds-list-sub">Aucun lien.</p>`
    : `<ul class="vault-atlas-items" role="list">${neighborIds.slice(0, 40).map((other) => {
      const target = graph.byId.get(other);
      if (target === undefined) return "";
      return `<li><button type="button" class="vault-atlas-item" data-atlas-pick="${esc(other)}">${esc(nodeTitle(target))}</button> <span class="ds-list-sub">${esc(kindOf(other))}</span></li>`;
    }).join("")}</ul>`;
  if (node.kind === "satellite") {
    const open = node.anchorType === "task"
      ? `<a class="ds-btn ds-btn--sm" href="#/tasks/${encodeURIComponent(node.label)}">Ouvrir la tâche</a>`
      : "";
    return `<h2 class="vault-atlas-detail-title">${esc(nodeTitle(node))}</h2>` +
      `<p class="ds-list-sub">${node.anchorType === "task" ? "Tâche ancrée" : "Chemin ancré"} : <code class="mono">${esc(node.label)}</code></p>` +
      `${open}<h3 class="vault-atlas-subtitle">Notes ancrées</h3>${neighbors}`;
  }
  const readable = node.readableId !== null ? `<code class="mono">${esc(node.readableId)}</code> ` : "";
  return `<h2 class="vault-atlas-detail-title">${readable}${esc(nodeTitle(node))}</h2>` +
    `<p>${dsBadge(VAULT_TYPE_LABEL[node.noteType as VaultNoteType] ?? node.noteType)} ${dsBadge(VAULT_STATUS_LABEL[node.status] ?? node.status)} ` +
    `<span class="ds-list-sub">${esc(vaultScopeLabel(node.scope))}</span></p>` +
    (node.summary.trim() === "" ? "" : `<p>${esc(node.summary)}</p>`) +
    `<a class="ds-btn ds-btn--sm ds-btn--primary" href="#/vault/${encodeURIComponent(node.id)}">Ouvrir dans la liste</a>` +
    `<h3 class="vault-atlas-subtitle">Voisins (${neighborIds.length})</h3>${neighbors}`;
}

export function atlasPageHtml(filters: AtlasFilters, projects: Project[], projectId: string | null): string {
  return header() + atlasToolbarHtml(filters, projects, projectId) +
    `<div class="vault-atlas">` +
    `<div class="vault-atlas-stage">` +
    `<div class="vault-atlas-frame">` +
    `<canvas id="atlas-canvas" class="vault-atlas-canvas" tabindex="0" role="img" aria-label="Atlas des notes du vault ; utilisez la liste « Notes visibles » pour naviguer au clavier."></canvas>` +
    `<p class="vault-atlas-hint" aria-hidden="true">Glisser : pivoter · Maj + glisser : déplacer · Molette : zoom · Double-clic : centrer</p>` +
    `</div>` +
    atlasLegendHtml() +
    `<p class="ds-list-sub vault-atlas-status" id="atlas-status" role="status" aria-live="polite"></p>` +
    `</div>` +
    `<aside class="vault-atlas-side" aria-label="Détail et notes visibles">` +
    `<section class="vault-atlas-detail" id="atlas-detail" aria-live="polite"></section>` +
    `<section><h2 class="vault-atlas-subtitle">Notes visibles</h2><div id="atlas-list"></div></section>` +
    `</aside>` +
    `</div>`;
}

/**
 * Palette par défaut, identique à `vaultAtlas.css`. Indispensable : la feuille
 * du chunk peut ne pas être appliquée au premier rendu, et une lecture CSS
 * vide retomberait sinon sur un gris uniforme.
 */
const ATLAS_TYPE_COLOR: Record<VaultNoteType, string> = {
  decision: "#5b9dff",
  rule: "#ff6b7a",
  convention: "#b58cff",
  procedure: "#3ddc97",
  reference: "#2fd4e6",
  lesson: "#ffc23d",
  note: "#a3b1c6",
};

/** Couleurs des variables CSS `--atlas-*` de `.vault-atlas`, sinon la palette par défaut. */
export function readAtlasPalette(el: Element): AtlasPalette {
  const css = getComputedStyle(el);
  const read = (name: string, fallback: string): string => css.getPropertyValue(name).trim() || fallback;
  const noteType = {} as Record<VaultNoteType, string>;
  for (const type of ATLAS_TYPE_ORDER) noteType[type] = read(NOTE_TYPE_TOKEN[type], ATLAS_TYPE_COLOR[type]);
  return {
    background: read("--atlas-bg", "#1b2540"),
    backgroundEdge: read("--atlas-bg-edge", "#0b1020"),
    text: read("--atlas-text", "#e8edf7"),
    textMuted: read("--atlas-text-muted", "#9aa8c1"),
    edge: read("--atlas-edge", "#56637d"),
    edgeStrong: read("--atlas-edge-strong", "#cbd5e1"),
    accent: read("--atlas-accent", "#ffffff"),
    noteType,
    satellite: read("--atlas-satellite", "#7c8aa5"),
    labelBackground: read("--atlas-label-bg", "rgba(11, 16, 32, 0.82)"),
  };
}

async function fetchProjects(client: StudioClient): Promise<Project[]> {
  const result = await client.GET("/api/v1/projects");
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

function prefersReducedMotion(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export async function renderVaultAtlas(root: HTMLElement, ctx: VaultAtlasContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = header() + dsEmptyState("Connectez-vous", "Saisissez votre jeton machine pour charger le vault.");
    return;
  }
  root.innerHTML = header() + dsSkeleton(4);
  const projects = await fetchProjects(ctx.client).catch(() => [] as Project[]);
  const projectNames = new Map(projects.map((p) => [p.id, p.name]));
  const filters = defaultFilters();
  let projectId: string | null = null;
  let graph: AtlasGraph;
  let view: AtlasView;
  let renderer: AtlasRenderer | null = null;
  let selected: string | null = null;
  let hovered: string | null = null;

  const load = async (): Promise<boolean> => {
    try {
      const { notes, truncated } = await loadAtlasNotes(ctx.client, { projectId });
      graph = buildAtlasGraph(notes, truncated);
      layoutAtlas(graph);
      return true;
    } catch (error) {
      renderer?.destroy();
      renderer = null;
      root.innerHTML = header() +
        `<div class="ds-notice ds-notice--danger" role="alert"><strong>Vault indisponible.</strong>${esc(describeError(error))}</div>`;
      return false;
    }
  };

  const refreshSide = (): void => {
    const detail = root.querySelector("#atlas-detail");
    if (detail !== null) detail.innerHTML = atlasDetailHtml(graph, selected ?? hovered);
    const list = root.querySelector("#atlas-list");
    if (list !== null) list.innerHTML = atlasVisibleListHtml(view, selected);
    const status = root.querySelector("#atlas-status");
    if (status !== null) status.textContent = atlasStatusLine(view, graph);
  };

  const refilter = (): void => {
    view = applyFilters(graph, filters, projectNames);
    if (selected !== null && !view.nodes.some((n) => n.id === selected)) selected = null;
    renderer?.setView(view);
    renderer?.setSelected(selected);
    refreshSide();
  };

  const select = (id: string | null): void => {
    if (id !== null && id.startsWith("cluster:")) {
      renderer?.flyTo(id);
      return;
    }
    selected = id;
    renderer?.setSelected(id);
    if (id !== null) renderer?.flyTo(id);
    refreshSide();
  };

  const mount = (): void => {
    renderer?.destroy();
    root.innerHTML = atlasPageHtml(filters, projects, projectId);
    const canvas = root.querySelector<HTMLCanvasElement>("#atlas-canvas");
    const stage = root.querySelector(".vault-atlas");
    if (canvas === null || stage === null) return;
    renderer = createAtlasRenderer(canvas, {
      palette: readAtlasPalette(stage),
      reducedMotion: prefersReducedMotion(),
      onHover: (id) => {
        hovered = id;
        if (selected === null) refreshSide();
      },
      onSelect: select,
    });
    bind(canvas);
    refilter();
  };

  const bind = (canvas: HTMLCanvasElement): void => {
    let debounce: ReturnType<typeof setTimeout> | null = null;
    const query = root.querySelector<HTMLInputElement>("#atlas-query");
    query?.addEventListener("input", () => {
      if (debounce !== null) clearTimeout(debounce);
      debounce = setTimeout(() => {
        filters.query = query.value;
        refilter();
      }, 150);
    });
    query?.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      if (debounce !== null) clearTimeout(debounce);
      filters.query = query.value;
      refilter();
      const first = [...view.matches][0];
      if (first !== undefined) select(first);
    });
    root.querySelector("#atlas-project")?.addEventListener("change", (event) => {
      projectId = (event.target as HTMLSelectElement).value || null;
      selected = null;
      void load().then((ok) => {
        if (ok) mount();
      });
    });
    root.querySelector("#atlas-recenter")?.addEventListener("click", () => renderer?.resetCamera());
    const collect = <T extends string>(attr: string): T[] =>
      [...root.querySelectorAll<HTMLInputElement>(`[data-atlas-${attr}]`)]
        .filter((box) => box.checked)
        .map((box) => box.getAttribute(`data-atlas-${attr}`) as T);
    root.querySelector(".vault-atlas-toolbar")?.addEventListener("change", (event) => {
      const box = event.target as HTMLInputElement;
      if (box.type !== "checkbox") return;
      const types = collect<VaultNoteType>("type");
      const statuses = collect<VaultNoteStatus>("status");
      filters.noteTypes = types.length === ATLAS_TYPE_ORDER.length ? [] : types;
      filters.statuses = statuses.length === ATLAS_STATUSES.length ? [] : statuses;
      const scopes = collect<"studio" | "project">("scope");
      filters.scopes = scopes.length === 2 ? [] : scopes;
      const toggles = collect<string>("toggle");
      filters.showSuperseded = toggles.includes("superseded");
      filters.showSatellites = toggles.includes("satellites");
      refilter();
    });
    root.querySelector(".vault-atlas-side")?.addEventListener("click", (event) => {
      const pick = (event.target as Element).closest<HTMLElement>("[data-atlas-pick]");
      if (pick === null) return;
      select(pick.dataset["atlasPick"] ?? null);
    });
    canvas.addEventListener("keydown", (event) => {
      if (event.key === "Escape") select(null);
      if (event.key === "/") {
        event.preventDefault();
        query?.focus();
      }
    });
  };

  if (!(await load())) return;
  mount();

  // Le canevas quitte le DOM au changement de route : on arrête le moteur.
  const onLeave = (): void => {
    if (location.hash === "#/vault/atlas" && root.contains(root.querySelector("#atlas-canvas"))) return;
    renderer?.destroy();
    renderer = null;
    window.removeEventListener("hashchange", onLeave);
  };
  window.addEventListener("hashchange", onLeave);
}
