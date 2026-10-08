/**
 * Atlas du Vault — modèle pur : graphe, disposition 3D déterministe et
 * filtres. Aucun accès DOM ni réseau ; testable en environnement node.
 */
import type { VaultNoteSummary, VaultNoteType } from "../vaultApi";
import {
  ATLAS_CLUSTER_THRESHOLD,
  type AtlasCluster,
  type AtlasEdge,
  type AtlasFilters,
  type AtlasGraph,
  type AtlasGroup,
  type AtlasNode,
  type AtlasNoteNode,
  type AtlasSatelliteNode,
  type AtlasView,
  type Vec3,
} from "./types";

/** Ordre d'affichage des types (légende, filtres, disposition). */
export const ATLAS_TYPE_ORDER: VaultNoteType[] = ["decision", "rule", "convention", "procedure", "reference", "lesson", "note"];

/** Variable CSS portant la couleur de chaque type (définie dans `vaultAtlas.css`). */
export const NOTE_TYPE_TOKEN: Record<VaultNoteType, string> = Object.fromEntries(
  ATLAS_TYPE_ORDER.map((type) => [type, `--atlas-type-${type}`]),
) as Record<VaultNoteType, string>;

const TYPE_SHORT: Record<VaultNoteType, string> = {
  decision: "Décisions",
  rule: "Règles",
  convention: "Conventions",
  procedure: "Procédures",
  reference: "Références",
  lesson: "Leçons",
  note: "Notes",
};

/** Minuscules, sans accents, espaces compactés. */
export function normalizeText(value: string): string {
  return value.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
}

/** `task:<uuid>` / `path:<chemin>` ; une ancre sans préfixe est un chemin. */
export function parseAnchor(anchor: string): { anchorType: "task" | "path"; label: string } | null {
  const value = anchor.trim();
  if (value === "") return null;
  if (value.startsWith("task:")) return { anchorType: "task", label: value.slice(5) };
  if (value.startsWith("path:")) return { anchorType: "path", label: value.slice(5) };
  return { anchorType: "path", label: value };
}

const ORIGIN = (): Vec3 => ({ x: 0, y: 0, z: 0 });

export function buildAtlasGraph(notes: VaultNoteSummary[], truncated: boolean): AtlasGraph {
  const nodes: AtlasNode[] = [];
  const byId = new Map<string, AtlasNode>();
  const neighbors = new Map<string, Set<string>>();
  const edges: AtlasEdge[] = [];
  const edgeKeys = new Set<string>();

  for (const note of notes) {
    if (byId.has(note.id)) continue;
    const node: AtlasNoteNode = {
      kind: "note",
      id: note.id,
      scope: note.scope,
      projectId: note.project_id ?? null,
      noteType: note.note_type,
      status: note.status,
      title: note.title,
      summary: note.summary,
      readableId: note.readable_id ?? null,
      slug: note.slug,
      tags: note.tags ?? [],
      position: ORIGIN(),
      radius: 1,
      searchText: normalizeText([note.readable_id ?? "", note.title, note.summary, note.slug, ...(note.tags ?? [])].join(" ")),
    };
    nodes.push(node);
    byId.set(node.id, node);
  }

  const link = (source: string, target: string, kind: AtlasEdge["kind"]): void => {
    if (source === target) return;
    const key = `${source}>${target}>${kind}`;
    if (edgeKeys.has(key)) return;
    edgeKeys.add(key);
    edges.push({ source, target, kind });
    for (const [a, b] of [[source, target], [target, source]] as const) {
      let set = neighbors.get(a);
      if (set === undefined) neighbors.set(a, (set = new Set()));
      set.add(b);
    }
  };

  for (const note of notes) {
    for (const entry of note.links ?? []) {
      if (byId.get(entry.target_note_id)?.kind === "note") link(note.id, entry.target_note_id, entry.kind ?? "links_to");
    }
    for (const raw of note.anchors ?? []) {
      const anchor = parseAnchor(raw);
      if (anchor === null) continue;
      const id = `anchor:${anchor.anchorType}:${anchor.label}`;
      if (!byId.has(id)) {
        const satellite: AtlasSatelliteNode = { kind: "satellite", id, anchorType: anchor.anchorType, label: anchor.label, position: ORIGIN(), radius: 1 };
        nodes.push(satellite);
        byId.set(id, satellite);
      }
      link(note.id, id, "anchor");
    }
  }
  return { nodes, edges, byId, neighbors, truncated };
}

/** Hachage FNV-1a 32 bits → [0, 1). Déterministe d'un rendu à l'autre. */
function hash01(value: string, salt = 0): number {
  let h = 0x811c9dc5 ^ salt;
  for (let i = 0; i < value.length; i += 1) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0) / 0x100000000;
}

