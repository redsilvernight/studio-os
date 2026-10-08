/**
 * Moteur Canvas 2D de l'atlas (zéro dépendance, compatible CSP stricte).
 *
 * - rAF seulement à la demande (interaction, vol de caméra) ; jamais en boucle.
 * - Souris : glisser = orbite, Maj/clic droit + glisser = pan, molette =
 *   zoom vers le curseur, clic = sélection, double-clic = vol.
 * - Clavier (canevas focalisé) : flèches = orbite, +/- = zoom, 0 = recentrer.
 */
import { cameraFor, lerpCamera, orbit, pan, project, zoomAt } from "./camera";
import {
  ATLAS_MAX_DRAWN_EDGES,
  type AtlasCamera,
  type AtlasCluster,
  type AtlasEdge,
  type AtlasNode,
  type AtlasRenderer,
  type AtlasRendererOptions,
  type AtlasView,
  type ProjectedPoint,
  type Vec3,
} from "./types";

const FLY_MS = 650;
const CLICK_SLOP = 4;
const MAX_LABELS = 70;
/** Rayon écran (px) à partir duquel une note reçoit son étiquette. */
const LABEL_MIN_PX = 7;
/** Plafond du rayon écran (px) : de près, les notes restent des pastilles. */
const MAX_NODE_PX = 16;
const LABEL_FONT = "500 12px Inter, system-ui, sans-serif";
const GROUP_FONT = "650 12.5px Inter, system-ui, sans-serif";

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Drawn {
  id: string;
  p: ProjectedPoint;
  r: number;
}

