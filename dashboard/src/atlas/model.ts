/**
 * Atlas du Vault — modèle pur : graphe, disposition 3D déterministe et
 * filtres. Aucun accès DOM ni réseau ; testable en environnement node.
 */
import type { VaultNoteSummary, VaultNoteType } from "../vaultApi";
import {
  ATLAS_CLUSTER_THRESHOLD,
  type AtlasCluster,
  type AtlasCommunity,
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

export const ATLAS_ZONE_COLORS = ["#5b9dff", "#3ddc97", "#ffc23d", "#b58cff", "#2fd4e6"];
export const ATLAS_COMMUNITY_COLORS = ["#f472b6", "#38bdf8", "#facc15", "#a3e635", "#fb923c", "#c084fc"];

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

export function zoneColorIndex(scope: AtlasNoteNode["scope"], projectId: string | null): number {
  if (scope === "studio") return 0;
  const span = Math.max(1, ATLAS_ZONE_COLORS.length - 1);
  return 1 + Math.floor(hash01(projectId ?? "?", 11) * span) % span;
}

/** Écart monde visé entre deux notes voisines d'une même boule. */
const NODE_SPACING = 13;
/** Marge monde entre deux boules de groupe. */
const GROUP_GAP = 36;
/** Suite R2 (constante plastique) : directions quasi uniformes sur la sphère. */
const R2_A = 0.7548776662466927;
const R2_B = 0.5698402909980532;

/** Rayon monde de la boule d'un groupe de `count` notes. */
export function groupRadius(count: number): number {
  return NODE_SPACING * 0.78 * Math.cbrt(count) + 6;
}

/** `i`-ème direction unitaire quasi uniforme (suite R2 projetée sur la sphère). */
function sphereDirection(i: number, seed = 0): Vec3 {
  const u = (seed + (i + 0.5) * R2_A) % 1;
  const v = (seed * 0.5 + (i + 0.5) * R2_B) % 1;
  const z = 1 - 2 * u;
  const rho = Math.sqrt(Math.max(0, 1 - z * z));
  const theta = v * Math.PI * 2;
  return { x: rho * Math.cos(theta), y: z, z: rho * Math.sin(theta) };
}

/** `i`-ème point sur `n` d'une sphère de Fibonacci (répartition régulière). */
function fibonacciDirection(i: number, n: number): Vec3 {
  const y = n === 1 ? 1 : 1 - (2 * (i + 0.5)) / n;
  const rho = Math.sqrt(Math.max(0, 1 - y * y));
  const theta = i * Math.PI * (3 - Math.sqrt(5));
  return { x: rho * Math.cos(theta), y, z: rho * Math.sin(theta) };
}

/**
 * Disposition sphérique : une boule par (portée/projet, type), notes
 * réparties en volume (les plus liées au centre). Le plus gros groupe
 * occupe le cœur, les autres se répartissent sur une coquille englobante
 * sans chevauchement. Les satellites se placent juste hors de la boule de
 * leurs notes. Mute `position` et `radius` en place.
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
    .map(([key, members]) => ({ key, members, radius: groupRadius(members.length) }))
    .sort((a, b) => b.radius - a.radius || a.key.localeCompare(b.key));

  // Le plus gros groupe au cœur ; les autres sur une coquille de Fibonacci,
  // agrandie jusqu'à ce qu'aucune boule n'en chevauche une autre.
  const centers = new Map<string, Vec3 & { r: number }>();
  const [core, ...shell] = discs;
  if (core !== undefined) centers.set(core.key, { ...ORIGIN(), r: core.radius });
  if (shell.length > 0) {
    const coreRadius = core?.radius ?? 0;
    const outer = Math.max(...shell.map((d) => d.radius));
    // Rotation propre à l'ensemble des groupes : la coquille ne commence pas toujours au pôle.
    const spin = hash01(shell.map((d) => d.key).join("|"), 7) * Math.PI * 2;
    const spots = shell.map((_, i) => {
      const d = fibonacciDirection(i, shell.length);
      return { x: d.x * Math.cos(spin) - d.z * Math.sin(spin), y: d.y, z: d.x * Math.sin(spin) + d.z * Math.cos(spin) };
    });
    let distance = coreRadius + outer + GROUP_GAP;
    const fits = (): boolean => shell.every((a, i) => shell.every((b, j) =>
      j <= i || Math.hypot(
        (spots[i]!.x - spots[j]!.x) * distance,
        (spots[i]!.y - spots[j]!.y) * distance,
        (spots[i]!.z - spots[j]!.z) * distance,
      ) >= a.radius + b.radius + GROUP_GAP));
    while (!fits() && distance < 100_000) distance *= 1.08;
    shell.forEach((disc, i) => {
      const s = spots[i]!;
      centers.set(disc.key, { x: s.x * distance, y: s.y * distance, z: s.z * distance, r: disc.radius });
    });
  }

  for (const disc of discs) {
    const center = centers.get(disc.key)!;
    const members = [...disc.members].sort((a, b) => degree(b.id) - degree(a.id) || a.id.localeCompare(b.id));
    const seed = hash01(disc.key, 3);
    const span = disc.radius - 6;
    members.forEach((node, i) => {
      const r = members.length === 1 ? 0 : span * Math.cbrt((i + 0.5) / members.length);
      const d = sphereDirection(i, seed);
      node.position = { x: center.x + d.x * r, y: center.y + d.y * r, z: center.z + d.z * r };
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
    let dir = { x: mean.x - home.x, y: mean.y - home.y, z: mean.z - home.z };
    let len = Math.hypot(dir.x, dir.y, dir.z);
    if (len < 1) {
      dir = sphereDirection(0, hash01(node.id, 4));
      len = 1;
    }
    // Couronne juste à l'extérieur de la boule, dans la direction des notes liées.
    const out = home.r + 10 + hash01(node.id, 5) * 14;
    node.position = { x: home.x + (dir.x / len) * out, y: home.y + (dir.y / len) * out, z: home.z + (dir.z / len) * out };
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
    const radius = members.reduce((max, n) => Math.max(max, Math.hypot(n.position.x - center.x, n.position.y - center.y, n.position.z - center.z) + n.radius), 4);
    const owner = first.scope === "studio" ? "Studio" : projectNames?.get(first.projectId ?? "") ?? "Projet";
    return {
      id,
      noteType: first.noteType,
      label: `${owner} · ${TYPE_SHORT[first.noteType]} (${members.length})`,
      count: members.length,
      center,
      radius,
      colorIndex: zoneColorIndex(first.scope, first.projectId),
    };
  });
}

export function atlasCommunities(notes: AtlasNoteNode[], edges: AtlasEdge[]): AtlasCommunity[] {
  const byId = new Map(notes.map((note) => [note.id, note]));
  const adjacency = new Map<string, Set<string>>();
  for (const edge of edges) {
    if (edge.kind === "anchor") continue;
    if (!byId.has(edge.source) || !byId.has(edge.target)) continue;
    for (const [a, b] of [[edge.source, edge.target], [edge.target, edge.source]] as const) {
      let set = adjacency.get(a);
      if (set === undefined) adjacency.set(a, (set = new Set()));
      set.add(b);
    }
  }

  const seen = new Set<string>();
  const components: string[][] = [];
  for (const note of notes) {
    if (seen.has(note.id) || !adjacency.has(note.id)) continue;
    const stack = [note.id];
    const members: string[] = [];
    seen.add(note.id);
    while (stack.length > 0) {
      const id = stack.pop()!;
      members.push(id);
      for (const next of adjacency.get(id) ?? []) {
        if (seen.has(next)) continue;
        seen.add(next);
        stack.push(next);
      }
    }
    if (members.length >= 2) components.push(members.sort());
  }

  components.sort((a, b) => b.length - a.length || a[0]!.localeCompare(b[0]!));
  return components.map((members, index) => {
    const nodes = members.map((id) => byId.get(id)!).filter((node) => node !== undefined);
    const counts = new Map<VaultNoteType, number>();
    for (const node of nodes) counts.set(node.noteType, (counts.get(node.noteType) ?? 0) + 1);
    const dominant = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]?.[0] ?? "note";
    const sum = nodes.reduce((acc, n) => ({ x: acc.x + n.position.x, y: acc.y + n.position.y, z: acc.z + n.position.z }), ORIGIN());
    const center = { x: sum.x / nodes.length, y: sum.y / nodes.length, z: sum.z / nodes.length };
    const radius = nodes.reduce((max, n) => Math.max(max, Math.hypot(n.position.x - center.x, n.position.y - center.y, n.position.z - center.z) + n.radius), 6);
    return {
      id: `community:${members[0]}`,
      label: `Communauté ${index + 1} · ${TYPE_SHORT[dominant]} (${members.length})`,
      count: members.length,
      members,
      position: center,
      radius: radius + 10,
      colorIndex: index % ATLAS_COMMUNITY_COLORS.length,
    };
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
    return { nodes, edges: [], clusters, matches, groups: [], communities: [] };
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
  return {
    nodes,
    edges,
    clusters: [],
    matches,
    groups: atlasGroups(visibleNotes, projectNames),
    communities: atlasCommunities(visibleNotes, edges),
  };
}