export function clusterKey(node: AtlasNoteNode): string {
  return node.scope === "project" ? `cluster:project:${node.projectId ?? "?"}:${node.noteType}` : `cluster:studio:${node.noteType}`;
}

/** Écart monde entre deux notes voisines d'un même disque. */
const NODE_SPACING = 13;
/** Marge monde entre deux disques de groupe. */
const GROUP_GAP = 42;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

/** Rayon monde du disque d'un groupe de `count` notes. */
export function discRadius(count: number): number {
  return NODE_SPACING * 0.62 * Math.sqrt(count) + 8;
}

/**
 * Disposition « archipel » lisible : un disque plat par (portée/projet,
 * type), notes en tournesol (les plus liées au centre), disques empaquetés
 * sans chevauchement dans le plan XY avec un léger relief en Z. Les
 * satellites se placent en couronne près de leurs notes.
 * Mute `position` et `radius` en place.
 */
export function layoutAtlas(graph: AtlasGraph): void {
  const degree = (id: string): number => graph.neighbors.get(id)?.size ?? 0;
  for (const node of graph.nodes) {
    node.radius = node.kind === "note"
      ? (2.4 + Math.sqrt(degree(node.id)) * 0.8) * (node.noteType === "decision" ? 1.35 : 1)
      : 1.6;
  }

  const notes = graph.nodes.filter((n): n is AtlasNoteNode => n.kind === "note");
  const groups = new Map<string, AtlasNoteNode[]>();
  for (const node of notes) {
    const key = clusterKey(node);
    const list = groups.get(key);
    if (list === undefined) groups.set(key, [node]);
    else list.push(node);
  }
  const discs = [...groups.entries()]
    .map(([key, members]) => ({ key, members, radius: discRadius(members.length) }))
    .sort((a, b) => b.radius - a.radius || a.key.localeCompare(b.key));

  // Empaquetage glouton : le plus gros au centre, les autres sur des
  // anneaux croissants, première place libre trouvée.
  const placed: { x: number; y: number; r: number }[] = [];
  const centers = new Map<string, Vec3 & { r: number }>();
  for (const disc of discs) {
    let spot = { x: 0, y: 0 };
    if (placed.length > 0) {
      const free = (x: number, y: number): boolean =>
        placed.every((p) => Math.hypot(p.x - x, p.y - y) >= p.r + disc.radius + GROUP_GAP);
      search: for (let ring = 1; ring < 4000; ring += 1) {
        const dist = ring * 10;
        const steps = Math.max(12, Math.ceil((2 * Math.PI * dist) / 10));
        for (let s = 0; s < steps; s += 1) {
          const angle = (s / steps) * Math.PI * 2 + hash01(disc.key, 7) * Math.PI * 2;
          const x = Math.cos(angle) * dist;
          const y = Math.sin(angle) * dist * 0.8;
          if (free(x, y)) {
            spot = { x, y };
            break search;
          }
        }
      }
    }
    placed.push({ ...spot, r: disc.radius });
    const center = { x: spot.x, y: spot.y, z: (hash01(disc.key, 6) - 0.5) * 40 };
    centers.set(disc.key, { ...center, r: disc.radius });
    const members = [...disc.members].sort((a, b) => degree(b.id) - degree(a.id) || a.id.localeCompare(b.id));
    const step = NODE_SPACING * 0.62;
    members.forEach((node, i) => {
      const r = members.length === 1 ? 0 : step * Math.sqrt(i + 0.5);
      const angle = i * GOLDEN_ANGLE;
      node.position = {
        x: center.x + Math.cos(angle) * r,
        y: center.y + Math.sin(angle) * r,
        z: center.z + (hash01(node.id, 3) - 0.5) * 8,
      };
    });
  }

  for (const node of graph.nodes) {
    if (node.kind !== "satellite") continue;
    const linked = [...(graph.neighbors.get(node.id) ?? [])]
      .map((id) => graph.byId.get(id))
      .filter((n): n is AtlasNoteNode => n !== undefined && n.kind === "note")
      .sort((a, b) => a.id.localeCompare(b.id));
    if (linked.length === 0) continue;
    const c = linked.reduce((acc, n) => ({ x: acc.x + n.position.x, y: acc.y + n.position.y, z: acc.z + n.position.z }), ORIGIN());
    const mean = { x: c.x / linked.length, y: c.y / linked.length, z: c.z / linked.length };
    const home = centers.get(clusterKey(linked[0]!)) ?? { ...ORIGIN(), r: 0 };
    let dx = mean.x - home.x;
    let dy = mean.y - home.y;
    let len = Math.hypot(dx, dy);
    if (len < 1) {
      const a = hash01(node.id, 4) * Math.PI * 2;
      dx = Math.cos(a);
      dy = Math.sin(a);
      len = 1;
    }
    // Couronne juste à l'extérieur du disque, dans la direction des notes liées.
    const out = home.r + 10 + hash01(node.id, 5) * 14;
    node.position = { x: home.x + (dx / len) * out, y: home.y + (dy / len) * out, z: mean.z + 4 };
  }
}

