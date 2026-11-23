// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getActiveStudio,
  getStudios,
  resetStudioStoreForTests,
  selectStudio,
  setStudios,
  STUDIO_CHANGE_EVENT,
  subscribeStudios,
} from "./studioStore";
import type { Studio } from "./studiosApi";

const A: Studio = { id: "a", name: "Atelier Phare", slug: "phare", plan: "Gratuit", status: "active", role: "owner" };
const B: Studio = { id: "b", name: "Binaweb", slug: "bina", plan: "Pro", status: "active", role: "member" };

beforeEach(() => {
  resetStudioStoreForTests();
});

describe("studioStore", () => {
  it("selects the first studio by default and switches without reload", () => {
    setStudios([A, B]);
    expect(getStudios()).toHaveLength(2);
    expect(getActiveStudio()).toEqual(A);
    const chosen = selectStudio("b");
    expect(chosen).toEqual(B);
    expect(getActiveStudio()).toEqual(B);
    expect(window.localStorage.getItem("studios.selected")).toBe("b");
  });

  it("ignores unknown ids", () => {
    setStudios([A]);
    expect(selectStudio("zzz")).toBeNull();
    expect(getActiveStudio()).toEqual(A);
  });

  it("notifies subscribers and emits a DOM event on change", () => {
    setStudios([A, B]);
    const listener = vi.fn();
    const off = subscribeStudios(listener);
    const domListener = vi.fn();
    window.addEventListener(STUDIO_CHANGE_EVENT, domListener);
    selectStudio("b");
    expect(listener).toHaveBeenCalledWith(B);
    expect(domListener).toHaveBeenCalledTimes(1);
    off();
    selectStudio("a");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("restores the persisted selection when available", () => {
    window.localStorage.setItem("studios.selected", "b");
    setStudios([A, B]);
    expect(getActiveStudio()).toEqual(B);
  });
});
