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
  type AtlasNode,
  type AtlasRenderer,
  type AtlasRendererOptions,
  type AtlasView,
  type ProjectedPoint,
  type Vec3,
} from "./types";

const FLY_MS = 650;
const CLICK_SLOP = 4;
const MAX_LABELS = 40;

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
  let view: AtlasView = { nodes: [], edges: [], clusters: [], matches: new Set() };
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
    const len = 7;
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(tipX - len * Math.cos(angle - 0.4), tipY - len * Math.sin(angle - 0.4));
    ctx.lineTo(tipX - len * Math.cos(angle + 0.4), tipY - len * Math.sin(angle + 0.4));
    ctx.closePath();
    ctx.fill();
  };

  const draw = (): void => {
    if (ctx === null) return;
    const pal = opts.palette;
    ctx.fillStyle = pal.background;
    ctx.fillRect(0, 0, width, height);
    const focus = focusSet();
    const searching = view.matches.size > 0;
    const projected = new Map<string, ProjectedPoint>();
    for (const node of view.nodes) projected.set(node.id, project(camera, node.position, width, height));

    // Arêtes : plafonnées, celles du focus d'abord.
    const edges = focus === null
      ? view.edges.slice(0, ATLAS_MAX_DRAWN_EDGES)
      : [...view.edges.filter((e) => focus.has(e.source) && focus.has(e.target)), ...view.edges.filter((e) => !(focus.has(e.source) && focus.has(e.target)))].slice(0, ATLAS_MAX_DRAWN_EDGES);
    ctx.lineCap = "round";
    for (const edge of edges) {
      const a = projected.get(edge.source);
      const b = projected.get(edge.target);
      if (a === undefined || b === undefined || a.scale <= 0 || b.scale <= 0 || (!a.visible && !b.visible)) continue;
      const lit = focus !== null && (edge.source === (selected ?? hovered) || edge.target === (selected ?? hovered));
      const dim = (focus !== null && !lit) || (searching && !view.matches.has(edge.source) && !view.matches.has(edge.target));
      ctx.globalAlpha = dim ? 0.15 : lit ? 0.95 : 0.55;
      const strong = edge.kind === "supersedes" || edge.kind === "derived_from";
      ctx.strokeStyle = lit ? pal.accent : strong ? pal.edgeStrong : pal.edge;
      ctx.lineWidth = lit ? 1.8 : strong ? 1.4 : 1;
      ctx.setLineDash(edge.kind === "anchor" ? [3, 3] : edge.kind === "relates_to" ? [6, 3] : []);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      if (edge.kind === "supersedes") {
        ctx.setLineDash([]);
        ctx.fillStyle = ctx.strokeStyle;
        const target = view.nodes.find((n) => n.id === edge.target);
        arrow(a, b, (target?.radius ?? 2) * b.scale + 2);
      }
    }
    ctx.setLineDash([]);

    // Nœuds : du plus loin au plus proche.
    const order = view.nodes
      .map((node) => ({ node, p: projected.get(node.id)! }))
      .filter((entry) => entry.p.visible && entry.p.scale > 0)
      .sort((a, b) => b.p.depth - a.p.depth);
    const next: Drawn[] = [];
    for (const { node, p } of order) {
      const r = Math.max(2, node.radius * p.scale);
      const dim = (focus !== null && !focus.has(node.id)) || (searching && !view.matches.has(node.id));
      const superseded = node.kind === "note" && node.status === "superseded";
      ctx.globalAlpha = (dim ? 0.22 : 1) * (superseded ? 0.45 : 1);
      ctx.beginPath();
      if (node.kind === "satellite") {
        ctx.moveTo(p.x, p.y - r);
        ctx.lineTo(p.x + r, p.y);
        ctx.lineTo(p.x, p.y + r);
        ctx.lineTo(p.x - r, p.y);
        ctx.closePath();
        ctx.fillStyle = pal.satellite;
        ctx.fill();
      } else {
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fillStyle = pal.noteType[node.noteType] ?? pal.textMuted;
        ctx.fill();
        // Anneau de statut : plein = validée, tirets = proposée, pointillé = brouillon.
        if (node.status === "validated" || node.status === "proposed" || node.status === "draft") {
          ctx.setLineDash(node.status === "proposed" ? [4, 3] : node.status === "draft" ? [1.5, 2.5] : []);
          ctx.lineWidth = node.noteType === "decision" ? 2 : 1.4;
          ctx.strokeStyle = pal.text;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r + 2, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }
      if (node.id === selected || node.id === hovered || view.matches.has(node.id)) {
        ctx.globalAlpha = 1;
        ctx.lineWidth = node.id === selected ? 3 : 2;
        ctx.strokeStyle = pal.accent;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r + 5, 0, Math.PI * 2);
        ctx.stroke();
      }
      next.push({ id: node.id, p, r });
    }

    // Amas (mode replié).
    for (const cluster of view.clusters) {
      const p = project(camera, cluster.position, width, height);
      if (!p.visible || p.scale <= 0) continue;
      const r = Math.max(8, cluster.radius * p.scale);
      ctx.globalAlpha = 0.35;
      ctx.fillStyle = opts.palette.noteType[cluster.noteType] ?? pal.textMuted;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = cluster.id === hovered ? 2.5 : 1.2;
      ctx.strokeStyle = cluster.id === hovered ? pal.accent : pal.text;
      ctx.stroke();
      ctx.fillStyle = pal.text;
      ctx.font = "600 12px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(cluster.label, p.x, p.y + 4);
      next.push({ id: cluster.id, p, r });
    }

    // Étiquettes : focus, correspondances, puis décisions proches.
    ctx.globalAlpha = 1;
    ctx.textAlign = "left";
    ctx.font = "12px system-ui, sans-serif";
    let labels = 0;
    const labelled = order
      .filter(({ node }) =>
        node.id === selected || node.id === hovered || focus?.has(node.id) || view.matches.has(node.id) ||
        (node.kind === "note" && node.noteType === "decision" && node.radius * (projected.get(node.id)?.scale ?? 0) > 7))
      .reverse();
    for (const { node, p } of labelled) {
      if (labels >= MAX_LABELS) break;
      labels += 1;
      const text = node.kind === "note" ? truncate(node.readableId ? `${node.readableId} ${node.title}` : node.title) : truncate(node.label, 32);
      const x = p.x + Math.max(2, node.radius * p.scale) + 6;
      ctx.lineWidth = 3;
      ctx.strokeStyle = pal.background;
      ctx.strokeText(text, x, p.y + 4);
      ctx.fillStyle = node.id === selected ? pal.accent : node.kind === "satellite" ? pal.textMuted : pal.text;
      ctx.fillText(text, x, p.y + 4);
    }
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
      const span = item !== undefined && "count" in item ? item.radius * 6 : 70;
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
