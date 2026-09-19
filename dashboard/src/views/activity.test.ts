/**
 * UI-4 — Onglet Activité : timeline lisible depuis GET /timeline, jamais un
 * dump JSON. DOM-free : chaînes pures + lecture statique de workspace.css.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  activityLoadingHtml,
  countTimelineEvents,
  TIMELINE_LIMIT_DEFAULT,
  TIMELINE_LIMIT_MAX,
  timelineEventActor,
  timelineEventContext,
  timelineEventLabel,
  timelineHtml,
} from "./activity";

const baseEvent = {
  event_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  project_id: "p1",
  task_id: null,
  machine_id: null,
  actor_type: "user",
  actor_id: "11111111-2222-4333-8444-555555555555",
  client_timestamp: "2026-09-12T09:00:00Z",
  server_timestamp: "2026-09-12T09:00:01Z",
  payload: {},
  schema_version: 1,
} as never;

const event = (overrides: Record<string, unknown> = {}) =>
  ({ ...(baseEvent as unknown as Record<string, unknown>), ...overrides }) as never;

const timeline = (...days: Array<{ date: string; events: never[] }>) =>
  ({ project_id: "p1", days }) as never;

describe("timelineEventLabel", () => {
  it("libelle chaque domaine en français", () => {
    expect(timelineEventLabel("task.created")).toBe("Tâche créée");
    expect(timelineEventLabel("task.blocked")).toBe("Tâche bloquée");
    expect(timelineEventLabel("resource.claimed")).toBe("Ressource réservée");
    expect(timelineEventLabel("resource.conflict")).toBe("Chevauchement de réservation");
    expect(timelineEventLabel("decision.created")).toBe("Décision créée");
    expect(timelineEventLabel("build.failed")).toBe("Build échoué");
    expect(timelineEventLabel("transfer.ready")).toBe("Transfert prêt");
    expect(timelineEventLabel("git.pr.merged")).toBe("Pull request fusionnée");
  });

  it("couvre tous les types du contrat et tolère les futurs inconnus", () => {
    const known = [
      "project.created",
      "task.created",
      "task.started",
      "task.updated",
      "task.blocked",
      "task.completed",
      "session.started",
      "session.ended",
      "resource.claimed",
      "resource.renewed",
      "resource.released",
      "resource.conflict",
      "decision.proposed",
      "decision.created",
      "library.version.created",
      "library.version.activated",
      "library.resource.deprecated",
      "library.lock.set",
      "library.lock.released",
      "agent.started",
      "agent.stopped",
      "ai_work.started",
      "ai_work.completed",
      "ai_work.failed",
      "ai_work.review_requested",
      "ai_work.approved",
      "ai_work.changes_requested",
      "git.commit",
      "git.branch.changed",
      "git.pr.opened",
      "git.pr.merged",
      "graph.updated",
      "memory.proposed",
      "memory.updated",
      "godot.started",
      "godot.stopped",
      "recording.started",
      "recording.finished",
      "recording.marker.created",
      "build.started",
      "build.succeeded",
      "build.failed",
      "producer.job.requested",
      "producer.job.completed",
      "producer.job.failed",
      "transfer.created",
      "transfer.uploading",
      "transfer.ready",
      "transfer.downloaded",
      "transfer.expired",
      "transfer.deleted",
      "marketing.candidate.created",
      "marketing.post.published",
    ];
    for (const type of known) {
      expect(timelineEventLabel(type)).not.toBe("Événement");
    }
    expect(timelineEventLabel("future.unknown_thing")).toBe("Événement");
  });
});

describe("timelineEventContext", () => {
  it("extrait la première clé d'affichage connue, jamais le payload brut", () => {
    expect(
      timelineEventContext(event({ payload: { resource_path: "godot/scenes/niveau.tscn", noise: 42 } })),
    ).toBe("godot/scenes/niveau.tscn");
    expect(timelineEventContext(event({ payload: { title: "Choisir le moteur" } }))).toBe("Choisir le moteur");
    expect(timelineEventContext(event({ payload: { count: 3 } }))).toBe("");
    expect(timelineEventContext(event({ payload: {} }))).toBe("");
  });
});

describe("timelineEventActor", () => {
  it("nomme l'acteur et la machine en identifiants courts", () => {
    expect(timelineEventActor(event({}))).toContain("utilisateur 11111111…");
    expect(
      timelineEventActor(
        event({ actor_type: "agent", machine_id: "99999999-0000-1111-2222-333333333333" } as Record<string, unknown>),
      ),
    ).toBe("agent 11111111… · machine 99999999…");
    expect(timelineEventActor(event({ actor_type: "system" } as Record<string, unknown>))).toContain("système");
  });

  it("n'affiche jamais d'UUID complet", () => {
    expect(timelineEventActor(event({}))).not.toContain("11111111-2222-4333-8444-555555555555");
  });
});

describe("timelineHtml nominal", () => {
  const html = timelineHtml({
    timeline: timeline(
      {
        date: "2026-09-12",
        events: [
          event({ event_type: "task.created", payload: { title: "Optimiser les éclairages" }, task_id: "t1" }),
          event({ event_type: "resource.conflict", payload: { resource_path: "scenes/niveau.tscn" } }),
        ],
      },
      { date: "2026-09-11", events: [event({ event_type: "build.failed" })] },
    ),
    limit: TIMELINE_LIMIT_DEFAULT,
  });

  it("groupe par jour du plus récent au plus ancien avec total", () => {
    expect(html).toContain("3 événement(s) affiché(s)");
    expect(html.indexOf("2026-09-12")).toBeLessThan(html.indexOf("2026-09-11"));
    expect(html).toContain("Tâche créée");
    expect(html).toContain("Chevauchement de réservation");
    expect(html).toContain("Build échoué");
  });

  it("montre acteur, moment, contexte utile et lien tâche", () => {
    expect(html).toContain("utilisateur");
    expect(html).toContain("Optimiser les éclairages");
    expect(html).toContain("scenes/niveau.tscn");
    expect(html).toContain('href="#/tasks/t1"');
    expect(html).toContain("<time");
  });

  it("aucune fuite JSON technique : ni payload, ni event_id, ni UUID complet", () => {
    expect(html).not.toContain("payload");
    expect(html).not.toContain("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
    expect(html).not.toContain("11111111-2222-4333-8444-555555555555");
    expect(html).not.toMatch(/[{}]\s*"/);
    expect(html).not.toMatch(/\sstyle\s*=/i);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });

  it("données longues : échappement et habillage, pas de débordement de balise", () => {
    const long = timelineHtml({
      timeline: timeline({
        date: "2026-09-12",
        events: [event({ event_type: "task.created", payload: { title: `<script>alert(1)</script>${"x".repeat(300)}` } })],
      }),
      limit: TIMELINE_LIMIT_DEFAULT,
    });
    expect(long).not.toContain("<script>");
    expect(long).toContain("&lt;script&gt;");
  });
});

describe("timelineHtml limites et états", () => {
  it("vide : message honnête avec réserve sur l'exhaustivité serveur", () => {
    const html = timelineHtml({ timeline: timeline(), limit: TIMELINE_LIMIT_DEFAULT });
    expect(html).toContain("Aucune activité");
    expect(html).toContain("pas encore émis");
  });

  it("ignore les jours sans événements", () => {
    const html = timelineHtml({
      timeline: timeline({ date: "2026-09-12", events: [] }, { date: "2026-09-11", events: [event({ event_type: "task.created" })] }),
      limit: TIMELINE_LIMIT_DEFAULT,
    });
    expect(html).toContain("1 événement(s)");
    expect(html).not.toContain("tl-day-2026-09-12");
  });

  it("plafond intermédiaire : propose d'afficher plus", () => {
    const events = Array.from({ length: TIMELINE_LIMIT_DEFAULT }, () => event({ event_type: "task.updated" }));
    const html = timelineHtml({ timeline: timeline({ date: "2026-09-12", events }), limit: TIMELINE_LIMIT_DEFAULT });
    expect(html).toContain("data-timeline-more");
    expect(html).toContain("Afficher plus");
  });

  it("plafond serveur : message honnête, plus de bouton", () => {
    const events = Array.from({ length: TIMELINE_LIMIT_MAX }, () => event({ event_type: "task.updated" }));
    const html = timelineHtml({ timeline: timeline({ date: "2026-09-12", events }), limit: TIMELINE_LIMIT_MAX });
    expect(html).not.toContain("data-timeline-more");
    expect(html).toContain(`${TIMELINE_LIMIT_MAX} événements`);
  });
});

describe("countTimelineEvents", () => {
  it("totalise les jours", () => {
    expect(
      countTimelineEvents(
        timeline(
          { date: "2026-09-12", events: [event({}), event({})] },
          { date: "2026-09-11", events: [event({})] },
        ),
      ),
    ).toBe(3);
  });
});

describe("activityLoadingHtml", () => {
  it("squelette DS annoncé une fois, barres décoratives masquées", () => {
    const html = activityLoadingHtml();
    expect(html).toContain("ds-skeleton");
    expect(html).toContain('role="status"');
  });
});

describe("workspace.css timeline responsive", () => {
  const css = readFileSync(join(__dirname, "workspace.css"), "utf-8");

  it("pas de débordement : habillage et empilement mobile", () => {
    expect(css).toContain("overflow-wrap");
    expect(css).toMatch(/@media[^{]*max-width:\s*640px/);
    expect(css).toContain(".tl-list");
  });

  it("tableaux hérités scrollables, kanban à colonnes bornées", () => {
    expect(css).toContain("overflow-x: auto");
    expect(css).toContain(".workspace-panel table");
  });
});
