/**
 * Atlas du Vault — contrat partagé entre le modèle (`model.ts`), le moteur
 * Canvas (`renderer.ts`) et la vue (`views/vaultAtlas.ts`).
 *
 * Données : uniquement `GET /vault/tree` (résumés sans corps, liens et
 * ancres inclus), paginé et borné par `ATLAS_MAX_NOTES`. Aucune fixture en
 * production, aucune dépendance runtime.
 */
import type { VaultNoteStatus, VaultNoteType, VaultScope } from "../vaultApi";

export type AtlasLinkKind = "links_to" | "relates_to" | "derived_from" | "supersedes";

/** Arête « anchor » : note → satellite (tâche ou chemin ancré). */
export type AtlasEdgeKind = AtlasLinkKind | "anchor";

/** Plafond de notes chargées (pages de 200 via le curseur de /vault/tree). */
export const ATLAS_MAX_NOTES = 2000;
/** Au-delà de ce nombre de notes visibles, repli en bulles de clusters. */
export const ATLAS_CLUSTER_THRESHOLD = 1500;
/** Plafond d'arêtes dessinées par frame. */
export const ATLAS_MAX_DRAWN_EDGES = 6000;

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface AtlasNoteNode {
  kind: "note";
  /** id de la note Vault (UUID). */
  id: string;
  scope: VaultScope;
  projectId: string | null;
  noteType: VaultNoteType;
  status: VaultNoteStatus;
  title: string;
  summary: string;
  readableId: string | null;
  slug: string;
  tags: string[];
  /** Position monde calculée par `layoutAtlas`. */
  position: Vec3;
  /** Rayon monde (fonction du degré, DEC légèrement plus grosses). */
  radius: number;
  /** Texte normalisé (minuscules, sans accents) pour la recherche. */
  searchText: string;
}

export interface AtlasSatelliteNode {
  kind: "satellite";
  /** `anchor:<valeur>` : `anchor:task:<uuid>` ou `anchor:path:<chemin>`. */
  id: string;
  anchorType: "task" | "path";
  /** Valeur brute de l'ancre, sans préfixe (uuid ou chemin). */
  label: string;
  position: Vec3;
  radius: number;
}

export type AtlasNode = AtlasNoteNode | AtlasSatelliteNode;

export interface AtlasEdge {
  source: string;
  target: string;
  kind: AtlasEdgeKind;
}

export interface AtlasCluster {
  /** `cluster:<scope>:<noteType>` (portée projet : `cluster:project:<projectId>:<noteType>`). */
  id: string;
  scope: VaultScope;
  noteType: VaultNoteType;
  label: string;
  count: number;
  /** ids des notes membres. */
  members: string[];
  position: Vec3;
  radius: number;
}

export interface AtlasGraph {
  nodes: AtlasNode[];
  edges: AtlasEdge[];
  /** id → nœud. */
  byId: Map<string, AtlasNode>;
  /** id → ids voisins (non orienté, toutes arêtes). */
  neighbors: Map<string, Set<string>>;
  /** true si le chargement a atteint ATLAS_MAX_NOTES. */
  truncated: boolean;
}

export interface AtlasFilters {
  /** Vide = tous les types. */
  noteTypes: VaultNoteType[];
  /** Vide = tous les statuts sauf `superseded` (masqué sauf `showSuperseded`). */
  statuses: VaultNoteStatus[];
  scopes: VaultScope[];
  showSuperseded: boolean;
  showSatellites: boolean;
  /** Recherche multi-mots : chaque mot (normalisé) doit apparaître. */
  query: string;
}

/** Résultat de `applyFilters` : ce que le moteur dessine. */
export interface AtlasView {
  /** Notes et satellites visibles (hors clusters). */
  nodes: AtlasNode[];
  edges: AtlasEdge[];
  /** Non vide seulement en mode replié (visibles > ATLAS_CLUSTER_THRESHOLD). */
  clusters: AtlasCluster[];
  /** ids correspondant à la recherche (vide si pas de requête). */
  matches: Set<string>;
  /** Étiquettes de groupe (portée × type) des notes visibles, mode déplié. */
  groups: AtlasGroup[];
}

/** Groupe (portée/projet × type) : étiquette flottante au-dessus de son disque. */
export interface AtlasGroup {
  id: string;
  noteType: VaultNoteType;
  label: string;
  count: number;
  center: Vec3;
  /** Rayon monde du disque (pour placer l'étiquette au-dessus). */
  radius: number;
}

/** Couleurs résolues depuis les variables CSS de `.vault-atlas`, injectées au moteur. */
export interface AtlasPalette {
  background: string;
  /** Second arrêt du dégradé radial du fond. */
  backgroundEdge: string;
  text: string;
  textMuted: string;
  edge: string;
  edgeStrong: string;
  accent: string;
  noteType: Record<VaultNoteType, string>;
  satellite: string;
  /** Fond des pastilles d'étiquette. */
  labelBackground: string;
}

export interface AtlasCamera {
  /** Rotation autour de Y puis X (radians). */
  yaw: number;
  pitch: number;
  /** Distance caméra → cible (> 0). */
  distance: number;
  /** Point visé (monde). */
  target: Vec3;
}

export interface ProjectedPoint {
  x: number;
  y: number;
  /** Facteur d'échelle perspective (> 0 si devant la caméra). */
  scale: number;
  /** Profondeur caméra (plus grand = plus loin). */
  depth: number;
  visible: boolean;
}

export interface AtlasRendererOptions {
  palette: AtlasPalette;
  /** Respecte prefers-reduced-motion : pas d'animation de vol, saut direct. */
  reducedMotion: boolean;
  onHover?: (id: string | null) => void;
  onSelect?: (id: string | null) => void;
}

/** Moteur Canvas 2D : rAF uniquement pendant une animation ou une interaction. */
export interface AtlasRenderer {
  setView(view: AtlasView): void;
  setSelected(id: string | null): void;
  setHovered(id: string | null): void;
  /** Vol de caméra vers un nœud ou un cluster (saut direct si reducedMotion). */
  flyTo(id: string): void;
  resetCamera(): void;
  getCamera(): AtlasCamera;
  /** Force un redessin (une frame). */
  requestRender(): void;
  /** Nœud/cluster sous un point écran (CSS px relatifs au canvas), ou null. */
  pick(x: number, y: number): string | null;
  resize(): void;
  destroy(): void;
}
