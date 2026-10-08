/**
 * Caméra orbitale de l'atlas : projection perspective, orbite, pan, zoom
 * vers le curseur et interpolation. Fonctions pures (aucun DOM).
 */
import type { AtlasCamera, ProjectedPoint, Vec3 } from "./types";

export const FOV = Math.PI / 3.2;
export const NEAR = 1;
export const MIN_DISTANCE = 8;
export const MAX_DISTANCE = 4000;
const PITCH_LIMIT = 1.45;
/** Vue initiale presque de face : la disposition en disques reste lisible, le relief se devine. */
const HOME_YAW = 0.1;
const HOME_PITCH = 0.14;

export function focalLength(height: number): number {
  return height / 2 / Math.tan(FOV / 2);
}

/** Monde → repère caméra (x droite, y haut, z profondeur depuis la cible). */
function toCamera(cam: AtlasCamera, p: Vec3): Vec3 {
  const vx = p.x - cam.target.x;
  const vy = p.y - cam.target.y;
  const vz = p.z - cam.target.z;
  const cy = Math.cos(cam.yaw);
  const sy = Math.sin(cam.yaw);
  const x1 = vx * cy - vz * sy;
  const z1 = vx * sy + vz * cy;
  const cp = Math.cos(cam.pitch);
  const sp = Math.sin(cam.pitch);
  return { x: x1, y: vy * cp - z1 * sp, z: vy * sp + z1 * cp };
}

/** Repère caméra → direction monde (inverse de la rotation, sans translation). */
function toWorldDirection(cam: AtlasCamera, v: Vec3): Vec3 {
  const cp = Math.cos(cam.pitch);
  const sp = Math.sin(cam.pitch);
  const y1 = v.y * cp + v.z * sp;
  const z1 = -v.y * sp + v.z * cp;
  const cy = Math.cos(cam.yaw);
  const sy = Math.sin(cam.yaw);
  return { x: v.x * cy + z1 * sy, y: y1, z: -v.x * sy + z1 * cy };
}

export function project(cam: AtlasCamera, p: Vec3, width: number, height: number): ProjectedPoint {
  const c = toCamera(cam, p);
  const depth = c.z + cam.distance;
  if (depth <= NEAR) return { x: 0, y: 0, scale: 0, depth, visible: false };
  const scale = focalLength(height) / depth;
  const x = width / 2 + c.x * scale;
  const y = height / 2 - c.y * scale;
  const margin = 64;
  const visible = x > -margin && x < width + margin && y > -margin && y < height + margin;
  return { x, y, scale, depth, visible };
}

export function orbit(cam: AtlasCamera, dx: number, dy: number): AtlasCamera {
  const pitch = Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, cam.pitch + dy * 0.006));
  return { ...cam, yaw: cam.yaw + dx * 0.006, pitch };
}

/** Déplace la cible dans le plan de l'écran (dx, dy en px CSS). */
export function pan(cam: AtlasCamera, dx: number, dy: number, height: number): AtlasCamera {
  const unit = cam.distance / focalLength(height);
  const move = toWorldDirection(cam, { x: -dx * unit, y: dy * unit, z: 0 });
  return { ...cam, target: { x: cam.target.x + move.x, y: cam.target.y + move.y, z: cam.target.z + move.z } };
}

/** Zoom de facteur `factor` (< 1 rapproche) en gardant fixe le point sous le curseur. */
export function zoomAt(cam: AtlasCamera, factor: number, sx: number, sy: number, width: number, height: number): AtlasCamera {
  const distance = Math.max(MIN_DISTANCE, Math.min(MAX_DISTANCE, cam.distance * factor));
  const applied = distance / cam.distance;
  const unit = cam.distance / focalLength(height);
  const offset = toWorldDirection(cam, { x: (sx - width / 2) * unit, y: (height / 2 - sy) * unit, z: 0 });
  const k = 1 - applied;
  return {
    ...cam,
    distance,
    target: { x: cam.target.x + offset.x * k, y: cam.target.y + offset.y * k, z: cam.target.z + offset.z * k },
  };
}

export function lerpCamera(a: AtlasCamera, b: AtlasCamera, t: number): AtlasCamera {
  const m = (x: number, y: number): number => x + (y - x) * t;
  return {
    yaw: m(a.yaw, b.yaw),
    pitch: m(a.pitch, b.pitch),
    distance: Math.exp(m(Math.log(a.distance), Math.log(b.distance))),
    target: { x: m(a.target.x, b.target.x), y: m(a.target.y, b.target.y), z: m(a.target.z, b.target.z) },
  };
}

/** Caméra qui cadre l'ensemble des points (vue initiale / « Recentrer »). */
export function cameraFor(points: Vec3[]): AtlasCamera {
  if (points.length === 0) return { yaw: HOME_YAW, pitch: HOME_PITCH, distance: 120, target: { x: 0, y: 0, z: 0 } };
  const c = points.reduce((acc, p) => ({ x: acc.x + p.x, y: acc.y + p.y, z: acc.z + p.z }), { x: 0, y: 0, z: 0 });
  const target = { x: c.x / points.length, y: c.y / points.length, z: c.z / points.length };
  const radius = Math.max(10, ...points.map((p) => Math.hypot(p.x - target.x, p.y - target.y, p.z - target.z)));
  const distance = Math.max(MIN_DISTANCE, Math.min(MAX_DISTANCE, radius / Math.sin(FOV / 2) * 1.05));
  return { yaw: HOME_YAW, pitch: HOME_PITCH, distance, target };
}
