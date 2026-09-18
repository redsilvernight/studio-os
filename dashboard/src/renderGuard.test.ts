import { describe, expect, it } from "vitest";
import { createRenderGuard } from "./renderGuard";

describe("createRenderGuard (UI-2, anti-race du shell)", () => {
  it("keeps only the newest render current", () => {
    const guard = createRenderGuard();
    const first = guard.next();
    expect(guard.isCurrent(first)).toBe(true);
    const second = guard.next();
    expect(guard.isCurrent(first)).toBe(false);
    expect(guard.isCurrent(second)).toBe(true);
  });

  it("rejects unknown or zero ids", () => {
    const guard = createRenderGuard();
    guard.next();
    expect(guard.isCurrent(0)).toBe(false);
    expect(guard.isCurrent(999)).toBe(false);
  });

  it("models the UI-1 race: slow overview discarded after navigation", () => {
    const guard = createRenderGuard();
    const overview = guard.next();
    const machines = guard.next();
    // Late overview completion must not repaint the current route.
    expect(guard.isCurrent(overview)).toBe(false);
    expect(guard.isCurrent(machines)).toBe(true);
  });
});
