/**
 * UI-4 — Page Projets : cartes DS, filtre client honnête, création en modale.
 *
 * DOM-free (vitest, environnement node) : assertions sur les chaînes
 * produites + lecture statique de projects.css pour le responsive.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  filterProjects,
  projectCreateFormHtml,
  projectsLoadingHtml,
  projectsPageHtml,
  projectsUnauthenticatedHtml,
  type ProjectsPageState,
} from "./projects";

const ID_A = "11111111-2222-4333-8444-555555555555";
const ID_B = "22222222-3333-4444-9555-666666666666";

const projectA = {
  id: ID_A,
  slug: "phare",
  name: "Jeu Phare",
  description: "Le jeu principal du studio",
  archived: false,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-10T10:00:00Z",
  version: 3,
} as never;

const projectB = {
  id: ID_B,
  slug: "digue",
  name: "Digue",
  description: null,
  archived: true,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-02T10:00:00Z",
  version: 1,
} as never;

const all = [projectA, projectB] as never[];
const blank: ProjectsPageState = { query: "", stateFilter: "all" };

describe("filterProjects (client-side, données déjà chargées)", () => {
  it("sans filtre retourne tous les projets dans l'ordre serveur", () => {
    expect(filterProjects(all, blank)).toEqual(all);
  });

  it("filtre par nom, description ou slug, insensible à la casse", () => {
    expect(filterProjects(all, { query: "PHARE", stateFilter: "all" }).map((p) => p.id)).toEqual([ID_A]);
    expect(filterProjects(all, { query: "principal du studio", stateFilter: "all" }).map((p) => p.id)).toEqual([
      ID_A,
    ]);
    expect(filterProjects(all, { query: "digue", stateFilter: "all" }).map((p) => p.id)).toEqual([ID_B]);
  });

  it("ignore les espaces superflus et ne touche jamais au réseau (pur)", () => {
    expect(filterProjects(all, { query: "  phare  ", stateFilter: "all" }).map((p) => p.id)).toEqual([ID_A]);
    expect(filterProjects(all, { query: "zzz", stateFilter: "all" })).toEqual([]);
  });

  it("filtre d'état : actifs / archivés / tous", () => {
    expect(filterProjects(all, { query: "", stateFilter: "active" }).map((p) => p.id)).toEqual([ID_A]);
    expect(filterProjects(all, { query: "", stateFilter: "archived" }).map((p) => p.id)).toEqual([ID_B]);
  });

  it("combine recherche et état", () => {
    expect(filterProjects(all, { query: "e", stateFilter: "archived" }).map((p) => p.id)).toEqual([ID_B]);
  });
});

describe("projectsPageHtml nominal", () => {
  const html = projectsPageHtml({ projects: all, state: blank, authed: true });

  it("affiche l'en-tête, l'action de création et la barre de filtre local", () => {
    expect(html).toContain("<h1>Projets</h1>");
    expect(html).toContain("Nouveau projet");
    expect(html).toContain('role="search"');
    expect(html).toContain("filtre local");
    expect(html).toContain("2 projet(s) affiché(s) sur 2 chargé(s)");
  });

  it("présente des cartes (nom, description, état, slug) sans tableau base de données", () => {
    expect(html).toContain("Jeu Phare");
    expect(html).toContain("Le jeu principal du studio");
    expect(html).toContain("Actif");
    expect(html).toContain("Archivé");
    expect(html).toContain("phare");
    expect(html).toContain(`href="#/projects/${ID_A}"`);
    expect(html).not.toContain("<table");
    expect(html).not.toContain("<th>");
  });

  it("relègue UUID/version/horodatages dans un détail secondaire", () => {
    expect(html).toContain("Détails techniques");
    expect(html).toContain(ID_A);
    const [foreground] = html.split("Détails techniques");
    expect(foreground).not.toContain(`>${ID_A}<`);
    expect(foreground).not.toMatch(/Version<\/|v3/);
  });

  it("n'invente aucun indicateur de progression ou score", () => {
    expect(html).not.toMatch(/progress|pourcent|%|health|score/i);
    expect(html).not.toContain("<progress");
  });

  it("inclut la modale de création cachée, labellisée et accessible", () => {
    expect(html).toContain('id="project-create-dialog"');
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain("Slug");
    expect(html).toContain("Description (facultative)");
    expect(html).toContain('role="alert"');
  });

  it("ne produit aucun style inline ni handler inline (CSP DEC-0061)", () => {
    expect(html).not.toMatch(/\sstyle\s*=/i);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toContain("javascript:");
  });
});

describe("projectsPageHtml états", () => {
  it("vide : explique et propose la création", () => {
    const html = projectsPageHtml({ projects: [], state: blank, authed: true });
    expect(html).toContain("Aucun projet");
    expect(html).toContain("Nouveau projet");
  });

  it("filtre sans résultat : distingue du vide réel", () => {
    const html = projectsPageHtml({ projects: all, state: { query: "zzz", stateFilter: "all" }, authed: true });
    expect(html).toContain("ne correspond au filtre");
    expect(html).toContain("0 projet(s) affiché(s) sur 2 chargé(s)");
  });

  it("chargement : squelette DS en français", () => {
    const html = projectsLoadingHtml();
    expect(html).toContain("ds-skeleton");
    expect(html).toContain("Projets");
    expect(html).not.toContain("Loading");
  });

  it("non authentifié : propose la connexion sans jargon", () => {
    const html = projectsUnauthenticatedHtml();
    expect(html).toContain("Connectez-vous");
    expect(html).not.toContain("machine token");
  });
});

describe("projectCreateFormHtml", () => {
  it("champs labellisés, aide, erreur alert cachée, double action", () => {
    const html = projectCreateFormHtml();
    expect(html).toContain('for="project-slug"');
    expect(html).toContain('for="project-name"');
    expect(html).toContain('for="project-desc"');
    expect(html).toContain("required");
    expect(html).toContain('id="project-create-error"');
    expect(html).toContain("hidden");
    expect(html).toContain("Annuler");
    expect(html).toContain("Créer le projet");
    expect(html).toMatch(/idempotence/i);
  });

  it("échappe le contenu (jamais d'injection via les aides)", () => {
    expect(projectCreateFormHtml()).not.toMatch(/\son[a-z]+\s*=/i);
  });
});

describe("projects.css responsive", () => {
  const css = readFileSync(join(__dirname, "projects.css"), "utf-8");

  it("grille fluide auto-fill, une colonne sur mobile", () => {
    expect(css).toMatch(/auto-fill\s*,\s*minmax/);
    expect(css).toMatch(/@media[^{]*max-width:\s*640px/);
  });

  it("aucun style inline attendu : classes seules", () => {
    expect(css).not.toContain("<style");
  });
});
