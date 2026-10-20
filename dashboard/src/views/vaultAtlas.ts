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
import {
  applyFilters,
  ATLAS_COMMUNITY_COLORS,
  ATLAS_TYPE_ORDER,
  ATLAS_ZONE_COLORS,
  buildAtlasGraph,
  defaultFilters,
  layoutAtlas,
  NOTE_TYPE_TOKEN,
} from "../atlas/model";
import { createAtlasRenderer } from "../atlas/renderer";
import type {
  AtlasFilters,
  AtlasGraph,
  AtlasNode,
  AtlasPalette,
  AtlasProjection,
  AtlasRenderer,
  AtlasView,
} from "../atlas/types";
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

export const ATLAS_MODE_STORAGE_KEY = "studio.vault.atlas.mode";
export const ATLAS_MODE_LABEL: Record<AtlasProjection, string> = { "2d": "Vue 2D", "3d": "Vue 3D" };

export interface AtlasTimings {
  buildMs: number;
  layoutMs: number;
  filterMs: number;
  drawMs: number;
}

export function measureAtlasStep<T>(label: string, fn: () => T): { value: T; ms: number } {
  const name = `studio:vault-atlas:${label}`;
  const startMark = `${name}:start`;
  const endMark = `${name}:end`;
  const start = typeof performance !== "undefined" ? performance.now() : 0;
  try {
    performance.mark(startMark);
  } catch {
  }
  const value = fn();
  const ms = (typeof performance !== "undefined" ? performance.now() : 0) - start;
  try {
    performance.mark(endMark);
    performance.measure(name, startMark, endMark);
    performance.clearMarks(startMark);
    performance.clearMarks(endMark);
    performance.clearMeasures(name);
  } catch {
  }
  return { value, ms };
}

export function atlasPerfText(notes: number, edges: number, timings: AtlasTimings): string {
  return `${notes} note(s) · ${edges} lien(s) · construction ${timings.buildMs.toFixed(1)} ms` +
    ` · disposition ${timings.layoutMs.toFixed(1)} ms · filtre ${timings.filterMs.toFixed(1)} ms` +
    ` · dessin ${timings.drawMs.toFixed(1)} ms`;
}

export function readAtlasMode(storage?: Storage | null): AtlasProjection {
  try {
    const store = storage ?? (typeof localStorage !== "undefined" ? localStorage : null);
    return store?.getItem(ATLAS_MODE_STORAGE_KEY) === "2d" ? "2d" : "3d";
  } catch {
    return "3d";
  }
}

export function writeAtlasMode(mode: AtlasProjection, storage?: Storage | null): void {
  try {
    const store = storage ?? (typeof localStorage !== "undefined" ? localStorage : null);
    store?.setItem(ATLAS_MODE_STORAGE_KEY, mode);
  } catch {
  }
}

export function toggleAtlasMode(mode: AtlasProjection): AtlasProjection {
  return mode === "2d" ? "3d" : "2d";
}

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

export function atlasToolbarHtml(
  filters: AtlasFilters,
  projects: Project[],
  projectId: string | null,
  mode: AtlasProjection = "3d",
): string {
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
    `<button class="ds-btn ds-btn--sm" type="button" id="atlas-projection" aria-pressed="${mode === "2d" ? "true" : "false"}" title="Basculer entre la vue perspective (3D) et la vue à plat (2D)">${ATLAS_MODE_LABEL[mode]}</button>` +
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
    `<li><span class="vault-atlas-ring" aria-hidden="true"></span>Brouillon</li>` +
    `<li class="vault-atlas-legend-sep"><span class="vault-atlas-zone-ring" aria-hidden="true"></span>Zone (portée × type)</li>` +
    `<li><span class="vault-atlas-community-swatch" aria-hidden="true"></span>Communauté de liens</li></ul>`;
}