export function defaultFilters(): AtlasFilters {
  return { noteTypes: [], statuses: [], scopes: [], showSuperseded: false, showSatellites: false, query: "" };
}

function noteVisible(node: AtlasNoteNode, filters: AtlasFilters): boolean {
  if (filters.noteTypes.length > 0 && !filters.noteTypes.includes(node.noteType)) return false;
  if (filters.scopes.length > 0 && !filters.scopes.includes(node.scope)) return false;
  if (node.status === "superseded") return filters.showSuperseded;
  return filters.statuses.length === 0 || filters.statuses.includes(node.status);
}

/** Groupes (portée/projet × type) des notes visibles, pour les étiquettes flottantes. */
export function atlasGroups(notes: AtlasNoteNode[], projectNames?: ReadonlyMap<string, string>): AtlasGroup[] {
  const groups = new Map<string, AtlasNoteNode[]>();
  for (const node of notes) {
    const key = clusterKey(node);
    const list = groups.get(key);
    if (list === undefined) groups.set(key, [node]);
    else list.push(node);
  }
  return [...groups.entries()].map(([id, members]) => {
    const first = members[0]!;
    const sum = members.reduce((acc, n) => ({ x: acc.x + n.position.x, y: acc.y + n.position.y, z: acc.z + n.position.z }), ORIGIN());
    const center = { x: sum.x / members.length, y: sum.y / members.length, z: sum.z / members.length };
    const radius = members.reduce((max, n) => Math.max(max, Math.hypot(n.position.x - center.x, n.position.y - center.y) + n.radius), 4);
    const owner = first.scope === "studio" ? "Studio" : projectNames?.get(first.projectId ?? "") ?? "Projet";
    return { id, noteType: first.noteType, label: `${owner} · ${TYPE_SHORT[first.noteType]} (${members.length})`, count: members.length, center, radius };
  });
}

/** Pur : ce que le moteur doit dessiner pour ces filtres. */
export function applyFilters(graph: AtlasGraph, filters: AtlasFilters, projectNames?: ReadonlyMap<string, string>): AtlasView {
  const tokens = normalizeText(filters.query).split(" ").filter((t) => t !== "");
  const visibleNotes = graph.nodes.filter((n): n is AtlasNoteNode => n.kind === "note" && noteVisible(n, filters));
  const matches = new Set<string>();
  if (tokens.length > 0) {
    for (const node of visibleNotes) if (tokens.every((t) => node.searchText.includes(t))) matches.add(node.id);
  }

  if (visibleNotes.length > ATLAS_CLUSTER_THRESHOLD) {
    const groups = new Map<string, AtlasNoteNode[]>();
    for (const node of visibleNotes) {
      const key = clusterKey(node);
      const list = groups.get(key);
      if (list === undefined) groups.set(key, [node]);
      else list.push(node);
    }
    const clusters: AtlasCluster[] = [...groups.entries()].map(([id, members]) => {
      const first = members[0]!;
      const sum = members.reduce((acc, n) => ({ x: acc.x + n.position.x, y: acc.y + n.position.y, z: acc.z + n.position.z }), ORIGIN());
      return {
        id,
        scope: first.scope,
        noteType: first.noteType,
        label: `${TYPE_SHORT[first.noteType]} · ${members.length}`,
        count: members.length,
        members: members.map((m) => m.id),
        position: { x: sum.x / members.length, y: sum.y / members.length, z: sum.z / members.length },
        radius: 4 + Math.sqrt(members.length) * 0.9,
      };
    });
    // Repli : seules les correspondances restent dessinées individuellement.
    const nodes = visibleNotes.filter((n) => matches.has(n.id));
    return { nodes, edges: [], clusters, matches, groups: [] };
  }

  const visible = new Set<string>(visibleNotes.map((n) => n.id));
  const nodes: AtlasNode[] = [...visibleNotes];
  if (filters.showSatellites) {
    for (const node of graph.nodes) {
      if (node.kind !== "satellite") continue;
      if ([...(graph.neighbors.get(node.id) ?? [])].some((id) => visible.has(id))) {
        nodes.push(node);
        visible.add(node.id);
      }
    }
  }
  const edges = graph.edges.filter((e) => visible.has(e.source) && visible.has(e.target));
  return { nodes, edges, clusters: [], matches, groups: atlasGroups(visibleNotes, projectNames) };
}
