/**
 * UI-5 — Tâches Liste/Tableau : filtres honnêtes, présentation FR,
 * création en modale, statuts traduits sans toucher aux clés.
 *
 * DOM-free (vitest, environnement node) : assertions sur les chaînes
 * produites + lecture statique de tasks.css pour le responsive.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  filterTasks,
  initialTasksState,
  isTasksDefaultState,
  taskCreateFormHtml,
  taskMoveControlHtml,
  tasksBoardHtml,
  tasksListHtml,
  tasksLoadingHtml,
  tasksPageHtml,
  tasksToolbarHtml,
  type TasksPageState,
} from "./tasks";

const P1 = "11111111-2222-4333-8444-555555555555";
const P2 = "22222222-3333-4444-9555-666666666666";

const task = (
  id: string,
  status: string,
  title: string,
  extra: Record<string, unknown> = {},
) =>
  ({
    id,
    project_id: P1,
    readable_id: null,
    title,
    description: null,
    status,
    claimed_by_machine_id: null,
    claimed_by_agent_id: null,
    created_at: "2026-09-10T10:00:00Z",
    updated_at: "2026-09-11T10:00:00Z",
    version: 1,
    ...extra,
  }) as never;

const t1 = task("t1", "created", "Caméra Android bloquée");
const t2 = task("t2", "in_progress", "Optimiser les éclairages", {
  description: "Revoir les sampler densities",
  claimed_by_machine_id: "abcdef12-3456-7890-abcd-ef1234567890",
});
const t3 = task("t3", "blocked", "Corriger le build", { project_id: P2 });
const all = [t1, t2, t3] as never[];
const names = { [P1]: "Jeu Phare", [P2]: "Digue" };
const blank: TasksPageState = initialTasksState();

const pageData = (state: TasksPageState, tasks: typeof all = all) => ({
  tasks,
  state,
  limit: 100,
  exhausted: true,
  authed: true,
  scopeLabel: "Tous les projets",
  projectId: undefined,
  projects: [],
  projectNames: names,
  msg: { human: "" },
});

describe("initialTasksState / isTasksDefaultState", () => {
  it("démarre en Liste, sans filtre ni recherche", () => {
    expect(blank).toEqual({ view: "list", filter: "all", query: "" });
    expect(isTasksDefaultState(blank)).toBe(true);
    expect(isTasksDefaultState({ ...blank, view: "board" })).toBe(true);
    expect(isTasksDefaultState({ ...blank, filter: "blocked" })).toBe(false);
    expect(isTasksDefaultState({ ...blank, query: "cam" })).toBe(false);
  });
});

describe("filterTasks (client-side, données déjà chargées)", () => {
  it("sans filtre retourne tout, dans l'ordre du serveur", () => {
    expect(filterTasks(all, blank, names)).toEqual(all);
  });

  it("filtre par statut exact", () => {
    expect(filterTasks(all, { ...blank, filter: "blocked" }, names).map((t) => t.id)).toEqual(["t3"]);
  });

  it("recherche locale titre + description + projet, insensible à la casse", () => {
    expect(filterTasks(all, { ...blank, query: "ÉCLAIRAGES" }, names).map((t) => t.id)).toEqual(["t2"]);
    expect(filterTasks(all, { ...blank, query: "sampler" }, names).map((t) => t.id)).toEqual(["t2"]);
    expect(filterTasks(all, { ...blank, query: "digue" }, names).map((t) => t.id)).toEqual(["t3"]);
    expect(filterTasks(all, { ...blank, query: "  caméra  " }, names).map((t) => t.id)).toEqual(["t1"]);
  });

  it("combine statut et recherche, sans réordonner", () => {
    expect(
      filterTasks(all, { ...blank, filter: "created", query: "caméra" }, names).map((t) => t.id),
    ).toEqual(["t1"]);
    expect(filterTasks(all, { ...blank, filter: "created", query: "zzz" }, names)).toEqual([]);
  });

  it("ne touche jamais au réseau (pur) et ne trie pas", () => {
    const reversed = [...all].reverse();
    expect(filterTasks(reversed, blank, names).map((t) => t.id)).toEqual(["t3", "t2", "t1"]);
  });
});

describe("tasksToolbarHtml", () => {
  const html = tasksToolbarHtml(blank, 3, 3);

  it("propose Liste/Tableau avec état explicite, pas de couleur seule", () => {
    expect(html).toContain('role="group"');
    expect(html).toContain("Présentation des tâches");
    expect(html).toContain(">Liste</button>");
    expect(html).toContain(">Tableau</button>");
    expect(html).toContain('data-view="list" aria-pressed="true"');
    expect(html).toContain('data-view="board" aria-pressed="false"');
  });

  it("filtre statut FR + recherche locale honnête + réinitialisation", () => {
    expect(html).toContain("Tous les statuts");
    expect(html).toContain("À faire");
    expect(html).toContain("En cours");
    expect(html).toContain("Bloqué");
    expect(html).toContain("Terminé");
    expect(html).toContain('type="search"');
    expect(html).toContain("déjà chargées");
    expect(html).toContain("Réinitialiser");
    expect(html).toContain("3 tâche(s) affichée(s) sur 3 chargée(s)");
    expect(html).not.toContain("TODO");
    expect(html).not.toContain("IN PROGRESS");
  });

  it("CSP : aucun handler inline ni style", () => {
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
  });
});

describe("tasksListHtml (vue par défaut)", () => {
  const html = tasksListHtml(all, { authed: true, showProject: true, projectNames: names });

  it("montre titre, projet, statut FR, signal de prise — pas de technique", () => {
    expect(html).toContain("Caméra Android bloquée");
    expect(html).toContain("Jeu Phare");
    expect(html).toContain("Digue");
    expect(html).toContain("À faire");
    expect(html).toContain("En cours");
    expect(html).toContain("Bloqué");
    expect(html).toContain("Disponible");
    expect(html).toContain("Prise · machine abcdef12…");
    expect(html).toContain("Revoir les sampler densities");
  });

  it("ne met ni UUID ni version ni horodatage au premier plan", () => {
    // Texte visible uniquement (hors attributs fonctionnels href/id/data-*).
    const text = html.replace(/<[^>]*>/g, " ");
    expect(text).not.toContain("11111111-2222");
    expect(text).not.toContain("2026-09-1");
    expect(text).not.toMatch(/version \d+/i);
    expect(html).not.toContain("Informations techniques");
    expect(html).not.toContain("<code");
  });

  it("chaque ligne ouvre le détail et propose le déplacement clavier", () => {
    expect(html).toContain('href="#/tasks/t1"');
    expect(html).toContain("Déplacer vers…");
    expect(html).toContain(">Déplacer</button>");
  });

  it("n'affiche ni priorité ni assigné inventés", () => {
    expect(html).not.toMatch(/priorit/i);
    expect(html).not.toMatch(/assign/i);
  });
});

describe("tasksBoardHtml", () => {
  const html = tasksBoardHtml(all, { authed: true, showProject: false, projectNames: names });

  it("quatre colonnes FR avec comptes, cartes épurées", () => {
    expect(html).toContain("À faire");
    expect(html).toContain("En cours");
    expect(html).toContain("Bloqué");
    expect(html).toContain("Terminé");
    expect(html).toContain('data-column="TODO"');
    expect(html).toContain('data-column="IN PROGRESS"');
    expect(html).toContain('class="kanban tasks-board"');
    expect(html).not.toContain(">TODO<");
    expect(html).not.toContain(">IN PROGRESS<");
    expect(html).not.toContain(">BLOCKED<");
    expect(html).not.toContain(">DONE<");
  });

  it("cartes : titre + contexte utile, activation vers le détail", () => {
    expect(html).toContain('data-card="t1"');
    expect(html).toContain('data-version="1"');
    expect(html).toContain('data-status-current="created"');
    expect(html).toContain('href="#/tasks/t2"');
    expect(html).toContain("Déplacer vers…");
  });

  it("colonnes vides explicites, pas de silhouette fantôme", () => {
    expect(tasksBoardHtml([], { authed: true, showProject: false })).toContain("Aucune tâche ici.");
  });
});

describe("taskMoveControlHtml (alternative clavier au drag & drop)", () => {
  it("libellé explicite, options FR, statut courant présélectionné", () => {
    const html = taskMoveControlHtml(t2 as never, true);
    expect(html).toContain("Déplacer vers…");
    expect(html).toContain('for="move-t2"');
    expect(html).toContain('<option value="in_progress" selected>En cours</option>');
    expect(html).toContain(">Déplacer</button>");
  });

  it("désactivé en lecture seule", () => {
    const html = taskMoveControlHtml(t2 as never, false);
    expect(html).toContain("disabled");
  });
});

describe("taskCreateFormHtml (modale, Idempotency-Key préservée)", () => {
  it("champs FR + sélecteur de projet en contexte global", () => {
    const html = taskCreateFormHtml(undefined, [{ id: P1, name: "Jeu Phare", slug: "phare" }] as never, "Tous les projets");
    expect(html).toContain("Projet");
    expect(html).toContain("Titre");
    expect(html).toContain("Description (facultative)");
    expect(html).toContain("Jeu Phare");
    expect(html).toContain("Créer la tâche");
    expect(html).toContain("Annuler");
    expect(html).toContain("Un envoi répété ne crée pas de doublon.");
  });

  it("projet fixé et affiché en contexte scopé", () => {
    const html = taskCreateFormHtml(P1, [], "Projet phare");
    expect(html).not.toContain('name="project_id"');
    expect(html).toContain("Projet phare");
  });

  it("validation accessible : erreur alertée, labels associés", () => {
    const html = taskCreateFormHtml(P1, [], "Projet phare");
    expect(html).toContain('role="alert"');
    expect(html).toContain('for="task-title"');
  });
});

describe("tasksPageHtml nominal", () => {
  it("en-tête FR, action de création, pagination honnête : pas d'anglais résiduel", () => {
    const html = tasksPageHtml(pageData(blank));
    expect(html).toContain("<h1>Tâches</h1>");
    expect(html).toContain("Nouvelle tâche");
    expect(html).toContain("Actualiser");
    expect(html).toContain("Toutes les tâches chargées.");
    expect(html).toContain("ordre du serveur");
    for (const word of ["Reload", "Load more", "Move", "Create", "New task", "Open", "unclaimed"]) {
      expect(html).not.toContain(word);
    }
  });

  it("vue Tableau sur demande, avec aide drag & drop + clavier", () => {
    const html = tasksPageHtml(pageData({ ...blank, view: "board" }));
    expect(html).toContain('data-view="board" aria-pressed="true"');
    expect(html).toContain("Glissez une carte");
    expect(html).toContain("Déplacer vers…");
  });

  it("vide global vs vide après filtre : deux messages distincts", () => {
    expect(tasksPageHtml(pageData(blank, []))).toContain("Aucune tâche");
    const filtered = tasksPageHtml(pageData({ ...blank, query: "zzz" }));
    expect(filtered).toContain("Aucune tâche ne correspond aux filtres");
    expect(filtered).toContain("Réinitialiser les filtres");
  });

  it("lecture seule : pas de création ni de déplacement, mention claire", () => {
    const html = tasksPageHtml({ ...pageData(blank), authed: false });
    expect(html).not.toContain("Nouvelle tâche");
    expect(html).toContain("Lecture seule");
    expect(html).toContain("disabled");
  });

  it("contexte projet : pas de colonne projet redondante, pas de sélecteur", () => {
    const html = tasksPageHtml({ ...pageData(blank), projectId: P1, scopeLabel: "Projet phare" });
    expect(html).toContain("Projet phare");
    expect(html).not.toContain("Jeu Phare");
  });

  it("chargement : squelette DS, pas de jargon", () => {
    const html = tasksLoadingHtml("Tous les projets");
    expect(html).toContain("<h1>Tâches</h1>");
    expect(html).toContain("Chargement en cours");
    expect(html).not.toMatch(/GET \//);
  });

  it("embarqué workspace : titre en h2, un seul h1 par page", () => {
    const html = tasksPageHtml({ ...pageData(blank), projectId: P1, headingLevel: 2 });
    expect(html).not.toContain("<h1>");
    expect(html).toContain("<h2>Tâches</h2>");
    expect(html).toContain("Nouvelle tâche");
  });

  it("CSP : aucun handler inline ni style", () => {
    expect(tasksPageHtml(pageData(blank))).not.toMatch(/\son[a-z]+\s*=/i);
    expect(tasksPageHtml(pageData(blank))).not.toMatch(/\sstyle\s*=/i);
  });
});

describe("tasks.css responsive", () => {
  const css = readFileSync(join(__dirname, "tasks.css"), "utf8");

  it("tableau : défilement horizontal LOCAL sous 900px, colonnes confortables", () => {
    expect(css).toContain("@media (max-width: 900px)");
    expect(css).toContain(".tasks-board");
    expect(css).toContain("overflow-x: auto");
    expect(css).toContain("minmax(250px");
  });

  it("mobile 375 : barre d'outils empilée, cartes enveloppées", () => {
    expect(css).toContain("@media (max-width: 640px)");
  });

  it("aucun scroll horizontal global imposé par les tâches", () => {
    expect(css).not.toMatch(/body\s*\{[^}]*overflow-x/s);
  });
});
