// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from "vitest";
import {
  baseVersion,
  checkWhatsNewAtStart,
  compareVersions,
  decideWhatsNew,
  loadSeenVersion,
  notesSince,
  openWhatsNew,
  renderNoteMarkdown,
  saveSeenVersion,
  WHATS_NEW_DIALOG_ID,
  WHATS_NEW_STORAGE_KEY,
  whatsNewSectionHtml,
} from "./releaseNotes";
import type { DesktopInfo } from "./platform/types";

const NOTES = {
  "0.1.0": "# Version 0.1.0\n\n- Premier lancement",
  "0.2.0": "# Version 0.2.0\n\n- Deuxième version",
  "0.3.0": "# Version 0.3.0\n\n- Troisième version",
};

const desktop = (version: string) => ({
  mode: "desktop" as const,
  desktopInfo: async (): Promise<DesktopInfo> =>
    ({
      product: "Studi'OS Desktop",
      desktop_version: version,
      mode: "desktop",
      protocol: "1",
      sidecar: { state: "not_started" },
    }) as unknown as DesktopInfo,
});

const overlay = (): HTMLElement | null => document.getElementById(WHATS_NEW_DIALOG_ID);

beforeEach(() => {
  document.body.innerHTML = "";
  globalThis.localStorage.clear();
});

describe("version comparison", () => {
  it("resolves a pre-release to its base version", () => {
    expect(baseVersion("0.1.0-dev.42")).toBe("0.1.0");
    expect(baseVersion("1.2.3")).toBe("1.2.3");
  });

  it("orders versions numerically", () => {
    expect(compareVersions("0.2.0", "0.1.0")).toBeGreaterThan(0);
    expect(compareVersions("0.1.0", "0.1.0")).toBe(0);
    expect(compareVersions("0.1.0", "0.10.0")).toBeLessThan(0);
  });
});

describe("cumulative notes", () => {
  it("returns every note strictly after the seen version up to the current one", () => {
    expect(notesSince("0.1.0", "0.3.0", NOTES).map((e) => e.version)).toEqual(["0.2.0", "0.3.0"]);
    expect(notesSince("0.2.0", "0.2.0", NOTES)).toEqual([]);
    expect(notesSince(null, "0.3.0", NOTES).map((e) => e.version)).toEqual(["0.1.0", "0.2.0", "0.3.0"]);
  });

  it("shows nothing on a fresh install and records nothing to show", () => {
    expect(decideWhatsNew("0.3.0", null, NOTES)).toEqual({ show: false, freshInstall: true, entries: [] });
  });

  it("shows one version on an N -> N+1 update", () => {
    const decision = decideWhatsNew("0.2.0", "0.1.0", NOTES);
    expect(decision.show).toBe(true);
    expect(decision.entries.map((e) => e.version)).toEqual(["0.2.0"]);
  });

  it("shows the cumulative notes on an N -> N+3 update", () => {
    const decision = decideWhatsNew("0.3.0", "0.1.0", NOTES);
    expect(decision.entries.map((e) => e.version)).toEqual(["0.2.0", "0.3.0"]);
  });

  it("shows nothing when the version did not move", () => {
    expect(decideWhatsNew("0.2.0", "0.2.0", NOTES).show).toBe(false);
  });
});

describe("seen version storage", () => {
  it("round-trips the base version and refuses a foreign schema", () => {
    saveSeenVersion("0.1.0-dev.42");
    expect(loadSeenVersion()).toBe("0.1.0");
    globalThis.localStorage.setItem(WHATS_NEW_STORAGE_KEY, JSON.stringify({ schema: 99, version: "9.9.9" }));
    expect(loadSeenVersion()).toBeNull();
  });
});

describe("note rendering", () => {
  it("renders headings and bullets and escapes markup", () => {
    const html = renderNoteMarkdown("# Titre\n\n- point **fort**\n- <script>");
    expect(html).toContain("<h2>Titre</h2>");
    expect(html).toContain("<li>point <strong>fort</strong></li>");
    expect(html).toContain("&lt;script&gt;");
  });

  it("the settings section lists versions newest first", () => {
    const html = whatsNewSectionHtml(NOTES);
    expect(html).toContain("data-action=\"open-whats-new\"");
    expect(html.indexOf("0.3.0")).toBeLessThan(html.indexOf("0.1.0"));
  });
});

describe("whats-new at start", () => {
  it("a fresh install records the version and opens nothing", async () => {
    await checkWhatsNewAtStart(desktop("0.1.0"), NOTES);
    expect(overlay()).toBeNull();
    expect(loadSeenVersion()).toBe("0.1.0");
  });

  it("an update opens the window once, then never again", async () => {
    saveSeenVersion("0.1.0");
    await checkWhatsNewAtStart(desktop("0.3.0"), NOTES);
    expect(overlay()?.hasAttribute("hidden")).toBe(false);
    expect(overlay()?.textContent).toContain("Deuxième version");
    expect(overlay()?.textContent).toContain("Troisième version");
    expect(loadSeenVersion()).toBe("0.3.0");

    document.body.innerHTML = "";
    await checkWhatsNewAtStart(desktop("0.3.0"), NOTES);
    expect(overlay()).toBeNull();
  });

  it("stays silent on a web build", async () => {
    await checkWhatsNewAtStart({ mode: "web", desktopInfo: async () => null });
    expect(overlay()).toBeNull();
  });
});

describe("openWhatsNew", () => {
  it("opens an accessible modal closed by the Close button", () => {
    openWhatsNew(document, [{ version: "0.1.0", markdown: "# Version 0.1.0" }]);
    const dialog = overlay();
    expect(dialog?.querySelector("[role=dialog]")).not.toBeNull();
    expect(dialog?.querySelector("[aria-modal=true]")).not.toBeNull();
    dialog?.querySelector<HTMLElement>("[data-ds-close]")?.click();
    expect(overlay()?.hasAttribute("hidden")).toBe(true);
  });
});
