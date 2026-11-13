// @vitest-environment happy-dom
/**
 * P62a-ui-3panes — Comparaison trois volets : base, override, nouveau
 * commun + aperçu du résultat. Le moteur Python n'est pas réexécuté :
 * les données sont fournies (fixtures miroir de `merge_texts`).
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  bindLibraryMerge,
  LIBRARY_MERGE_NO_API_NOTE,
  libraryMergeHtml,
  libraryMergeSectionHtml,
  renderLibraryMerge,
  staticMergeProvider,
  type LibraryMergeData,
} from "./libraryMerge";
import { libraryDetailHtml } from "./library";
import type { LibraryResource, LibraryVersion } from "../libraryApi";

const SCRIPT = "<script>window.mergeExecuted = true</script>";

/** Fixture miroir du moteur Python : édition disjointe + un bloc en conflit. */
function fixture(): LibraryMergeData {
  const base = "ligne une\nligne deux\nligne trois\n";
  const ours = "ligne une\nligne deux (moi)\nligne trois\n";
  const theirs = "ligne une\nligne deux\nligne trois (commun)\n";
  const conflictBase = "commun\n";
  const conflictOurs = "commun (moi)\n";
  const conflictTheirs = "commun (eux)\n";
  const content =
    "ligne une\nligne deux (moi)\nligne trois (commun)\n<<<<<<< ours\ncommun (moi)\n=======\ncommun (eux)\n>>>>>>> theirs\n";
  return {
    inputs: { base, ours, theirs },
    result: {
      content,
      conflicts: [{ startLine: 4, baseStart: 3, baseEnd: 4, base: conflictBase, ours: conflictOurs, theirs: conflictTheirs }],
    },
  };
}

