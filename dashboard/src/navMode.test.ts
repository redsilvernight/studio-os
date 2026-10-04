// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { loadNavMode, NAV_MODE_STORAGE_KEY, saveNavMode, toggledNavMode } from "./navMode";
import { shellHtml, shellNavGroups } from "./shell";

function memoryStore(initial?: string): Pick<Storage, "getItem" | "setItem"> & { value: string | null } {
  const store = {
    value: initial ?? null,
    getItem: (): string | null => store.value,
    setItem: (_key: string, value: string): void => {
      store.value = value;
    },
  };
  return store;
}

describe("navMode (P06 rollout)", () => {
  it("defaults to simple and treats unreadable values as simple", () => {
    expect(loadNavMode(memoryStore())).toBe("simple");
    expect(loadNavMode(memoryStore("n'importe quoi"))).toBe("simple");
    expect(loadNavMode(null)).toBe("simple");
    const broken = {
      getItem: (): string => {
        throw new Error("denied");
      },
      setItem: (): void => {
        throw new Error("denied");
      },
    };
    expect(loadNavMode(broken)).toBe("simple");
    expect(() => saveNavMode("complete", broken)).not.toThrow();
  });

  it("round-trips the choice and toggles both ways", () => {
    const store = memoryStore();
    saveNavMode("complete", store);
    expect(store.value).toBe("complete");
    expect(loadNavMode(store)).toBe("complete");
    saveNavMode(toggledNavMode("complete"), store);
    expect(loadNavMode(store)).toBe("simple");
    expect(NAV_MODE_STORAGE_KEY).toBe("studio-os.nav-mode");
  });

  it("changes presentation only: same destinations in both modes, nothing collapsed in complete", () => {
    const hrefs = (mode: "simple" | "complete"): string[] =>
      shellNavGroups({ name: "dashboard" }, false, mode).flatMap((group) => group.items.map((item) => item.href));
    expect(hrefs("complete")).toEqual(hrefs("simple"));
    const complete = shellNavGroups({ name: "dashboard" }, false, "complete");
    expect(complete.map((group) => group.collapsible === true)).toEqual([false, false, false]);

    const simpleHtml = shellHtml({ name: "dashboard" }, true, false, "simple");
    expect(simpleHtml).toContain("<details");
    expect(simpleHtml).toContain('aria-pressed="false"');
    const completeHtml = shellHtml({ name: "dashboard" }, true, false, "complete");
    expect(completeHtml).not.toContain("<details");
    expect(completeHtml).toContain('aria-pressed="true"');
    expect(completeHtml).toContain('id="nav-mode-toggle"');
    // Toujours un seul indicateur de connexion (C4), quel que soit le mode.
    expect(completeHtml.match(/data-testid="connection-status"/g)).toHaveLength(1);
  });
});
