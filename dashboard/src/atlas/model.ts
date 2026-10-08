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

/** Point `i` sur `n` d'une sphère de Fibonacci de rayon `r`. */
function fibonacci(i: number, n: number, r: number): Vec3 {
  if (n <= 1) return ORIGIN();
  const y = 1 - (2 * (i + 0.5)) / n;
  const ring = Math.sqrt(1 - y * y);
  const theta = i * Math.PI * (3 - Math.sqrt(5));
  return { x: Math.cos(theta) * ring * r, y: y * r, z: Math.sin(theta) * ring * r };
}

export function clusterKey(node: AtlasNoteNode): string {
  return node.scope === "project" ? `cluster:project:${node.projectId ?? "?"}:${node.noteType}` : `cluster:studio:${node.noteType}`;
}

/**
 * Disposition : un amas par (portée/projet, type) réparti sur une sphère,
 * notes en spirale autour du centre de leur amas, puis quelques passes de
 * ressorts le long des liens. Les satellites se placent près de leurs notes.
 * Mute `position` et `radius` en place.
 */
export function layoutAtlas(graph: AtlasGraph): void {
  const notes = graph.nodes.filter((n): n is AtlasNoteNode => n.kind === "note");
  const groups = new Map<string, AtlasNoteNode[]>();
  for (const node of notes) {
    const key = clusterKey(node);
    const list = groups.get(key);
    if (list === undefined) groups.set(key, [node]);
    else list.push(node);
  }
  const keys = [...groups.keys()].sort((a, b) => {
    const ta = ATLAS_TYPE_ORDER.indexOf(groups.get(a)![0]!.noteType);
    const tb = ATLAS_TYPE_ORDER.indexOf(groups.get(b)![0]!.noteType);
    return a.split(":").slice(0, -1).join(":").localeCompare(b.split(":").slice(0, -1).join(":")) || ta - tb;
  });
  const shell = 40 + 28 * Math.cbrt(notes.length);
  keys.forEach((key, index) => {
    const members = groups.get(key)!.sort((a, b) => a.id.localeCompare(b.id));
    const center = fibonacci(index, keys.length, shell);
    const spread = 6 + 7 * Math.cbrt(members.length);
    members.forEach((node, i) => {
      const local = fibonacci(i, members.length, spread * Math.cbrt((i + 1) / members.length));
      node.position = {
        x: center.x + local.x + (hash01(node.id, 1) - 0.5) * 4,
        y: center.y + local.y + (hash01(node.id, 2) - 0.5) * 4,
        z: center.z + local.z + (hash01(node.id, 3) - 0.5) * 4,
      };
    });
  });

  // Ressorts : rapproche les notes liées sans écraser les amas (O(E) par passe).
  const noteEdges = graph.edges.filter((e) => e.kind !== "anchor");
  for (let pass = 0; pass < 12; pass += 1) {
    for (const edge of noteEdges) {
      const a = graph.byId.get(edge.source);
      const b = graph.byId.get(edge.target);
      if (a === undefined || b === undefined) continue;
      const dx = b.position.x - a.position.x;
      const dy = b.position.y - a.position.y;
      const dz = b.position.z - a.position.z;
      const dist = Math.hypot(dx, dy, dz) || 1;
      const pull = Math.max(0, dist - 18) * 0.03 / dist;
      a.position = { x: a.position.x + dx * pull, y: a.position.y + dy * pull, z: a.position.z + dz * pull };
      b.position = { x: b.position.x - dx * pull, y: b.position.y - dy * pull, z: b.position.z - dz * pull };
    }
  }

  for (const node of graph.nodes) {
    const degree = graph.neighbors.get(node.id)?.size ?? 0;
    if (node.kind === "note") {
      node.radius = (2.4 + Math.sqrt(degree) * 0.8) * (node.noteType === "decision" ? 1.35 : 1);
      continue;
    }
    node.radius = 1.6;
    const linked = [...(graph.neighbors.get(node.id) ?? [])].map((id) => graph.byId.get(id)).filter((n) => n !== undefined);
    if (linked.length === 0) continue;
    const c = linked.reduce((acc, n) => ({ x: acc.x + n.position.x, y: acc.y + n.position.y, z: acc.z + n.position.z }), ORIGIN());
    const len = Math.hypot(c.x, c.y, c.z) || 1;
    const out = 10 + hash01(node.id, 4) * 6;
    node.position = {
      x: c.x / linked.length + (c.x / len) * out,
      y: c.y / linked.length + (c.y / len) * out + (hash01(node.id, 5) - 0.5) * 6,
      z: c.z / linked.length + (c.z / len) * out,
    };
  }
}

export function defaultFilters(): AtlasFilters {
  return { noteTypes: [], statuses: [], scopes: [], showSuperseded: false, showSatellites: true, query: "" };
}

function noteVisible(node: AtlasNoteNode, filters: AtlasFilters): boolean {
  if (filters.noteTypes.length > 0 && !filters.noteTypes.includes(node.noteType)) return false;
  if (filters.scopes.length > 0 && !filters.scopes.includes(node.scope)) return false;
  if (node.status === "superseded") return filters.showSuperseded;
  return filters.statuses.length === 0 || filters.statuses.includes(node.status);
}

/** Pur : ce que le moteur doit dessiner pour ces filtres. */
export function applyFilters(graph: AtlasGraph, filters: AtlasFilters): AtlasView {
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
    return { nodes, edges: [], clusters, matches };
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
  return { nodes, edges, clusters: [], matches };
}