describe("libraryMergeHtml (trois volets + aperçu)", () => {
  it("affiche trois volets focalisables avec rôles et labels ARIA français", () => {
    const html = libraryMergeHtml(fixture());
    for (const label of ["Base commune", "Ma version", "Nouveau commun"]) {
      expect(html).toContain(`aria-label="${label}`);
    }
    expect(html).toContain('role="region"');
    expect(html).toContain('role="group"');
    expect(html.match(/tabindex="0"/g)?.length).toBeGreaterThanOrEqual(3);
    const order = [html.indexOf("Base commune"), html.indexOf("Ma version"), html.indexOf("Nouveau commun")];
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it("montre l'aperçu du résultat et la liste des conflits ancrés", () => {
    const html = libraryMergeHtml(fixture());
    expect(html).toContain("Aperçu du résultat");
    expect(html).toContain("ligne deux (moi)");
    expect(html).toContain('id="library-merge-conflict-1"');
    expect(html).toContain('href="#library-merge-conflict-1"');
    expect(html).toContain("Conflit 1 — ligne 4");
    expect(html).toContain("1 conflit(s)");
  });

  it("annonce une fusion nette sans inventer de conflit", () => {
    const data = fixture();
    const clean: LibraryMergeData = {
      inputs: data.inputs,
      result: { content: "ligne une\nligne deux (moi)\n", conflicts: [] },
    };
    const html = libraryMergeHtml(clean);
    expect(html).toContain("Aucun conflit");
    expect(html).not.toContain("library-merge-conflict-");
  });

  it("échappe tout contenu injecté (volets, aperçu, conflits)", () => {
    const data = fixture();
    const evil: LibraryMergeData = {
      inputs: { base: SCRIPT, ours: SCRIPT, theirs: SCRIPT },
      result: { content: SCRIPT, conflicts: [{ startLine: 1, baseStart: 0, baseEnd: 1, base: SCRIPT, ours: SCRIPT, theirs: SCRIPT }] },
    };
    const html = libraryMergeHtml(evil);
    expect(html).toContain("&lt;script&gt;");
    // Aucun élément script réel : le texte reste inerte (même convention que library-hooks.spec).
    expect(html).not.toContain("<script>");
    expect(html).not.toMatch(/<script[\s>]/);
  });
});

describe("fournisseur injectable (aucune route API inventée)", () => {
  it("documente l'absence de route de fusion", () => {
    expect(LIBRARY_MERGE_NO_API_NOTE).toMatch(/aucune route api/i);
    expect(libraryMergeSectionHtml(null)).toContain("Comparaison indisponible");
    expect(libraryMergeSectionHtml(null)).toContain("data-library-merge=\"unavailable\"");
  });

  it("staticMergeProvider rejoue les données fournies", async () => {
    const data = fixture();
    const provider = staticMergeProvider(data);
    await expect(provider.load()).resolves.toBe(data);
  });

  it("renderLibraryMerge peint le chargement, le succès puis lie le clavier", async () => {
    const root = document.createElement("div");
    const pending = renderLibraryMerge(root, staticMergeProvider(fixture(), "test"));
    expect(root.innerHTML).toContain("Chargement de la comparaison");
    await pending;
    expect(root.innerHTML).toContain("Base commune");
    expect(root.innerHTML).toContain("Aperçu du résultat");
  });

  it("renderLibraryMerge affiche l'erreur du fournisseur sans inventer de données", async () => {
    const root = document.createElement("div");
    await renderLibraryMerge(root, { label: "cassé", load: () => Promise.reject(new Error("coupé")) });
    expect(root.innerHTML).toContain("Comparaison indisponible");
    expect(root.innerHTML).toContain("coupé");
  });
});

describe("bindLibraryMerge (clavier entre volets)", () => {
  function mounted(): HTMLElement {
    const root = document.createElement("div");
    root.innerHTML = libraryMergeHtml(fixture());
    document.body.appendChild(root);
    bindLibraryMerge(root);
    const panes = [...root.querySelectorAll<HTMLElement>(".library-merge-pane")];
    expect(panes).toHaveLength(3);
    return root;
  }

  function key(target: Element, keyValue: string): void {
    target.dispatchEvent(new KeyboardEvent("keydown", { key: keyValue, bubbles: true, cancelable: true }));
  }

  it("flèches droite/gauche circulent entre les trois volets", () => {
    const root = mounted();
    const [base, ours, theirs] = [...root.querySelectorAll<HTMLElement>(".library-merge-pane")];
    base!.focus();
    key(base!, "ArrowRight");
    expect(document.activeElement).toBe(ours);
    key(ours!, "ArrowRight");
    expect(document.activeElement).toBe(theirs);
    key(theirs!, "ArrowRight");
    expect(document.activeElement).toBe(base);
    key(base!, "ArrowLeft");
    expect(document.activeElement).toBe(theirs);
    root.remove();
  });

  it("Début/Fin sautent aux extrémités, les autres touches sont ignorées", () => {
    const root = mounted();
    const [base, , theirs] = [...root.querySelectorAll<HTMLElement>(".library-merge-pane")];
    theirs!.focus();
    key(theirs!, "Home");
    expect(document.activeElement).toBe(base);
    key(base!, "End");
    expect(document.activeElement).toBe(theirs);
    key(theirs!, "a");
    expect(document.activeElement).toBe(theirs);
    root.remove();
  });

  it("sans volets, aucun gestionnaire ne lève", () => {
    const root = document.createElement("div");
    expect(() => bindLibraryMerge(root)).not.toThrow();
  });
});

describe("intégration page détail (additive)", () => {
  const resource = (overrides: Partial<LibraryResource> = {}): LibraryResource =>
    ({
      id: "11111111-1111-4111-8111-111111111111",
      kind: "rule",
      stable_key: "coding-standard",
      scope: "user",
      status: "active",
      active_version: 1,
      owner_user_id: null,
      project_id: null,
      created_by_user_id: null,
      version: 1,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
      ...overrides,
    }) as unknown as LibraryResource;

  const versions: LibraryVersion[] = [];

  it("sans données : page inchangée, sans section de comparaison", () => {
    const html = libraryDetailHtml(resource({}), versions, [], []);
    expect(html).not.toContain("Comparaison trois volets");
  });

  it("base périmée sans données : repli honnête, jamais de volets inventés", () => {
    const html = libraryDetailHtml(resource({ base_update_available: true, base_active_version: 4 }), versions, [], []);
    expect(html).toContain("Comparaison indisponible");
    expect(html).not.toContain("library-merge-panes");
  });

  it("données fournies : trois volets et aperçu dans le détail", () => {
    const html = libraryDetailHtml(resource({}), versions, [], [], true, fixture());
    expect(html).toContain("Comparaison trois volets");
    expect(html).toContain("library-merge-panes");
    expect(html).toContain("Aperçu du résultat");
  });
});

describe("library.css (fusion : lisible, empilé sur mobile)", () => {
  it("trois colonnes sur desktop, une colonne sous 640px, sans scroll global", () => {
    const css = readFileSync(join(__dirname, "library.css"), "utf-8");
    expect(css).toContain(".library-merge-panes");
    expect(css).toContain("repeat(3, minmax(0, 1fr))");
    expect(css).toContain("@media (max-width: 640px)");
    expect(css).not.toContain("overflow-x: auto");
  });
});
