import { describe, expect, it } from "vitest";
import { designSystemHtml } from "./designSystem";

describe("designSystemHtml (internal UI-1 demo, DEC-0078)", () => {
  it("presents every primitive family with breathing room", () => {
    const html = designSystemHtml();
    for (const section of [
      "Boutons",
      "Badges et statuts",
      "Champs",
      "Onglets",
      "Tableaux",
      "Listes",
      "États",
      "Indicateurs",
      "Modale et tiroir",
      "Notifications",
      "Infobulle",
    ]) {
      expect(html).toContain(section);
    }
    for (const marker of [
      "ds-btn--primary",
      "ds-badge--ai",
      "ds-status",
      'role="tablist"',
      "ds-table",
      "ds-list",
      "ds-empty",
      "ds-skeleton",
      "ds-metric",
      "ds-progress",
      "ds-agent",
      'role="dialog"',
      "data-ds-tip",
    ]) {
      expect(html).toContain(marker);
    }
  });

  it("states the keyboard contracts on the page", () => {
    const html = designSystemHtml();
    expect(html).toContain("Échap");
    expect(html).toContain("flèches");
    expect(html).toContain("Tab");
  });

  it("contains no inline style or event-handler attributes (CSP, DEC-0061)", () => {
    const html = designSystemHtml();
    expect(html).not.toMatch(/<[^>]*\sstyle\s*=/i);
    expect(html).not.toMatch(/<[^>]*\son[a-z]+\s*=/i);
  });

  it("is French-first: no English user-facing string leaks", () => {
    const html = designSystemHtml();
    // data-ds-close / ds-btn--loading are code hooks, not user text.
    const userText = html.replace(/data-ds-close|ds-btn--loading/g, "");
    expect(userText).not.toMatch(/Loading|Nothing to show|See all|Sign in|Submit/i);
  });
});
