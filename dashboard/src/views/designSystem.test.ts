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
      "Divulgation progressive",
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
      "ds-empty--error",
      "ds-hero",
      "ds-tech",
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
  it("aligns on the tools wireframe: internal eyebrow, hero, 4 cards + context", () => {
    const html = designSystemHtml();
    expect(html).toContain("Interne · absente de la navigation");
    expect(html).toContain('class="ds-hero"');
    expect(html).toContain("Voir les états");
    expect(html.match(/class="ds-card tool-stack"/g) ?? []).toHaveLength(4);
    expect(html).toContain('class="ds-card tool-context"');
  });

  it("demonstrates the five shared states through the shared component", () => {
    const html = designSystemHtml();
    for (const state of ["Introuvable", "Vide", "Chargement", "Erreur", "Hors ligne"]) {
      expect(html).toContain(state);
    }
    expect(html).toContain("ds-state-actions");
    expect(html).toContain("ds-notice--warning");
    // Les notices gardent leurs quatre tons, désormais en colonne de contexte.
    for (const tone of ["success", "warning", "danger", "info"]) {
      expect(html).toContain(`ds-notice--${tone}`);
    }
  });
});