export function atlasStatusLine(view: AtlasView, graph: AtlasGraph, selected: string | null = null): string {
  const notes = view.clusters.length > 0
    ? view.clusters.reduce((sum, c) => sum + c.count, 0)
    : view.nodes.filter((n) => n.kind === "note").length;
  const parts = [`${notes} note(s) visible(s) sur ${graph.nodes.filter((n) => n.kind === "note").length}`];
  if (view.clusters.length > 0) parts.push(`regroupées en ${view.clusters.length} amas`);
  if (view.groups.length > 0) parts.push(`${view.groups.length} zone(s)`);
  if (view.communities.length > 0) parts.push(`${view.communities.length} communauté(s)`);
  if (view.matches.size > 0) parts.push(`${view.matches.size} correspondance(s)`);
  if (selected !== null) {
    const neighbors = graph.neighbors.get(selected)?.size ?? 0;
    if (neighbors > 0) parts.push(`${neighbors} voisin(s) surligné(s)`);
  }
  if (graph.truncated) parts.push("chargement plafonné, affinez par projet");
  return `${parts.join(" — ")}.`;
}

/** Alternative clavier : correspondances d'abord, puis le reste, plafonné. */
export function atlasVisibleListHtml(view: AtlasView, selected: string | null, graph?: AtlasGraph): string {
  const notes = view.nodes.filter((n) => n.kind === "note");
  const ordered = view.matches.size > 0
    ? [...notes.filter((n) => view.matches.has(n.id)), ...notes.filter((n) => !view.matches.has(n.id))]
    : notes;
  if (ordered.length === 0) return `<p class="ds-list-sub">Aucune note visible avec ces filtres.</p>`;
  const neighbors = selected === null ? new Set<string>() : graph?.neighbors.get(selected) ?? new Set<string>();
  const items = ordered.slice(0, VISIBLE_LIST_MAX).map((node) => {
    const isSelected = node.id === selected;
    const isNeighbor = !isSelected && neighbors.has(node.id);
    const classes = `vault-atlas-item${isSelected ? " is-selected" : ""}${isNeighbor ? " is-neighbor" : ""}`;
    return `<li><button type="button" class="${classes}" data-atlas-pick="${esc(node.id)}"${isSelected ? ' aria-current="true"' : ""}><span class="vault-atlas-dot" data-type="${esc(node.kind === "note" ? node.noteType : "anchor")}" aria-hidden="true"></span>${esc(nodeTitle(node))}${isNeighbor ? ' <span class="vault-atlas-neighbor">voisin</span>' : ""}</button></li>`;
  }).join("");
  const more = ordered.length > VISIBLE_LIST_MAX
    ? `<p class="ds-list-sub">${ordered.length - VISIBLE_LIST_MAX} autre(s) : affinez la recherche.</p>`
    : "";
  return `<ul class="vault-atlas-items" role="list">${items}</ul>${more}`;
}

