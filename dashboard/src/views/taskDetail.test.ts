/**
 * UI-5 — Détail tâche : page de travail FR, édition versionnée 409,
 * prise en charge distinguée des Claims, sessions et AI work lisibles,
 * compléments best-effort jamais bloquants.
 *
 * DOM-free (vitest, environnement node) : assertions sur les chaînes produites.
 */
import { describe, expect, it } from "vitest";
import {
  aiWorkStatusLabel,
  aiWorkStatusTone,
  sessionStateLabel,
  taskConflictNotice,
  taskDetailErrorHtml,
  taskDetailHtml,
  taskDetailLoadingHtml,
  taskEditFormHtml,
  type SessionRow,
  type TaskDetailData,
  type WorkRow,
} from "./taskDetail";

const P1 = "11111111-2222-4333-8444-555555555555";

const baseTask = {
  id: "t1",
  project_id: P1,
  readable_id: "T-001",
  title: "Optimiser les éclairages",
  description: "Revoir les sampler densities.",
  status: "in_progress",
  claimed_by_machine_id: null,
  claimed_by_agent_id: null,
  created_at: "2026-09-10T10:00:00Z",
  updated_at: "2026-09-11T10:00:00Z",
  version: 4,
} as never;

const sessionOpen: SessionRow = {
  id: "s1",
  machine_id: "abcdef12-3456-7890-abcd-ef1234567890",
  agent_id: null,
  started_at: "2026-09-11T09:00:00Z",
  ended_at: null,
};

const sessionClosed: SessionRow = {
  id: "s2",
  machine_id: "m2",
  agent_id: "a1",
  started_at: "2026-09-10T09:00:00Z",
  ended_at: "2026-09-10T11:30:00Z",
};

const work: WorkRow = {
  id: "w1",
  summary: "Réécriture du sampler avec tests",
  status: "review_requested",
  started_at: "2026-09-11T10:00:00Z",
  agent_profile: "dev-front",
  model: "muse-spark",
  changed_files: ["a.ts", "b.ts"],
  tests_run: ["vitest run"],
};

const data = (overrides: Partial<TaskDetailData> = {}): TaskDetailData => ({
  task: baseTask,
  sessions: [sessionOpen, sessionClosed],
  worklogs: [work],
  taskClaims: 2,
  notice: "",
  authed: true,
  ...overrides,
});

