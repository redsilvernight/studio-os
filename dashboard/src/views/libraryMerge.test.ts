// @vitest-environment happy-dom
/**
 * P62a-ui-3panes — Comparaison trois volets : base, override, nouveau
 * commun + aperçu du résultat. Le moteur Python n'est pas réexécuté :
 * les données sont fournies (fixtures miroir de `merge_texts`).
 */
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  bindLibraryMerge,
  libraryMergeHtml,
  remainingConflicts,
  renderLibraryMerge,
  resolveMergeContent,
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
      conflicts: [{ start_line: 4, base_start: 3, base_end: 4, base: conflictBase, ours: conflictOurs, theirs: conflictTheirs }],
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
    expect(html).toContain('data-merge-conflict-link="1"');
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
      result: { content: SCRIPT, conflicts: [{ start_line: 1, base_start: 0, base_end: 1, base: SCRIPT, ours: SCRIPT, theirs: SCRIPT }] },
    };
    const html = libraryMergeHtml(evil);
    expect(html).toContain("&lt;script&gt;");
    // Aucun élément script réel : le texte reste inerte (même convention que library-hooks.spec).
    expect(html).not.toContain("<script>");
    expect(html).not.toMatch(/<script[\s>]/);
  });
});

describe("fournisseur de comparaison", () => {
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

  it("n'affiche les choix de fusion que si le fournisseur sait appliquer", async () => {
    const without = document.createElement("div");
    await renderLibraryMerge(without, staticMergeProvider(fixture()));
    expect(without.querySelector("[data-merge-revert]")).toBeNull();
    expect(without.querySelector("[data-merge-hunk]")).toBeNull();
    const withApply = document.createElement("div");
    await renderLibraryMerge(withApply, { ...staticMergeProvider(fixture()), apply: () => Promise.resolve() });
    expect(withApply.querySelector("[data-merge-revert]")?.textContent).toBe("Revenir au commun");
    expect(withApply.querySelector("[data-merge-keep]")?.textContent).toBe("Garder mon override");
  });

  it("Revenir au commun : confirme, applique, affiche l'erreur et rend la main", async () => {
    const confirm = vi.spyOn(window, "confirm");
    const apply = vi.fn().mockRejectedValueOnce(new Error("conflit de version")).mockResolvedValueOnce(undefined);
    const root = document.createElement("div");
    await renderLibraryMerge(root, { ...staticMergeProvider(fixture()), apply });
    const button = root.querySelector<HTMLButtonElement>("[data-merge-revert]")!;
    confirm.mockReturnValueOnce(false);
    button.click();
    expect(apply).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    button.click();
    await Promise.resolve();
    await Promise.resolve();
    expect(apply).toHaveBeenCalledWith({ choice: "revert_to_common" });
    expect(root.querySelector("[data-merge-msg]")?.textContent).toBe("conflit de version");
    expect(button.disabled).toBe(false);
    root.querySelector<HTMLButtonElement>("[data-merge-keep]")!.click();
    expect(apply).toHaveBeenLastCalledWith({ choice: "keep_override" });
    confirm.mockRestore();
  });
});

