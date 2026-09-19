/**
 * UI-7 — Bibliothèque : trouver, comprendre, lire, gérer.
 *
 * DOM-free (vitest, environnement node) : assertions sur les chaînes
 * produites + lecture statique de library.css pour le responsive.
 * Les routes (#/library, #/library/<kind>, #/library/<kind>/<id>) et les
 * contrats d'API sont inchangés — seuls les rendus sont refondus.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { scopeLabel } from "../libraryFormat";
import {
  createFormFieldsHtml,
  dependenciesTableHtml,
  filterLibraryResources,
  inspectorLinkHtml,
  kindFr,
  LIBRARY_KIND_FR,
  libraryDetailHtml,
  libraryKindPageHtml,
  libraryRootHtml,
  libraryTabsHtml,
  locksTableHtml,
  resourcesTableHtml,
  shadowNoteHtml,
  statusLabelFr,
  versionContentHtml,
  versionsTableHtml,
  type LibraryListState,
} from "./library";
import type { LibraryProjectLock, LibraryResource, LibraryVersion } from "../libraryApi";

const resource = (overrides: Partial<LibraryResource>): LibraryResource =>
  ({
    id: "11111111-1111-4111-8111-111111111111",
    kind: "rule",
    stable_key: "coding-standard",
    scope: "studio",
    status: "active",
    active_version: 2,
    owner_user_id: null,
    project_id: null,
    created_by_user_id: null,
    version: 3,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  }) as unknown as LibraryResource;

const version = (content: Record<string, unknown>, overrides: Partial<LibraryVersion> = {}): LibraryVersion =>
  ({
    id: "22222222-2222-4222-8222-222222222222",
    resource_id: "11111111-1111-4111-8111-111111111111",
    version: 2,
    title: "Coding standard v2",
    description: null,
    content,
    dependencies: [],
    created_by_user_id: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }) as unknown as LibraryVersion;

const blank: LibraryListState = { query: "", scope: "all", status: "all" };

/* ---------------- Racine : 5 kinds réels, français, calme ---------------- */

describe("libraryRootHtml (page #/library)", () => {
  const html = libraryRootHtml();

  it("présente les cinq catégories réelles en français", () => {
    expect(LIBRARY_KIND_FR).toHaveLength(5);
    for (const entry of LIBRARY_KIND_FR) {
      expect(html).toContain(entry.plural);
      expect(html).toContain(entry.description);
    }
    expect(html).toContain("Règles");
    expect(html).toContain("Compétences");
    expect(html).toContain("Définitions d'agents");
    expect(html).toContain("Flux de travail");
    expect(html).toContain("Profils de modèles");
  });

  it("chaque catégorie ouvre sa liste via une route stable", () => {
    expect(html).toContain('href="#/library/rules"');
    expect(html).toContain('href="#/library/skills"');
    expect(html).toContain('href="#/library/agent-definitions"');
    expect(html).toContain('href="#/library/workflows"');
    expect(html).toContain('href="#/library/model-profiles"');
  });

  it("ne montre aucune information technique au premier plan", () => {
    expect(html).not.toContain("content_schema");
    expect(html).not.toContain("stable_key");
    expect(html).not.toContain("payload");
    expect(html).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/i);
  });

  it("titre la page en français", () => {
    expect(html).toContain("<h1>Bibliothèque</h1>");
  });
});

describe("libraryTabsHtml", () => {
  it("liste les cinq catégories en français et marque la courante", () => {
    const html = libraryTabsHtml("workflows");
    expect(html).toContain(">Règles<");
    expect(html).toContain(">Compétences<");
    expect(html).toContain(">Définitions d'agents<");
    expect(html).toContain(">Flux de travail<");
    expect(html).toContain(">Profils de modèles<");
    expect(html).toContain('href="#/library/workflows"');
    expect(html).toMatch(/class="tab active" href="#\/library\/workflows"/);
    expect(html).toContain('aria-current="page"');
  });
});

describe("vocabulaire français (présentation seule)", () => {
  it("ne traduit jamais les valeurs de contrat", () => {
    expect(kindFr("rule").kind).toBe("rule");
    expect(kindFr("agent_definition").slug).toBe("agent-definitions");
    expect(scopeLabel("studio")).toBe("Studio");
    expect(scopeLabel("project")).toBe("Projet");
    expect(scopeLabel("user")).toBe("Utilisateur");
    expect(statusLabelFr("draft")).toBe("Brouillon");
    expect(statusLabelFr("active")).toBe("Actif");
    expect(statusLabelFr("deprecated")).toBe("Déprécié");
  });
});