function ease(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

function truncate(text: string, max = 42): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function createAtlasRenderer(canvas: HTMLCanvasElement, opts: AtlasRendererOptions): AtlasRenderer {
  const ctx = canvas.getContext("2d");
  let view: AtlasView = { nodes: [], edges: [], clusters: [], matches: new Set(), groups: [] };
  let byId = new Map<string, AtlasNode | AtlasCluster>();
  let selected: string | null = null;
  let hovered: string | null = null;
  let camera: AtlasCamera = cameraFor([]);
  let home: AtlasCamera = camera;
  let framed = false;
  let frame = 0;
  let flight: { from: AtlasCamera; to: AtlasCamera; start: number } | null = null;
  let drawn: Drawn[] = [];
  let width = 0;
  let height = 0;
  let destroyed = false;

  const size = (): void => {
    const rect = canvas.getBoundingClientRect();
    const dpr = typeof devicePixelRatio === "number" && devicePixelRatio > 0 ? devicePixelRatio : 1;
    width = Math.max(1, rect.width);
    height = Math.max(1, rect.height);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  const positionOf = (id: string): Vec3 | null => byId.get(id)?.position ?? null;

  const focusSet = (): Set<string> | null => {
    const focus = selected ?? hovered;
    if (focus === null) return null;
    const set = new Set<string>([focus]);
    for (const edge of view.edges) {
      if (edge.source === focus) set.add(edge.target);
      if (edge.target === focus) set.add(edge.source);
    }
    return set;
  };

  const arrow = (from: ProjectedPoint, to: ProjectedPoint, r: number): void => {
    if (ctx === null) return;
    const angle = Math.atan2(to.y - from.y, to.x - from.x);
    const tipX = to.x - Math.cos(angle) * r;
    const tipY = to.y - Math.sin(angle) * r;
    const len = 8;
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(tipX - len * Math.cos(angle - 0.4), tipY - len * Math.sin(angle - 0.4));
    ctx.lineTo(tipX - len * Math.cos(angle + 0.4), tipY - len * Math.sin(angle + 0.4));
    ctx.closePath();
    ctx.fill();
  };

  /** Pastille arrondie sous une étiquette. */
  const pill = (x: number, y: number, w: number, h: number): void => {
    if (ctx === null) return;
    const r = h / 2;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.arc(x + w - r, y + r, r, -Math.PI / 2, Math.PI / 2);
    ctx.lineTo(x + r, y + h);
    ctx.arc(x + r, y + r, r, Math.PI / 2, (3 * Math.PI) / 2);
    ctx.closePath();
    ctx.fill();
  };

  const colorOf = (node: AtlasNode | undefined): string =>
    node === undefined ? opts.palette.edge : node.kind === "satellite" ? opts.palette.satellite : opts.palette.noteType[node.noteType] ?? opts.palette.textMuted;

  const draw = (): void => {
    if (ctx === null) return;
    const pal = opts.palette;
    ctx.globalAlpha = 1;
    const glow = ctx.createRadialGradient(width / 2, height * 0.42, 0, width / 2, height * 0.42, Math.hypot(width, height) * 0.62);
    glow.addColorStop(0, pal.background);
    glow.addColorStop(1, pal.backgroundEdge);
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, width, height);

    const focusId = selected ?? hovered;
    const focus = focusSet();
    // Une note isolée sélectionnée n'éteint pas le reste de la carte.
    const dimming = focus !== null && focus.size > 1;
    const searching = view.matches.size > 0;
    const nodeById = new Map<string, AtlasNode>(view.nodes.map((n) => [n.id, n]));
    const projected = new Map<string, ProjectedPoint>();
    for (const node of view.nodes) projected.set(node.id, project(camera, node.position, width, height));
    // Brume de profondeur : ce qui est loin derrière la cible s'estompe.
    const fog = (p: ProjectedPoint): number => Math.max(0.3, Math.min(1, 1.55 - (p.depth / camera.distance) * 0.55));
    const isDim = (id: string): boolean => (dimming && focus !== null && !focus.has(id)) || (searching && !view.matches.has(id));

    // Îlots : un disque teinté sous chaque groupe.
    for (const group of view.groups) {
      const p = project(camera, group.center, width, height);
      if (p.scale <= 0) continue;
      const r = (group.radius + 6) * p.scale;
      if (p.x + r < 0 || p.x - r > width || p.y + r < 0 || p.y - r > height) continue;
      const tint = pal.noteType[group.noteType] ?? pal.textMuted;
      ctx.globalAlpha = (dimming || searching ? 0.04 : 0.08) * fog(p);
      ctx.fillStyle = tint;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = (dimming || searching ? 0.1 : 0.22) * fog(p);
      ctx.strokeStyle = tint;
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // Arêtes : plafonnées, celles du focus d'abord, teintées par la note source.
    const isLit = (e: AtlasEdge): boolean => focusId !== null && (e.source === focusId || e.target === focusId);
    const edges = focus === null
      ? view.edges.slice(0, ATLAS_MAX_DRAWN_EDGES)
      : [...view.edges.filter(isLit), ...view.edges.filter((e) => !isLit(e))].slice(0, ATLAS_MAX_DRAWN_EDGES);
    ctx.lineCap = "round";
    for (const edge of edges) {
      const a = projected.get(edge.source);
      const b = projected.get(edge.target);
      if (a === undefined || b === undefined || a.scale <= 0 || b.scale <= 0 || (!a.visible && !b.visible)) continue;
      const lit = isLit(edge);
      const dim = (dimming && !lit) || (searching && !view.matches.has(edge.source) && !view.matches.has(edge.target));
      ctx.globalAlpha = dim ? 0.05 : lit ? 0.95 : 0.28 * Math.min(fog(a), fog(b));
      ctx.strokeStyle = lit ? pal.accent : edge.kind === "supersedes" ? pal.edgeStrong : colorOf(nodeById.get(edge.source));
      ctx.lineWidth = lit ? 2 : edge.kind === "supersedes" || edge.kind === "derived_from" ? 1.5 : 1;
      ctx.setLineDash(edge.kind === "anchor" ? [2, 4] : edge.kind === "relates_to" ? [6, 4] : []);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      if (edge.kind === "supersedes") {
        ctx.setLineDash([]);
        ctx.fillStyle = ctx.strokeStyle;
        arrow(a, b, (nodeById.get(edge.target)?.radius ?? 2) * b.scale + 3);
      }
    }
    ctx.setLineDash([]);

    // Nœuds : du plus loin au plus proche.
    const order = view.nodes
      .map((node) => ({ node, p: projected.get(node.id)! }))
      .filter((entry) => entry.p.visible && entry.p.scale > 0)
      .sort((a, b) => b.p.depth - a.p.depth);
    const next: Drawn[] = [];
    const glowAllowed = order.length <= 800;
    for (const { node, p } of order) {
      const r = Math.min(MAX_NODE_PX, Math.max(2.5, node.radius * p.scale));
      const superseded = node.kind === "note" && node.status === "superseded";
      const color = colorOf(node);
      const focused = node.id === selected || node.id === hovered || (searching && view.matches.has(node.id));
      ctx.globalAlpha = (isDim(node.id) ? 0.13 : fog(p)) * (superseded ? 0.45 : 1);
      if (focused && glowAllowed) {
        ctx.shadowColor = color;
        ctx.shadowBlur = 22;
      }
      ctx.beginPath();
      if (node.kind === "satellite") {
        ctx.moveTo(p.x, p.y - r);
        ctx.lineTo(p.x + r, p.y);
        ctx.lineTo(p.x, p.y + r);
        ctx.lineTo(p.x - r, p.y);
        ctx.closePath();
        ctx.fillStyle = color;
        ctx.fill();
        ctx.shadowBlur = 0;
      } else {
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        // Brouillon = anneau creux ; proposée / validée = disque plein.
        ctx.fillStyle = node.status === "draft" ? pal.backgroundEdge : color;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.lineWidth = node.status === "draft" ? 2 : 1.5;
        ctx.strokeStyle = node.status === "draft" ? color : pal.backgroundEdge;
        ctx.stroke();
        if (node.status !== "draft" && r >= 4) {
          // Reflet : un peu de volume sans éclairage 3D.
          const base = ctx.globalAlpha;
          ctx.globalAlpha = base * 0.35;
          ctx.fillStyle = "#ffffff";
          ctx.beginPath();
          ctx.arc(p.x - r * 0.32, p.y - r * 0.32, r * 0.38, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = base;
        }
        if (node.status === "proposed") {
          ctx.setLineDash([3, 3]);
          ctx.lineWidth = 1.5;
          ctx.strokeStyle = color;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r + 3.5, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }
      if (focused) {
        ctx.globalAlpha = 1;
        ctx.lineWidth = node.id === selected ? 2.5 : 2;
        ctx.strokeStyle = pal.accent;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r + 6, 0, Math.PI * 2);
        ctx.stroke();
      }
      next.push({ id: node.id, p, r });
    }

    // Amas (mode replié).
    for (const cluster of view.clusters) {
      const p = project(camera, cluster.position, width, height);
      if (!p.visible || p.scale <= 0) continue;
      const r = Math.max(10, cluster.radius * p.scale);
      const color = pal.noteType[cluster.noteType] ?? pal.textMuted;
      ctx.globalAlpha = 0.28;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = cluster.id === hovered ? 2.5 : 1.5;
      ctx.strokeStyle = cluster.id === hovered ? pal.accent : color;
      ctx.stroke();
      ctx.fillStyle = pal.text;
      ctx.font = GROUP_FONT;
      ctx.textAlign = "center";
      ctx.fillText(cluster.label, p.x, p.y + 4);
      next.push({ id: cluster.id, p, r });
    }

    // Étiquettes sans chevauchement : groupes, puis sélection, survol,
    // correspondances, voisins, puis les plus grosses notes à l'écran
    // (le zoom en révèle davantage).
    const taken: Box[] = [];
    const free = (box: Box): boolean =>
      taken.every((t) => box.x + box.w < t.x || t.x + t.w < box.x || box.y + box.h < t.y || t.y + t.h < box.y);
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";

    ctx.font = GROUP_FONT;
    for (const group of view.groups) {
      const p = project(camera, { ...group.center, y: group.center.y + group.radius + 4 }, width, height);
      if (!p.visible || p.scale <= 0) continue;
      const w = ctx.measureText(group.label).width + 28;
      const box = { x: p.x - w / 2, y: p.y - 26, w, h: 22 };
      if (!free(box)) continue;
      taken.push(box);
      ctx.globalAlpha = dimming || searching ? 0.55 : 0.95;
      ctx.fillStyle = pal.labelBackground;
      pill(box.x, box.y, box.w, box.h);
      ctx.fillStyle = pal.noteType[group.noteType] ?? pal.text;
      ctx.beginPath();
      ctx.arc(box.x + 11, box.y + 11, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = pal.text;
      ctx.fillText(group.label, box.x + 20, box.y + 11.5);
    }

    ctx.font = LABEL_FONT;
    const rank = (id: string): number =>
      id === selected ? 0 : id === hovered ? 1 : view.matches.has(id) ? 2 : dimming && focus !== null && focus.has(id) ? 3 : 4;
    const candidates = order
      .filter(({ node, p }) => rank(node.id) < 4 || (!dimming && !searching && node.kind === "note" && node.radius * p.scale >= LABEL_MIN_PX))
      .sort((a, b) => rank(a.node.id) - rank(b.node.id) || b.node.radius * b.p.scale - a.node.radius * a.p.scale);
    let labels = 0;
    for (const { node, p } of candidates) {
      if (labels >= MAX_LABELS) break;
      const text = node.kind === "note" ? truncate(node.readableId ? `${node.readableId} · ${node.title}` : node.title) : truncate(node.label, 32);
      const r = Math.min(MAX_NODE_PX, Math.max(2.5, node.radius * p.scale));
      const box = { x: p.x + r + 6, y: p.y - 10, w: ctx.measureText(text).width + 14, h: 20 };
      const important = rank(node.id) <= 1;
      if (!important && !free(box)) continue;
      taken.push(box);
      labels += 1;
      ctx.globalAlpha = important ? 1 : 0.92 * fog(p);
      ctx.fillStyle = pal.labelBackground;
      pill(box.x, box.y, box.w, box.h);
      if (node.id === selected) {
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = colorOf(node);
        ctx.stroke();
      }
      ctx.fillStyle = node.kind === "satellite" ? pal.textMuted : pal.text;
      ctx.fillText(text, box.x + 7, box.y + 10.5);
    }
    ctx.globalAlpha = 1;
    ctx.textBaseline = "alphabetic";
    drawn = next;
  };

  const tick = (now: number): void => {
    frame = 0;
    if (destroyed) return;
    if (flight !== null) {
      const t = Math.min(1, (now - flight.start) / FLY_MS);
      camera = lerpCamera(flight.from, flight.to, ease(t));
      if (t >= 1) flight = null;
    }
    draw();
    if (flight !== null) frame = requestAnimationFrame(tick);
  };

  const requestRender = (): void => {
    if (destroyed || frame !== 0) return;
    frame = requestAnimationFrame(tick);
  };

  const goTo = (to: AtlasCamera): void => {
    if (opts.reducedMotion) {
      flight = null;
      camera = to;
    } else {
      flight = { from: camera, to, start: performance.now() };
    }
    requestRender();
  };

  const pick = (x: number, y: number): string | null => {
    let best: string | null = null;
    let bestDepth = Infinity;
    for (const item of drawn) {
      const d = Math.hypot(item.p.x - x, item.p.y - y);
      if (d <= item.r + 4 && item.p.depth < bestDepth) {
        best = item.id;
        bestDepth = item.p.depth;
      }
    }
    return best;
  };

  // --- Interactions ---
  let drag: { x: number; y: number; startX: number; startY: number; pan: boolean; moved: boolean } | null = null;
  const local = (event: MouseEvent): { x: number; y: number } => {
    const rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const onPointerDown = (event: PointerEvent): void => {
    const { x, y } = local(event);
    drag = { x, y, startX: x, startY: y, pan: event.shiftKey || event.button === 2 || event.button === 1, moved: false };
    canvas.setPointerCapture?.(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent): void => {
    const { x, y } = local(event);
    if (drag !== null) {
      const dx = x - drag.x;
      const dy = y - drag.y;
      drag.x = x;
      drag.y = y;
      if (Math.hypot(x - drag.startX, y - drag.startY) > CLICK_SLOP) drag.moved = true;
      if (!drag.moved) return;
      flight = null;
      camera = drag.pan ? pan(camera, dx, dy, height) : orbit(camera, dx, dy);
      requestRender();
      return;
    }
    const id = pick(x, y);
    if (id !== hovered) {
      hovered = id;
      canvas.style.cursor = id === null ? "" : "pointer";
      opts.onHover?.(id);
      requestRender();
    }
  };
  const onPointerUp = (event: PointerEvent): void => {
    const current = drag;
    drag = null;
    canvas.releasePointerCapture?.(event.pointerId);
    if (current === null || current.moved || event.button !== 0) return;
    const { x, y } = local(event);
    opts.onSelect?.(pick(x, y));
  };
  const onPointerLeave = (): void => {
    if (drag !== null || hovered === null) return;
    hovered = null;
    opts.onHover?.(null);
    requestRender();
  };
  const onWheel = (event: WheelEvent): void => {
    event.preventDefault();
    const { x, y } = local(event);
    flight = null;
    camera = zoomAt(camera, Math.exp(Math.max(-1, Math.min(1, event.deltaY * 0.0015))), x, y, width, height);
    requestRender();
  };
  const onDoubleClick = (event: MouseEvent): void => {
    const { x, y } = local(event);
    const id = pick(x, y);
    if (id !== null) api.flyTo(id);
  };
  const onKeyDown = (event: KeyboardEvent): void => {
    const step = 24;
    const moves: Record<string, () => AtlasCamera> = {
      ArrowLeft: () => orbit(camera, -step, 0),
      ArrowRight: () => orbit(camera, step, 0),
      ArrowUp: () => orbit(camera, 0, -step),
      ArrowDown: () => orbit(camera, 0, step),
      "+": () => zoomAt(camera, 0.8, width / 2, height / 2, width, height),
      "=": () => zoomAt(camera, 0.8, width / 2, height / 2, width, height),
      "-": () => zoomAt(camera, 1.25, width / 2, height / 2, width, height),
    };
    if (event.key === "0") {
      event.preventDefault();
      api.resetCamera();
      return;
    }
    const move = moves[event.key];
    if (move === undefined) return;
    event.preventDefault();
    flight = null;
    camera = move();
    requestRender();
  };
  const onContextMenu = (event: MouseEvent): void => event.preventDefault();

  canvas.addEventListener("pointerdown", onPointerDown);
  canvas.addEventListener("pointermove", onPointerMove);
  canvas.addEventListener("pointerup", onPointerUp);
  canvas.addEventListener("pointerleave", onPointerLeave);
  canvas.addEventListener("wheel", onWheel, { passive: false });
  canvas.addEventListener("dblclick", onDoubleClick);
  canvas.addEventListener("keydown", onKeyDown);
  canvas.addEventListener("contextmenu", onContextMenu);
  const observer = typeof ResizeObserver === "function" ? new ResizeObserver(() => api.resize()) : null;
  observer?.observe(canvas);
  size();

  const api: AtlasRenderer = {
    setView(next) {
      view = next;
      byId = new Map<string, AtlasNode | AtlasCluster>();
      for (const node of next.nodes) byId.set(node.id, node);
      for (const cluster of next.clusters) byId.set(cluster.id, cluster);
      const points = [...next.nodes.map((n) => n.position), ...next.clusters.map((c) => c.position)];
      home = cameraFor(points);
      if (!framed && points.length > 0) {
        camera = home;
        framed = true;
      }
      if (hovered !== null && !byId.has(hovered)) hovered = null;
      requestRender();
    },
    setSelected(id) {
      selected = id;
      requestRender();
    },
    setHovered(id) {
      hovered = id;
      requestRender();
    },
    flyTo(id) {
      const target = positionOf(id);
      if (target === null) return;
      const item = byId.get(id);
      const span = item !== undefined && "count" in item ? item.radius * 6 : 190;
      goTo({ ...camera, target: { ...target }, distance: Math.min(camera.distance, Math.max(span, 30)) });
    },
    resetCamera() {
      goTo(home);
    },
    getCamera() {
      return camera;
    },
    requestRender,
    pick,
    resize() {
      size();
      requestRender();
    },
    destroy() {
      destroyed = true;
      if (frame !== 0) cancelAnimationFrame(frame);
      frame = 0;
      observer?.disconnect();
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointerleave", onPointerLeave);
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("dblclick", onDoubleClick);
      canvas.removeEventListener("keydown", onKeyDown);
      canvas.removeEventListener("contextmenu", onContextMenu);
    },
  };
  return api;
}