describe("P62b — acceptation par bloc", () => {
  const twoConflicts = (): LibraryMergeData["result"] => ({
    content: "a\n<<<<<<< ours\nmoi 1\n=======\neux 1\n>>>>>>> theirs\nb\n<<<<<<< ours\nmoi 2\n=======\neux 2\n>>>>>>> theirs\n",
    conflicts: [
      { start_line: 2, base_start: 1, base_end: 2, base: "x1\n", ours: "moi 1\n", theirs: "eux 1\n" },
      { start_line: 8, base_start: 3, base_end: 4, base: "x2\n", ours: "moi 2\n", theirs: "eux 2\n" },
    ],
  });

  it("resolveMergeContent remplace chaque bloc choisi et garde les autres", () => {
    const result = twoConflicts();
    expect(resolveMergeContent(result, ["theirs", "ours"])).toBe("a\neux 1\nb\nmoi 2\n");
    expect(resolveMergeContent(result, ["both", "base"])).toBe("a\nmoi 1\neux 1\nb\nx2\n");
    const partial = resolveMergeContent(result, [null, "theirs"]);
    expect(partial).toBe("a\n<<<<<<< ours\nmoi 1\n=======\neux 1\n>>>>>>> theirs\nb\neux 2\n");
    expect(remainingConflicts(partial)).toBe(1);
  });

  it("préserve l'absence de saut de ligne final et les fragments vides", () => {
    const result = {
      content: "<<<<<<< ours\nmine\n=======\n>>>>>>> theirs\n",
      conflicts: [{ start_line: 1, base_start: 0, base_end: 1, base: "base", ours: "mine", theirs: "" }],
    };
    expect(resolveMergeContent(result, ["ours"])).toBe("mine");
    expect(resolveMergeContent(result, ["theirs"])).toBe("");
    expect(resolveMergeContent(result, ["base"])).toBe("base");
  });

  it("compteur de conflits restants et publication bloquée tant qu'un conflit reste", async () => {
    const apply = vi.fn().mockResolvedValue(undefined);
    const root = document.createElement("div");
    await renderLibraryMerge(root, { load: () => Promise.resolve({ inputs: fixture().inputs, result: twoConflicts() }), apply });
    const publish = root.querySelector<HTMLButtonElement>("[data-merge-publish]")!;
    const remaining = root.querySelector("[data-merge-remaining]")!;
    expect(remaining.textContent).toBe("2 conflit(s) restant(s)");
    expect(publish.disabled).toBe(true);
    const pick = (index: number, value: string): void => {
      const radio = root.querySelector<HTMLInputElement>(`[data-merge-hunk="${index}"][value="${value}"]`)!;
      radio.checked = true;
      radio.dispatchEvent(new Event("change"));
    };
    pick(0, "theirs");
    expect(remaining.textContent).toBe("1 conflit(s) restant(s)");
    expect(publish.disabled).toBe(true);
    publish.click();
    expect(apply).not.toHaveBeenCalled();
    pick(1, "ours");
    expect(remaining.textContent).toBe("0 conflit(s) restant(s)");
    expect(publish.disabled).toBe(false);
    expect(root.querySelector<HTMLTextAreaElement>("[data-merge-result]")!.value).toBe("a\neux 1\nb\nmoi 2\n");
  });
});

describe("P62c — résultat éditable et publication", () => {
  it("l'édition revalide : marqueurs isolés ou texte vide bloquent la publication", async () => {
    const root = document.createElement("div");
    await renderLibraryMerge(root, { ...staticMergeProvider(fixture()), apply: () => Promise.resolve() });
    const editor = root.querySelector<HTMLTextAreaElement>("[data-merge-result]")!;
    const publish = root.querySelector<HTMLButtonElement>("[data-merge-publish]")!;
    const validation = root.querySelector("[data-merge-validation]")!;
    const edit = (text: string): void => {
      editor.value = text;
      editor.dispatchEvent(new Event("input"));
    };
    edit("texte\n=======\n");
    expect(publish.disabled).toBe(true);
    expect(validation.textContent).toContain("marqueurs");
    edit("   ");
    expect(validation.textContent).toBe("Le résultat est vide.");
    edit("ligne une\nmon choix final\n");
    expect(publish.disabled).toBe(false);
    expect(validation.textContent).toBe("Prêt à publier.");
  });

  it("publie le texte édité après une seule confirmation et affiche le refus serveur", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const apply = vi.fn().mockRejectedValueOnce(new Error("invalid_content")).mockResolvedValueOnce(undefined);
    const root = document.createElement("div");
    await renderLibraryMerge(root, { ...staticMergeProvider(fixture()), apply });
    const editor = root.querySelector<HTMLTextAreaElement>("[data-merge-result]")!;
    editor.value = "résolu à la main\n";
    editor.dispatchEvent(new Event("input"));
    const publish = root.querySelector<HTMLButtonElement>("[data-merge-publish]")!;
    publish.click();
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(apply).toHaveBeenCalledWith({ choice: "merge", content: "résolu à la main\n" });
    await Promise.resolve();
    await Promise.resolve();
    expect(root.querySelector("[data-merge-msg]")?.textContent).toBe("invalid_content");
    expect(publish.disabled).toBe(false);
    confirm.mockRestore();
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

  it("réserve la comparaison pour un override actif dont la base a changé", () => {
    const html = libraryDetailHtml(resource({ scope: "user", status: "active", base_update_available: true, base_active_version: 4 }), versions, [], []);
    expect(html).toContain("data-library-merge-preview");
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