/* ---------------- Liste : nominal, recherche, filtres ---------------- */

describe("filterLibraryResources (local, données déjà chargées)", () => {
  const all = [
    resource({ stable_key: "coding-standard", scope: "studio", status: "active" }),
    resource({ stable_key: "review-helper", scope: "project", status: "draft" }),
    resource({ stable_key: "old-linter", scope: "user", status: "deprecated" }),
  ];

  it("sans filtre retourne tout dans l'ordre serveur", () => {
    expect(filterLibraryResources(all, blank)).toEqual(all);
  });

  it("cherche dans la clé stable, insensible à la casse et aux espaces", () => {
    expect(filterLibraryResources(all, { ...blank, query: "CODING" }).map((r) => r.stable_key)).toEqual([
      "coding-standard",
    ]);
    expect(filterLibraryResources(all, { ...blank, query: "  review  " }).map((r) => r.stable_key)).toEqual([
      "review-helper",
    ]);
    expect(filterLibraryResources(all, { ...blank, query: "zzz" })).toEqual([]);
  });

  it("filtre par portée et par état réellement stockés", () => {
    expect(filterLibraryResources(all, { ...blank, scope: "project" }).map((r) => r.stable_key)).toEqual([
      "review-helper",
    ]);
    expect(filterLibraryResources(all, { ...blank, status: "deprecated" }).map((r) => r.stable_key)).toEqual([
      "old-linter",
    ]);
  });

  it("combine recherche et filtres", () => {
    expect(
      filterLibraryResources(all, { query: "e", scope: "all", status: "active" }).map((r) => r.stable_key),
    ).toEqual(["coding-standard"]);
  });
});

describe("libraryKindPageHtml (liste #/library/<kind>)", () => {
  const all = [
    resource({ stable_key: "coding-standard", scope: "studio", status: "active", active_version: 2 }),
    resource({ stable_key: "review-helper", scope: "project", status: "draft", active_version: 0 }),
  ];

  it("affiche l'en-tête FR, la création et la barre de recherche locale", () => {
    const html = libraryKindPageHtml("rule", all, blank);
    expect(html).toContain("<h1>Règles</h1>");
    expect(html).toContain("+ Nouvelle ressource");
    expect(html).toContain('role="search"');
    expect(html).toContain("Rechercher par clé stable");
    expect(html).toContain("2 élément(s) affiché(s) sur 2 chargé(s)");
    expect(html).toContain("recherche et filtres locaux");
  });

  it("présente une liste documentaire : clé stable, portée, état, version active", () => {
    const html = libraryKindPageHtml("rule", all, blank);
    expect(html).toContain("coding-standard");
    expect(html).toContain("Studio");
    expect(html).toContain("Actif");
    expect(html).toContain("Version active : v2");
    expect(html).toContain("Brouillon");
    expect(html).toContain("Aucune version activée");
    expect(html).toContain("#/library/rules/11111111-1111-4111-8111-111111111111");
    expect(html).not.toContain("<table");
  });

  it("ne montre aucune information technique au premier plan", () => {
    const html = libraryKindPageHtml("rule", all, blank);
    const [foreground] = html.split("Informations techniques");
    expect(foreground ?? html).not.toContain("content_schema");
    expect(foreground ?? html).not.toContain("payload");
    expect(html).not.toContain("11111111-1111-4111-8111-111111111111".slice(0, 36).replace(/-/g, "") + "x");
    // L'UUID complet n'est présent que dans le href de navigation, jamais en texte.
    expect(html).not.toContain(">11111111-1111-4111-8111-111111111111<");
  });

  it("distingue vide réel et aucun résultat de recherche", () => {
    expect(libraryKindPageHtml("rule", [], blank)).toContain("Aucune règle");
    expect(libraryKindPageHtml("rule", [], blank)).not.toContain("Aucun résultat");
    const noResult = libraryKindPageHtml("rule", all, { ...blank, query: "zzz" });
    expect(noResult).toContain("Aucun résultat pour cette recherche");
    expect(noResult).not.toContain("coding-standard");
  });

  it("propose portée, état et réinitialisation", () => {
    const html = libraryKindPageHtml("rule", all, blank);
    expect(html).toContain('id="library-scope"');
    expect(html).toContain('id="library-status"');
    expect(html).toContain('id="library-reset"');
    expect(html).toContain("Réinitialiser");
  });
});

