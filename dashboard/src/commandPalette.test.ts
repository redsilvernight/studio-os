// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  closePalette,
  filterPalette,
  isPaletteOpen,
  mountPalette,
  paletteEntries,
  paletteListHtml,
  resetPaletteForTests,
} from "./commandPalette";
import { parseRoute } from "./router";
import { shellHtml } from "./shell";

describe("paletteEntries (P03-shell)", () => {
  it("lists exactly the sidebar destinations, daily first", () => {
    const entries = paletteEntries(parseRoute("#/"));
    expect(entries.slice(0, 5).map((e) => e.label)).toEqual(["Accueil", "Projets", "Travail", "À valider", "Agents"]);
    expect(entries.some((e) => e.label === "Configuration" && e.group === "Administration")).toBe(true);
    expect(entries.some((e) => e.label === "Vue d'ensemble" && e.group === "Administration")).toBe(true);
    expect(entries.some((e) => e.label === "Espaces de travail" && e.group === "Administration")).toBe(true);
    expect(entries.some((e) => e.label === "Inspecteur" && e.group === "Outils experts")).toBe(true);
    expect(new Set(entries.map((e) => e.href)).size).toBe(entries.length);
  });

  it("adds no extra entry on desktop: Espaces is always visible", () => {
    expect(paletteEntries(parseRoute("#/"), true).length).toBe(paletteEntries(parseRoute("#/")).length);
  });
});

describe("filterPalette", () => {
  const entries = paletteEntries(parseRoute("#/"));

  it("returns everything for an empty query", () => {
    expect(filterPalette(entries, "  ")).toEqual(entries);
  });

  it("ignores accents and case", () => {
    expect(filterPalette(entries, "a VALIDER").map((e) => e.label)).toEqual(["À valider"]);
    expect(filterPalette(entries, "parametres")).toEqual([]);
    expect(filterPalette(entries, "configuration").map((e) => e.label)).toEqual(["Configuration"]);
  });

  it("requires every word and ranks label prefixes first", () => {
    const hits = filterPalette(entries, "admin");
    expect(hits.length).toBeGreaterThan(1);
    expect(hits.every((e) => e.group === "Administration")).toBe(true);
    expect(filterPalette(entries, "agents zzz")).toEqual([]);
    const pro = filterPalette(entries, "pro");
    expect(pro[0]?.label).toBe("Projets");
  });
});

describe("paletteListHtml", () => {
  it("marks the active option and escapes labels", () => {
    const html = paletteListHtml([{ href: "#/x", label: "<b>", group: "G", icon: "home" }], 0);
    expect(html).toContain('aria-selected="true"');
    expect(html).toContain("&lt;b&gt;");
  });

  it("says when nothing matches", () => {
    expect(paletteListHtml([], 0)).toContain("Aucune page ne correspond.");
  });
});

describe("mountPalette", () => {
  beforeEach(() => {
    document.body.innerHTML = shellHtml(parseRoute("#/"), true);
    location.hash = "#/";
    mountPalette(() => paletteEntries(parseRoute("#/")));
  });
  afterEach(() => {
    closePalette(false);
    resetPaletteForTests();
  });

  function key(target: EventTarget, init: KeyboardEventInit): void {
    target.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init }));
  }

  it("toggles with Ctrl K and focuses the input", () => {
    key(document.body, { key: "k", ctrlKey: true });
    expect(isPaletteOpen()).toBe(true);
    expect(document.activeElement?.id).toBe("app-palette-input");
    key(document.body, { key: "k", ctrlKey: true });
    expect(isPaletteOpen()).toBe(false);
  });

  it("filters, moves with arrows and navigates with Enter", () => {
    (document.getElementById("palette-open") as HTMLButtonElement).click();
    const input = document.getElementById("app-palette-input") as HTMLInputElement;
    input.value = "valider";
    input.dispatchEvent(new Event("input"));
    expect(document.querySelectorAll("#app-palette-list [role=option]")).toHaveLength(1);
    key(input, { key: "Enter" });
    expect(location.hash).toBe("#/decisions");
    expect(isPaletteOpen()).toBe(false);
  });

  it("closes on Escape and returns focus to the opener", () => {
    const opener = document.getElementById("palette-open") as HTMLButtonElement;
    opener.click();
    key(document.getElementById("app-palette-input") as HTMLElement, { key: "Escape" });
    expect(isPaletteOpen()).toBe(false);
    expect(document.activeElement).toBe(opener);
  });
});