describe("taskDetailLoadingHtml / taskDetailErrorHtml", () => {
  it("chargement : squelette DS, identifiant tronqué", () => {
    const html = taskDetailLoadingHtml("t1");
    expect(html).toContain("Chargement en cours");
    expect(html).not.toMatch(/GET \//);
  });

  it("erreur : message humain, pas de page blanche", () => {
    const html = taskDetailErrorHtml("t1", "HTTP 404 · task not found");
    expect(html).toContain("Tâche indisponible");
    expect(html).toContain("HTTP 404");
  });
});

describe("taskDetailHtml nominal", () => {
  const html = taskDetailHtml(data());

  it("en-tête : titre, statut FR, prise, actions principales", () => {
    expect(html).toContain("Optimiser les éclairages");
    expect(html).toContain("T-001");
    expect(html).toContain("En cours");
    expect(html).toContain("Disponible");
    expect(html).toContain("Prendre");
    expect(html).toContain("Modifier");
    // Aucune clé brute comme texte visible au premier plan (les attributs
    // value="/href et la section technique repliée les conservent, à raison).
    const [foreground] = html.split("Informations techniques");
    for (const key of ["created", "in_progress", "blocked", "completed"]) {
      expect(foreground).not.toContain(`>${key}<`);
    }
  });

  it("sections lisibles : vue générale, modification, prise, sessions, IA", () => {
    expect(html).toContain("Vue générale");
    expect(html).toContain("Revoir les sampler densities.");
    expect(html).toContain("Ouvrir le projet");
    expect(html).toContain("Modifier la tâche");
    expect(html).toContain("Prise en charge");
    expect(html).toContain("Sessions (2)");
    expect(html).toContain("Travail IA (1)");
  });

  it("distingue prise de tâche et réservations de ressources", () => {
    expect(html).toContain("À ne pas confondre avec les réservations de ressources");
    expect(html).toContain("Libérer garde le statut tel quel");
  });

  it("technique secondaire repliée : UUID/version/dates hors du premier plan", () => {
    expect(html).toContain("Informations techniques");
    expect(html).toContain("t1");
    const [foreground] = html.split("Informations techniques");
    const text = (foreground ?? "").replace(/<[^>]*>/g, " ");
    expect(text).not.toContain("11111111-2222");
    // Une seule mention légitime : la protection de version du formulaire.
    expect(text.match(/version 4/g)).toHaveLength(1);
    expect(text).not.toContain("2026-09-1");
  });

  it("compteur de réservations best-effort : lien vers l'onglet Réservations", () => {
    expect(html).toContain("Réservations de ressources liées : 2");
    expect(html).toContain(`#/projects/${P1}/claims`);
  });

  it("CSP : aucun handler inline ni style", () => {
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
  });
});

describe("taskEditFormHtml (PATCH versionné)", () => {
  it("champs FR, statut traduit, version affichée en secondaire", () => {
    const html = taskEditFormHtml(baseTask, true);
    expect(html).toContain("Titre");
    expect(html).toContain("Description (facultative)");
    expect(html).toContain("Statut");
    expect(html).toContain('<option value="in_progress" selected>En cours</option>');
    expect(html).toContain("version 4");
    expect(html).toContain("Enregistrer");
  });

  it("lecture seule : champs désactivés, mention claire", () => {
    const html = taskEditFormHtml(baseTask, false);
    expect(html).toContain("disabled");
    expect(html).toContain("Lecture seule");
  });
});

describe("taskConflictNotice (409, relecture sans retry)", () => {
  it("explique humainement : changé ailleurs, données rechargées", () => {
    const notice = taskConflictNotice(7);
    expect(notice).toContain("changé ailleurs");
    expect(notice).toContain("version 7");
    expect(notice).toContain("rechargées");
    expect(taskDetailHtml(data({ notice }))).toContain(notice);
  });
});

describe("prise en charge (claim/release machine)", () => {
  it("tâche prise : machine indicative, action Libérer", () => {
    const held = {
      ...(baseTask as unknown as Record<string, unknown>),
      claimed_by_machine_id: "abcdef12-3456",
    } as never;
    const html = taskDetailHtml(data({ task: held }));
    expect(html).toContain("Prise par la machine");
    expect(html).toContain("abcdef12");
    expect(html).toContain("Libérer");
  });

  it("lecture seule : actions désactivées sans disparaître", () => {
    const html = taskDetailHtml(data({ authed: false }));
    expect(html).toContain("disabled");
    expect(html).not.toContain('id="task-head-take"');
    expect(html).toContain("Prise en charge");
  });
});

describe("sessions lisibles, jamais de payload", () => {
  it("état, agent, début/fin, machine indicative", () => {
    const html = taskDetailHtml(data());
    expect(html).toContain("En cours");
    expect(html).toContain("Terminée");
    expect(html).toContain("Agent non renseigné");
    expect(html).toContain("Agent a1");
    expect(html).toContain("indicative");
    expect(html).not.toContain("unvalidated");
    expect(html).not.toContain("Machine (unvalidated)");
  });

  it("vide utile vs indisponible : deux messages distincts", () => {
    expect(taskDetailHtml(data({ sessions: [] }))).toContain("Aucune session");
    const down = taskDetailHtml(data({ sessions: null }));
    expect(down).toContain("Sessions indisponibles");
    expect(down).toContain("Sessions (?)");
    expect(down).toContain("Optimiser les éclairages");
  });
});

describe("travail IA lisible, actions existantes préservées", () => {
  it("résumé, statut FR, contexte agent, volumes", () => {
    const html = taskDetailHtml(data());
    expect(html).toContain("Réécriture du sampler");
    expect(html).toContain("En relecture");
    expect(html).toContain("dev-front");
    expect(html).toContain("muse-spark");
    expect(html).toContain("2 fichier(s)");
    expect(html).toContain("1 test(s)");
  });

  it("vide utile vs indisponible, sans déplacer la logique Review (UI-8)", () => {
    expect(taskDetailHtml(data({ worklogs: [] }))).toContain("Aucun travail IA");
    expect(taskDetailHtml(data({ worklogs: null }))).toContain("Travail IA indisponible");
    expect(taskDetailHtml(data())).not.toContain("Approuver");
  });
});

describe("best-effort claims : omis proprement en cas d'échec", () => {
  it("aucune mention bloquante quand le compteur est inconnu", () => {
    const html = taskDetailHtml(data({ sessions: null, worklogs: null, taskClaims: null }));
    expect(html).not.toContain("Réservations de ressources liées");
    expect(html).not.toContain("ds-notice--danger");
    expect(html).toContain("Optimiser les éclairages");
  });
});

describe("statuts IA et sessions (unités)", () => {
  it("libellés FR sans clés brutes", () => {
    expect(aiWorkStatusLabel("started")).toBe("Commencé");
    expect(aiWorkStatusLabel("review_requested")).toBe("En relecture");
    expect(aiWorkStatusLabel("changes_requested")).toBe("Modifications demandées");
    expect(aiWorkStatusLabel("mystery")).toBe("mystery");
  });

  it("teintes : échec en danger, relecture en IA", () => {
    expect(aiWorkStatusTone("failed")).toBe("danger");
    expect(aiWorkStatusTone("review_requested")).toBe("ai");
    expect(aiWorkStatusTone("approved")).toBe("success");
    expect(aiWorkStatusTone("started")).toBe("info");
  });

  it("session ouverte vs terminée", () => {
    expect(sessionStateLabel(sessionOpen)).toEqual({ label: "En cours", tone: "info" });
    expect(sessionStateLabel(sessionClosed)).toEqual({ label: "Terminée", tone: "neutral" });
  });
});