describe("resourcesTableHtml", () => {
  it("rend une liste documentaire liée au détail, avec état vide contextualisé", () => {
    const html = resourcesTableHtml([resource({})]);
    expect(html).toContain("coding-standard");
    expect(html).toContain("#/library/rules/11111111-1111-4111-8111-111111111111");
    expect(html).toContain("Actif");
    expect(resourcesTableHtml([])).toContain("Aucune ressource");
  });
});

/* ---------------- Shadowing : signalé, jamais décidé ---------------- */

describe("shadowNoteHtml", () => {
  it("reste silencieux quand chaque clé vit dans une seule portée", () => {
    expect(shadowNoteHtml([resource({ stable_key: "a" }), resource({ stable_key: "b" })])).toBe("");
  });

  it("signale en français sans désigner de gagnant, avec lien Inspecteur", () => {
    const html = shadowNoteHtml([
      resource({ stable_key: "a", scope: "user" }),
      resource({ stable_key: "a", scope: "studio" }),
    ]);
    expect(html).toContain("Plusieurs portées");
    expect(html).toContain("ne choisit pas");
    expect(html).toContain("#/inspector");
    expect(html).toContain('role="note"');
  });
});

/* ---------------- Création : contrat préservé, champs par kind ---------------- */

describe("createFormFieldsHtml (POST /library, Idempotency-Key par tentative)", () => {
  it("conserve les noms de champs du contrat pour les règles", () => {
    const html = createFormFieldsHtml("rule");
    expect(html).toContain('name="stable_key"');
    expect(html).toContain('name="scope"');
    expect(html).toContain('name="project_id"');
    expect(html).toContain('name="title"');
    expect(html).toContain('name="description"');
    expect(html).toContain('name="text"');
    expect(html).toContain("Informations principales");
    expect(html).toContain("Paramètres avancés");
  });

  it("adapte les champs au kind sans masquer le contrat", () => {
    expect(createFormFieldsHtml("agent_definition")).toContain('name="summary"');
    expect(createFormFieldsHtml("model_profile")).toContain('name="reasoning"');
    expect(createFormFieldsHtml("workflow")).toContain('name="summary"');
    const workflow = createFormFieldsHtml("workflow");
    expect(workflow).toContain("Participants");
    expect(workflow).toContain("Entrées du flux");
  });

  it("garde les erreurs accessibles et la mention de non-duplication", () => {
    const html = createFormFieldsHtml("rule");
    expect(html).toContain('data-msg');
    expect(html).toContain('role="alert"');
    expect(html).toContain("Un envoi répété ne crée pas de doublon.");
  });
});

/* ---------------- Détail : lecture d'abord, technique repliée ---------------- */

