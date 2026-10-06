/**
 * UI-5 / P04-task-detail — Fiche action-first FR : héros à action primaire
 * unique, prochaine action, blocages/validation prioritaires, sessions /
 * journaux / automatisations repliés, propriétés en latéral, PATCH versionné
 * 409, prise distinguée des Claims, compléments best-effort jamais bloquants.
 *
 * DOM-free (vitest, environnement node) : assertions sur les chaînes produites.
 */
import { describe, expect, it } from "vitest";
import { resetActorNames, setActorNames } from "../actorNames";
import {
  aiWorkStatusLabel,
  aiWorkStatusTone,
  canReleaseTask,
  launchSectionHtml,
  nextActionText,
  releaseTaskConfirmText,
  sessionStateLabel,
  taskConflictNotice,
  taskDetailErrorHtml,
  taskDetailHtml,
  taskDetailLoadingHtml,
  taskDetailStatusState,
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

/**
 * Ce que l'on lit sans cliquer : les blocs <details> sont repliés fermés par
 * défaut, leur contenu est donc retiré avant de contrôler le texte visible.
 */
const unfoldedText = (markup: string): string =>
  markup
    .replace(/<details\b[\s\S]*?<\/details>/g, "")
    .replace(/<[^>]*>/g, " ");

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
  /** Partie après la carte héros : ordre réel des blocs de la fiche. */
  const body = html.slice(html.indexOf("</section>") + "</section>".length);

  it("héros : titre h1, point de statut DS, responsable, action primaire unique", () => {
    expect(html).toContain("<h1>Optimiser les éclairages</h1>");
    expect(html).toContain("T-001");
    expect(html).toContain("ds-status");
    expect(html).toContain("En cours");
    expect(html).toContain("Disponible");
    expect(html).toContain("Ouvrir le projet");
    expect(html).toContain("Prendre cette tâche");
    // UNE action primaire dans le héros (C1), le secondaire reste un lien.
    const [hero] = html.split("</section>");
    expect(hero?.match(/ds-btn--primary/g)).toHaveLength(1);
    expect(hero).toContain('id="task-head-take"');
    expect(hero).toContain('class="ds-hero-link task-hero-link" type="button" id="task-head-edit"');
  });

  it("tête sans défilement : objectif et prochaine action dans le héros", () => {
    const heroEnd = html.indexOf("</section>");
    for (const marker of ["Objectif", "Revoir les sampler densities.", "Prochaine action", "Faire la relecture"]) {
      expect(html.indexOf(marker)).toBeGreaterThan(-1);
      expect(html.indexOf(marker)).toBeLessThan(heroEnd);
    }
  });

  it("blocages et validation juste après le héros, avant la mécanique", () => {
    expect(body).toContain("Blocages");
    expect(body).toContain("Aucun blocage");
    expect(body).toContain("Réécriture du sampler");
    expect(taskDetailHtml(data({ worklogs: [] }))).toContain("Rien à valider");
    const order = ["Blocages", "Validation", "Modifier la tâche", "Prise en charge", "Sessions, journaux et automatisations"];
    let last = -1;
    for (const marker of order) {
      const at = body.indexOf(marker);
      expect(at).toBeGreaterThan(last);
      last = at;
    }
  });

  it("fonctions conservées : modification, prise, sessions/IA, automatisations, propriétés", () => {
    expect(html).toContain("Modifier la tâche");
    expect(html).toContain("Prise en charge");
    expect(html).toContain("data-claim");
    expect(html).toContain("data-release");
    expect(html).toContain("id=\"task-edit-form\"");
    expect(html).toContain("Sessions (2)");
    expect(html).toContain("Travail IA (1)");
    expect(html).toContain("Automatisations");
    expect(html).toContain('id="task-launch-panel"');
    expect(html).toContain("Propriétés");
    expect(html).toContain("Responsable");
  });

  it("divulgation progressive : sessions, journaux, automatisations et technique repliés fermés", () => {
    // Deux blocs repliés, aucun ouvert, et les ancres du panneau de
    // lancement pointent toujours vers leurs sections.
    expect(html.match(/<details/g)).toHaveLength(2);
    expect(html).not.toMatch(/<details[^>]*open/);
    expect(html).toContain('<details class="ds-tech task-detail-fold" id="task-mecanique">');
    expect(html).toContain('id="task-sessions"');
    expect(html).toContain('id="task-ai-work"');
    expect(html).toContain('id="task-automatisations"');
    expect(html).toContain("Détails techniques");
  });

  it("distingue prise de tâche et réservations de ressources", () => {
    expect(html).toContain("À ne pas confondre avec les réservations de ressources");
    expect(html).toContain("Libérer garde le statut tel quel");
  });

  it("technique repliée : UUID, version interne et dates ISO hors du premier plan", () => {
    expect(html).toContain("t1");
    expect(html).toContain("Statut interne");
    const text = unfoldedText(html);
    // Aucun identifiant ni date brute tant que le bloc reste fermé.
    expect(text).not.toContain("11111111-2222");
    expect(text).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
    // Une seule mention légitime : la protection de version du formulaire.
    expect(text.match(/version 4/g)).toHaveLength(1);
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
  it("tâche prise : nom de machine, aucun identifiant, action Libérer", () => {
    const held = {
      ...(baseTask as unknown as Record<string, unknown>),
      claimed_by_machine_id: "abcdef12-3456",
    } as never;
    const html = taskDetailHtml(data({ task: held }));
    expect(html).toContain("Prise par la machine");
    expect(html).not.toContain("abcdef12");
    expect(html).not.toContain("indicatif");
    expect(html).toContain("Libérer");
    setActorNames([{ id: "abcdef12-3456", display_name: "flo-laptop" }], []);
    const named = taskDetailHtml(data({ task: held }));
    expect(named).toContain('<span class="actor-name">flo-laptop</span>');
    expect(named).not.toContain("abcdef12");
    resetActorNames();
  });

  it("confirmation de libération : nomme la machine et l'agent détenteurs", () => {
    const held = {
      ...(baseTask as unknown as Record<string, unknown>),
      claimed_by_machine_id: "abcdef12-3456",
      claimed_by_agent_id: "agent-9876",
    } as never;
    setActorNames([{ id: "abcdef12-3456", display_name: "flo-laptop" }], [{ id: "agent-9876", display_name: "claude-dev" }]);
    const text = releaseTaskConfirmText(held);
    expect(text).toContain("machine flo-laptop");
    expect(text).toContain("agent claude-dev");
    expect(text).toContain("détenteur ou à un administrateur");
    expect(text).not.toContain("<");
    resetActorNames();
  });

  it("libérer : détenteur ou admin seulement (indice UI, identité inconnue = actif)", () => {
    const held = {
      ...(baseTask as unknown as Record<string, unknown>),
      claimed_by_machine_id: "abcdef12-3456",
    } as never;
    const me = { user_id: "u1", display_name: "Flo", email: "f@x", role: "developer", machine_id: "abcdef12-3456" };
    expect(canReleaseTask(held, true, me)).toBe(true);
    expect(canReleaseTask(held, true, { ...me, machine_id: "other" })).toBe(false);
    expect(canReleaseTask(held, true, { ...me, machine_id: "other", role: "admin" })).toBe(true);
    expect(canReleaseTask(held, true, null)).toBe(true);
    expect(canReleaseTask(held, false, me)).toBe(false);
    expect(canReleaseTask(baseTask, true, me)).toBe(false);

    const other = taskDetailHtml(data({ task: held, canRelease: false }));
    expect(other).toContain("data-release disabled");
    expect(other).toContain("ou un administrateur, peut la libérer");
    const admin = taskDetailHtml(data({ task: held, canRelease: true }));
    expect(admin).not.toContain("data-release disabled");
  });

  it("lecture seule : actions désactivées sans disparaître", () => {
    const html = taskDetailHtml(data({ authed: false }));
    expect(html).toContain("disabled");
    expect(html).not.toContain('id="task-head-take"');
    expect(html).toContain("Prise en charge");
    // Sans connexion, aucune action primaire : rien n'est proposé en vain.
    const [hero] = html.split("</section>");
    expect(hero).not.toContain("ds-btn--primary");
    expect(hero).toContain('id="task-head-edit"');
  });
});

describe("sessions lisibles, jamais de payload", () => {
  it("état, agent, début/fin, machine", () => {
    const html = taskDetailHtml(data());
    expect(html).toContain("En cours");
    expect(html).toContain("Terminée");
    expect(html).toContain("Agent non renseigné");
    expect(html).toContain("Agent <span class=\"actor-name actor-name--unknown\">Agent sans nom</span>");
    expect(html).not.toContain("indicative");
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

describe("héros action-first (P04-task-detail)", () => {
  const asTask = (patch: Record<string, unknown>) =>
    ({ ...(baseTask as unknown as Record<string, unknown>), ...patch }) as never;

  it("point de statut DS par statut métier", () => {
    expect(taskDetailStatusState("in_progress")).toBe("info");
    expect(taskDetailStatusState("blocked")).toBe("warning");
    expect(taskDetailStatusState("completed")).toBe("success");
    expect(taskDetailStatusState("created")).toBe("idle");
  });

  it("prochaine action dérivée de l'état réel, sans checklist inventée", () => {
    expect(nextActionText(baseTask, 1)).toContain("Faire la relecture");
    expect(nextActionText(asTask({ status: "blocked" }), 0)).toContain("Débloquer");
    expect(nextActionText(asTask({ status: "created" }), 0)).toContain("Prendre la tâche");
    expect(nextActionText(asTask({ status: "created", claimed_by_machine_id: "m1" }), 0)).toContain("Démarrer");
    expect(nextActionText(asTask({ status: "completed" }), 0)).toContain("Vérifier");
    expect(nextActionText(asTask({ claimed_by_machine_id: "m1" }), 0)).toContain("Poursuivre");
    // Une tâche bloquée ne peut pas progresser : le blocage passe avant la
    // relecture, même quand un travail attend déjà un avis.
    expect(nextActionText(asTask({ status: "blocked" }), 2)).toContain("Débloquer");
  });

  it("bloquée : alerte prioritaire, pas de vide rassurant", () => {
    const html = taskDetailHtml(data({ task: asTask({ status: "blocked" }) }));
    expect(html).toContain("Tâche bloquée");
    expect(html).not.toContain("Aucun blocage");
  });

  it("relecture en attente : validation prioritaire et prochaine action", () => {
    const html = taskDetailHtml(data());
    expect(html).toContain("Validation");
    expect(html).toContain("Réécriture du sampler");
  });

  it("propriétés latérales, jamais d'UUID lisible par défaut", () => {
    const html = taskDetailHtml(data());
    expect(html).toContain('aria-label="Propriétés"');
    expect(html).toContain("<aside class=\"task-detail-props\"");
    const text = unfoldedText(html);
    expect(text).not.toContain("11111111-2222");
    // Le repli garde la donnée, il la retire seulement de la lecture.
    expect(html).toContain("11111111-2222-4333-8444-555555555555");
  });
});

describe("launchSectionHtml (AIB R4)", () => {
  it("rend le panneau « Lancer sur… » avec les machines éligibles", () => {
    const html = launchSectionHtml(
      data({
        launch: {
          machines: [
            {
              machine_id: "m1",
              display_name: "flo-laptop",
              status: "online",
              eligible: true,
              free_slots: 1,
            } as never,
          ],
          agents: [],
          latest: null,
        },
      }),
    );
    expect(html).toContain('id="task-launch-panel"');
    expect(html).toContain("Lancer sur…");
    expect(html).toContain("flo-laptop");
  });

  it("sans données : indisponibilité affichée, aucun état inventé", () => {
    expect(launchSectionHtml(data())).toContain("Machines éligibles indisponibles");
  });
});