export function atlasRegionsHtml(view: AtlasView): string {
  if (view.groups.length === 0 && view.communities.length === 0) {
    return `<p class="ds-list-sub">Aucune zone avec ces filtres.</p>`;
  }
  const zones = view.groups
    .map(
      (group) =>
        `<li><span class="vault-atlas-region-dot" data-zone-color="${group.colorIndex % ATLAS_ZONE_COLORS.length}" aria-hidden="true"></span>` +
        `<span class="vault-atlas-region-label">${esc(group.label)}</span></li>`,
    )
    .join("");
  const communities = view.communities
    .map(
      (community) =>
        `<li><span class="vault-atlas-region-dot" data-community-color="${community.colorIndex % ATLAS_COMMUNITY_COLORS.length}" aria-hidden="true"></span>` +
        `<button type="button" class="vault-atlas-region-link" data-atlas-pick="${esc(community.members[0] ?? "")}">${esc(community.label)}</button></li>`,
    )
    .join("");
  return `<h3 class="vault-atlas-region-title">Zones (${view.groups.length})</h3>` +
    (zones === "" ? `<p class="ds-list-sub">Aucune zone.</p>` : `<ul class="vault-atlas-regions" role="list">${zones}</ul>`) +
    (communities === ""
      ? ""
      : `<h3 class="vault-atlas-region-title">Communautés (${view.communities.length})</h3>` +
        `<ul class="vault-atlas-regions" role="list">${communities}</ul>`);
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

export function atlasHintText(mode: AtlasProjection): string {
  return mode === "2d"
    ? "Glisser : déplacer · Molette : zoom · Flèches : notes · Entrée : sélection · Échap : effacer"
    : "Glisser : pivoter · Maj + glisser : déplacer · Molette : zoom · Flèches : notes · Entrée : sélection · Échap : effacer";
}

export function atlasPageHtml(
  filters: AtlasFilters,
  projects: Project[],
  projectId: string | null,
  mode: AtlasProjection = "3d",
): string {
  return header() + atlasToolbarHtml(filters, projects, projectId, mode) +
    `<div class="vault-atlas" data-atlas-mode="${mode}">` +
    `<div class="vault-atlas-stage">` +
    `<div class="vault-atlas-frame">` +
    `<canvas id="atlas-canvas" class="vault-atlas-canvas" tabindex="0" role="img" aria-label="Atlas des notes du vault ; utilisez la liste « Notes visibles » pour naviguer au clavier."></canvas>` +
    `<p class="vault-atlas-hint" id="atlas-hint" aria-hidden="true">${esc(atlasHintText(mode))}</p>` +
    `</div>` +
    atlasLegendHtml() +
    `<p class="ds-list-sub vault-atlas-status" id="atlas-status" role="status" aria-live="polite"></p>` +
    `<p class="ds-list-sub vault-atlas-perf" id="atlas-perf" hidden></p>` +
    `</div>` +
    `<aside class="vault-atlas-side" aria-label="Détail et notes visibles">` +
    `<section class="vault-atlas-detail" id="atlas-detail" aria-live="polite"></section>` +
    `<section><h2 class="vault-atlas-subtitle">Zones et communautés</h2><div id="atlas-regions"></div></section>` +
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
  const zones = ATLAS_ZONE_COLORS.map((fallback, index) => read(`--atlas-zone-${index + 1}`, fallback));
  const communities = ATLAS_COMMUNITY_COLORS.map((fallback, index) => read(`--atlas-community-${index + 1}`, fallback));
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
    zones,
    communities,
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
  let atlasMode = readAtlasMode();
  const timings: AtlasTimings = { buildMs: 0, layoutMs: 0, filterMs: 0, drawMs: 0 };
  let graph: AtlasGraph;
  let view: AtlasView;
  let renderer: AtlasRenderer | null = null;
  let selected: string | null = null;
  let hovered: string | null = null;

  const updatePerf = (): void => {
    const host = root.querySelector<HTMLElement>("#atlas-perf");
    if (host === null) return;
    if (!import.meta.env.DEV) {
      host.hidden = true;
      host.textContent = "";
      return;
    }
    const noteCount = graph.nodes.filter((node) => node.kind === "note").length;
    host.textContent = atlasPerfText(noteCount, graph.edges.length, timings);
    host.hidden = false;
  };

  const load = async (): Promise<boolean> => {
    try {
      const { notes, truncated } = await loadAtlasNotes(ctx.client, { projectId });
      const built = measureAtlasStep("build", () => buildAtlasGraph(notes, truncated));
      graph = built.value;
      timings.buildMs = built.ms;
      const laid = measureAtlasStep("layout", () => layoutAtlas(graph));
      timings.layoutMs = laid.ms;
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
    if (list !== null) list.innerHTML = atlasVisibleListHtml(view, selected, graph);
    const regions = root.querySelector("#atlas-regions");
    if (regions !== null) regions.innerHTML = atlasRegionsHtml(view);
    const status = root.querySelector("#atlas-status");
    if (status !== null) status.textContent = atlasStatusLine(view, graph, selected);
    updatePerf();
  };

  const refilter = (): void => {
    const filtered = measureAtlasStep("filter", () => applyFilters(graph, filters, projectNames));
    view = filtered.value;
    timings.filterMs = filtered.ms;
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
    root.innerHTML = atlasPageHtml(filters, projects, projectId, atlasMode);
    const canvas = root.querySelector<HTMLCanvasElement>("#atlas-canvas");
    const stage = root.querySelector(".vault-atlas");
    if (canvas === null || stage === null) return;
    renderer = createAtlasRenderer(canvas, {
      palette: readAtlasPalette(stage),
      reducedMotion: prefersReducedMotion(),
      mode: atlasMode,
      onHover: (id) => {
        hovered = id;
        if (selected === null) refreshSide();
      },
      onSelect: select,
      onRender: (ms) => {
        timings.drawMs = ms;
        updatePerf();
      },
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
    root.querySelector("#atlas-projection")?.addEventListener("click", () => {
      atlasMode = toggleAtlasMode(atlasMode);
      writeAtlasMode(atlasMode);
      renderer?.setMode(atlasMode);
      const stage = root.querySelector(".vault-atlas");
      stage?.setAttribute("data-atlas-mode", atlasMode);
      const button = root.querySelector<HTMLButtonElement>("#atlas-projection");
      if (button !== null) {
        button.textContent = ATLAS_MODE_LABEL[atlasMode];
        button.setAttribute("aria-pressed", atlasMode === "2d" ? "true" : "false");
      }
      const hint = root.querySelector("#atlas-hint");
      if (hint !== null) hint.textContent = atlasHintText(atlasMode);
    });
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
    const navIds = (): string[] => {
      const notes = view.nodes.filter((node) => node.kind === "note");
      const ordered = view.matches.size > 0
        ? [...notes.filter((node) => view.matches.has(node.id)), ...notes.filter((node) => !view.matches.has(node.id))]
        : notes;
      return ordered.map((node) => node.id);
    };

    const moveSelection = (delta: number): void => {
      const ids = navIds();
      if (ids.length === 0) return;
      const current = selected === null ? -1 : ids.indexOf(selected);
      const base = current < 0 ? (delta > 0 ? -1 : 0) : current;
      const next = (base + delta + ids.length) % ids.length;
      select(ids[next] ?? null);
    };

    canvas.addEventListener("keydown", (event) => {
      if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
      switch (event.key) {
        case "ArrowRight":
        case "ArrowDown":
          event.preventDefault();
          moveSelection(1);
          break;
        case "ArrowLeft":
        case "ArrowUp":
          event.preventDefault();
          moveSelection(-1);
          break;
        case "Enter":
          event.preventDefault();
          if (selected === null) moveSelection(1);
          else select(selected);
          break;
        case "Escape":
          event.preventDefault();
          select(null);
          break;
        case "/":
          event.preventDefault();
          query?.focus();
          break;
        default:
          break;
      }
    });

    root.querySelector<HTMLElement>(".vault-atlas-side")?.addEventListener("keydown", (event: KeyboardEvent) => {
      const items = [...root.querySelectorAll<HTMLButtonElement>("#atlas-list [data-atlas-pick]")];
      if (event.key === "Escape") {
        event.preventDefault();
        select(null);
        canvas.focus();
        return;
      }
      if (items.length === 0) return;
      const index = items.indexOf(document.activeElement as HTMLButtonElement);
      let target: number | null = null;
      if (event.key === "ArrowDown") target = index < 0 ? 0 : (index + 1) % items.length;
      else if (event.key === "ArrowUp") target = index < 0 ? items.length - 1 : (index - 1 + items.length) % items.length;
      else if (event.key === "Home") target = 0;
      else if (event.key === "End") target = items.length - 1;
      if (target === null) return;
      event.preventDefault();
      items[target]?.focus();
    });
  };

  if (!(await load())) return;
  mount();

  // Le canevas quitte le DOM au changement de route : on arrête le moteur.
  const stopWhenLeft = (): void => {
    if (location.hash === "#/vault/atlas" && root.contains(root.querySelector("#atlas-canvas"))) return;
    renderer?.destroy();
    renderer = null;
    window.removeEventListener("hashchange", stopWhenLeft);
  };
  window.addEventListener("hashchange", stopWhenLeft);
}