describe("libraryDetailHtml (#/library/<kind>/<id>)", () => {
  const versions = [
    version({ content_schema: "studio.library.rule/v1", text: "Always verify." }, { version: 1, title: "Coding standard v1" }),
    version({ content_schema: "studio.library.rule/v1", text: "Always verify twice." }, { version: 2, title: "Coding standard v2" }),
  ];

  it("titre avec le contenu courant, UUID relégué aux détails repliés", () => {
    const html = libraryDetailHtml(resource({}), versions, [], []);
    expect(html).toContain("Coding standard v2");
    expect(html).toContain("Always verify twice.");
    expect(html).toContain("Contenu actuel — v2");
    // L'UUID complet n'apparaît qu'après le repli « Informations techniques ».
    const [reading, tech] = html.split("Informations techniques");
    expect(reading ?? "").not.toContain("11111111-1111-4111-8111-111111111111");
    expect(tech ?? "").toContain("11111111-1111-4111-8111-111111111111");
  });

  it("affiche portée, état et version active en badges avec libellés", () => {
    const html = libraryDetailHtml(resource({}), versions, [], []);
    expect(html).toContain("Studio");
    expect(html).toContain("Actif");
    expect(html).toContain("Version active : v2");
    expect(html).toContain("← Retour aux règles");
  });

  it("replie les détails techniques par défaut", () => {
    const html = libraryDetailHtml(resource({}), versions, [], []);
    expect(html).toContain("<details");
    expect(html).toContain("Informations techniques");
    expect(html).toContain("content_schema");
    expect(html).toContain("studio.library.rule/v1");
    // Technique après le contenu de lecture.
    expect(html.indexOf("Contenu actuel")).toBeLessThan(html.indexOf("Informations techniques"));
  });

  it("garde l'historique accessible sans dominer : versions repliables, active ouverte", () => {
    const html = libraryDetailHtml(resource({}), versions, [], []);
    expect(html).toContain("Historique des versions");
    expect(html).toContain("2 version(s)");
    expect(html).toContain("Coding standard v1");
    expect(html).toContain("Always verify.");
    expect(html).toMatch(/<details class="library-version" open>/);
  });

  it("préserve Activate / Deprecate / nouvelle version / verrous avec leurs contrats", () => {
    const html = libraryDetailHtml(resource({}), versions, [], []);
    expect(html).toContain("Activer une version");
    expect(html).toContain('name="version"');
    expect(html).toContain("Déprécier");
    expect(html).toContain("+ Nouvelle version");
    expect(html).toContain('name="version_title"');
    expect(html).toContain("Verrous projet");
    expect(html).toContain("n'empêche jamais un commit Git");
    expect(html).toContain('name="lock_project_id"');
    expect(html).toContain('name="lock_version"');
  });

  it("signale le shadowing de la ressource quand il existe, silencieux sinon", () => {
    const shadowed = libraryDetailHtml(
      resource({}),
      versions,
      [],
      [resource({}), resource({ id: "99999999-9999-4999-8999-999999999999", scope: "project" })],
    );
    expect(shadowed).toContain("plusieurs portées");
    expect(shadowed).toContain("Inspecteur de résolution");
    expect(libraryDetailHtml(resource({}), versions, [], [resource({})])).not.toContain("plusieurs portées");
  });

  it("affiche les verrous filtrés à la ressource avec action de libération", () => {
    const lock = {
      id: "33333333-3333-4333-8333-333333333333",
      project_id: "44444444-4444-4444-8444-444444444444",
      resource_id: "11111111-1111-4111-8111-111111111111",
      locked_version: 2,
      created_by_user_id: null,
      created_at: "2026-01-01T00:00:00Z",
    } as unknown as LibraryProjectLock;
    const html = libraryDetailHtml(resource({}), versions, [lock], []);
    expect(html).toContain("v2");
    expect(html).toContain('data-release-lock="33333333-3333-4333-8333-333333333333"');
    expect(html).toContain("Libérer");
  });

  it("gère l'absence de version active sans inventer de contenu", () => {
    const html = libraryDetailHtml(resource({ active_version: 0 }), [], [], []);
    expect(html).toContain("Aucune version activée");
    expect(html).toContain("Aucune version enregistrée.");
  });
});

describe("inspectorLinkHtml (deep link, agent-definitions uniquement)", () => {
  it("propose « Inspecter la résolution » pour les définitions d'agents", () => {
    const html = inspectorLinkHtml(resource({ kind: "agent_definition", stable_key: "review-agent" }));
    expect(html).toContain("Inspecter la résolution");
    expect(html).toContain("#/inspector/review-agent");
    expect(html).not.toContain("Open stableKey");
  });

  it("ne propose rien pour les autres kinds", () => {
    expect(inspectorLinkHtml(resource({ kind: "rule" }))).toBe("");
    expect(inspectorLinkHtml(resource({ kind: "workflow" }))).toBe("");
  });
});

/* ---------------- Contenus par kind : cohérents, jamais uniformisés ---------------- */

describe("versionContentHtml", () => {
  it("rend le texte règle / compétence lisible et échappé, sans schéma au premier plan", () => {
    const html = versionContentHtml("rule", version({ content_schema: "studio.library.rule/v1", text: "<b>be safe</b>" }));
    expect(html).toContain("&lt;b&gt;be safe&lt;/b&gt;");
    expect(html).not.toContain("<b>be safe</b>");
    expect(html).not.toContain("content_schema");
  });

  it("rend l'identité d'une définition d'agent de façon structurée", () => {
    const html = versionContentHtml(
      "agent_definition",
      version({ content_schema: "studio.library.agent_definition/v1", summary: "Reviews", intended_use: "Relire" }),
    );
    expect(html).toContain("Reviews");
    expect(html).toContain("Relire");
    expect(html).toContain("Usage prévu");
  });

  it("affiche les exigences d'un profil sans jamais statuer sur la compatibilité", () => {
    const html = versionContentHtml(
      "model_profile",
      version({ content_schema: "studio.library.model_profile/v1", requirements: { coding: true } }),
    );
    expect(html).toContain("Coding");
    expect(html).toContain("Inspecteur");
    expect(html).not.toContain("Compatible");
    expect(html).not.toContain("compatible");
    expect(html).not.toMatch(/score/i);
  });

  it("rend participants et enchaînement déclaré d'un flux, sans graphique inventé", () => {
    const html = versionContentHtml(
      "workflow",
      version({
        content_schema: "studio.library.workflow/v1",
        participants: [
          { participant_id: "implementer", agent_stable_key: "impl", depends_on: [], inputs: [], outputs: [] },
          { participant_id: "tester", agent_stable_key: "test", depends_on: ["implementer"], inputs: [], outputs: [] },
        ],
        inputs: [],
        outputs: [],
      }),
    );
    expect(html).toContain("implementer");
    expect(html).toContain("tester");
    expect(html).toContain("implementer → tester");
    expect(html).toContain("n'exécute jamais");
    expect(html).not.toContain("<svg");
    expect(html).not.toContain("<canvas");
  });

  it("dégrade proprement un contenu de flux non canonique", () => {
    expect(versionContentHtml("workflow", version({}))).toContain("non canonique");
  });
});

