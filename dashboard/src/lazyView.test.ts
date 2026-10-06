// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { lazyView, renderViewLoadError, ViewLoadError, VIEW_LOAD_RETRY_ID } from "./lazyView";

describe("lazyView", () => {
  it("returns the imported module", async () => {
    await expect(lazyView(async () => ({ ok: 1 }))).resolves.toEqual({ ok: 1 });
  });

  it("wraps a failed chunk load in ViewLoadError and keeps the cause", async () => {
    const cause = new TypeError("Failed to fetch dynamically imported module");
    const error = await lazyView(() => Promise.reject(cause)).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ViewLoadError);
    expect((error as ViewLoadError).cause).toBe(cause);
  });
});

describe("renderViewLoadError", () => {
  it("paints an alert with a reload action", () => {
    const view = document.createElement("main");
    const reload = vi.fn();
    renderViewLoadError(view, reload);
    expect(view.querySelector('[role="alert"]')).not.toBeNull();
    view.querySelector<HTMLElement>(`#${VIEW_LOAD_RETRY_ID}`)?.click();
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
