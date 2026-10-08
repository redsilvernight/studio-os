import { describe, expect, it } from "vitest";
import { cameraFor, lerpCamera, MAX_DISTANCE, MIN_DISTANCE, orbit, pan, project, zoomAt } from "./camera";
import type { AtlasCamera } from "./types";

const W = 800;
const H = 600;
const cam: AtlasCamera = { yaw: 0.4, pitch: 0.3, distance: 200, target: { x: 10, y: -5, z: 3 } };

describe("atlas camera", () => {
  it("projects the target to the screen center and hides points behind", () => {
    const p = project(cam, cam.target, W, H);
    expect(p.x).toBeCloseTo(W / 2);
    expect(p.y).toBeCloseTo(H / 2);
    expect(p.visible).toBe(true);
    const behind = project({ ...cam, yaw: 0, pitch: 0 }, { x: 10, y: -5, z: -400 }, W, H);
    expect(behind.visible).toBe(false);
  });

  it("clamps pitch while orbiting", () => {
    expect(orbit(cam, 0, 10_000).pitch).toBeLessThan(Math.PI / 2);
    expect(orbit(cam, 100, 0).yaw).not.toBe(cam.yaw);
  });

  it("pans so the target follows the drag on screen", () => {
    const moved = pan(cam, 50, 0, H);
    const p = project(moved, cam.target, W, H);
    expect(p.x).toBeCloseTo(W / 2 + 50, 3);
    expect(p.y).toBeCloseTo(H / 2, 3);
  });

  it("zooms toward the cursor, keeping the point under it fixed", () => {
    const sx = 600;
    const sy = 150;
    // Point du plan de la cible qui se projette sous le curseur.
    const probe = pan(cam, -(sx - W / 2), -(sy - H / 2), H).target;
    const before = project(cam, probe, W, H);
    const zoomed = zoomAt(cam, 0.5, sx, sy, W, H);
    const after = project(zoomed, probe, W, H);
    expect(before.x).toBeCloseTo(sx, 3);
    expect(after.x).toBeCloseTo(sx, 3);
    expect(after.y).toBeCloseTo(sy, 3);
    expect(zoomed.distance).toBeCloseTo(100);
    expect(zoomAt(cam, 1e-6, 0, 0, W, H).distance).toBe(MIN_DISTANCE);
    expect(zoomAt(cam, 1e6, 0, 0, W, H).distance).toBe(MAX_DISTANCE);
  });

  it("interpolates and frames a point cloud", () => {
    const end: AtlasCamera = { yaw: 1, pitch: 0, distance: 50, target: { x: 0, y: 0, z: 0 } };
    expect(lerpCamera(cam, end, 0).distance).toBeCloseTo(cam.distance);
    expect(lerpCamera(cam, end, 0).target).toEqual(cam.target);
    expect(lerpCamera(cam, end, 1).distance).toBeCloseTo(50);
    const framed = cameraFor([{ x: -100, y: 0, z: 0 }, { x: 100, y: 0, z: 0 }]);
    expect(framed.target).toEqual({ x: 0, y: 0, z: 0 });
    for (const x of [-100, 100]) {
      const p = project(framed, { x, y: 0, z: 0 }, W, H);
      expect(p.visible).toBe(true);
    }
  });
});