/* ---------------- Versions, dépendances, verrous ---------------- */

describe("versionsTableHtml", () => {
  it("liste la plus récente d'abord avec la version active marquée", () => {
    const html = versionsTableHtml(
      [version({}, { version: 1, title: "v1" }), version({}, { version: 2, title: "Coding standard v2" })],
      2,
    );
    expect(html).toContain("Active");
    expect(html.indexOf("Coding standard v2")).toBeLessThan(html.indexOf("v1"));
  });
});

describe("locksTableHtml", () => {
  it("explique le sens utilisateur et rend version figée + libération", () => {
    const lock = {
      id: "33333333-3333-4333-8333-333333333333",
      project_id: "44444444-4444-4444-8444-444444444444",
      resource_id: "11111111-1111-4111-8111-111111111111",
      locked_version: 2,
      created_by_user_id: null,
      created_at: "2026-01-01T00:00:00Z",
    } as unknown as LibraryProjectLock;
    const html = locksTableHtml([lock]);
    expect(html).toContain("v2");
    expect(html).toContain("figée");
    expect(html).toContain('data-release-lock="33333333-3333-4333-8333-333333333333"');
    expect(locksTableHtml([])).toContain("Aucun verrou");
  });
});

describe("dependenciesTableHtml", () => {
  it("nomme le type épinglé, la version et la relation en français", () => {
    const html = dependenciesTableHtml([{ kind: "skill", stable_key: "code-review", version: 5, relation: "uses_skill" }]);
    expect(html).toContain("Compétence");
    expect(html).toContain("code-review");
    expect(html).toContain("v5");
    expect(html).toContain("uses skill");
    expect(dependenciesTableHtml([])).toContain("Aucune dépendance");
  });
});

/* ---------------- Transverse : CSP, responsive, clavier ---------------- */

describe("transverse UI-7", () => {
  it("aucun style inline ni handler inline dans les gabarits", () => {
    const samples = [
      libraryRootHtml(),
      libraryKindPageHtml("rule", [resource({})], blank),
      libraryDetailHtml(resource({}), [version({ text: "x" })], [], []),
      createFormFieldsHtml("workflow"),
      versionContentHtml("model_profile", version({ requirements: { coding: true } })),
    ].join("\n");
    expect(samples).not.toMatch(/\sstyle\s*=/i);
    expect(samples).not.toMatch(/\son[a-z]+\s*=/i);
    expect(samples).not.toContain("javascript:");
  });

  it("hiérarchie de titres, live regions et clavier (details natifs, labels, focus)", () => {
    const detail = libraryDetailHtml(resource({}), [version({ text: "x" })], [], []);
    expect(detail).toContain("<h1>");
    expect(detail).toContain("<h2>Contenu actuel");
    expect(detail).toContain("<h2>Historique des versions");
    expect(detail).toContain('role="alert"');
    expect(detail).toContain("<details");
    expect(detail).toContain("<summary>");
    // La live region du compteur vit sur la liste (recherche locale).
    expect(libraryKindPageHtml("rule", [resource({})], blank)).toContain('aria-live="polite"');
    expect(createFormFieldsHtml("rule")).toContain("<label");
  });

  it("statuts jamais couleur seule (libellé explicite systématique)", () => {
    const list = libraryKindPageHtml(
      "rule",
      [resource({ status: "active" }), resource({ status: "deprecated" })],
      blank,
    );
    expect(list).toContain("Actif");
    expect(list).toContain("Déprécié");
  });

  it("library.css : responsive sans scroll global, modale contenue", () => {
    const css = readFileSync(join(__dirname, "library.css"), "utf-8");
    expect(css).toContain("@media (max-width: 640px)");
    expect(css).toContain("grid-template-columns: 1fr");
    expect(css).not.toContain("overflow-x: auto");
    expect(css).toContain("min-width: 200px");
  });
});
