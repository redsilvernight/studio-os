/**
 * UI-4 — Onglet Activité : timeline lisible depuis GET /timeline, jamais un
 * dump JSON. DOM-free : chaînes pures + lecture statique de workspace.css.
 */
// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  activityLoadingHtml,
  collapseAiWork,
  countTimelineEvents,
  TIMELINE_LIMIT_DEFAULT,
  TIMELINE_LIMIT_MAX,
  timelineEventActor,
  timelineEventContext,
  timelineEventLabel,
  timelineHtml,
  newestTimelineFirst,
  renderActivityInto,
  utcDayWindow,
} from "./activity";
import type { StudioClient } from "../api";

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

  it("signaux coordination.* : libellé d'intention, jamais le type brut", () => {
    expect(timelineEventLabel("coordination.question")).toBe("Question");
    expect(timelineEventLabel("coordination.blocked_by")).toBe("Blocage");
    expect(timelineEventLabel("coordination.handoff")).toBe("Passage de relais");
    expect(timelineEventLabel("coordination.heads_up")).toBe("Information");
    for (const type of ["coordination.question", "coordination.blocked_by", "coordination.handoff", "coordination.heads_up"]) {
      expect(timelineEventLabel(type)).not.toContain("coordination");
    }
    expect(timelineEventLabel("coordination.future_intent")).toBe("Événement");
  });
});

describe("coordination.* dans la timeline", () => {
  const html = timelineHtml({
    timeline: timeline({
      date: "2026-09-12",
      events: [
        event({
          event_type: "coordination.question",
          task_id: "t1",
          payload: { text: "Le chemin de sortie est-il validé ?" },
        }),
      ],
    }),
    limit: TIMELINE_LIMIT_DEFAULT,
  });

  it("la timeline n'est pas filtrée : un signal s'y affiche comme les autres", () => {
    expect(html).toContain("Question");
    expect(html).toContain("1 événement(s)");
    expect(html).toContain('href="#/tasks/t1"');
    expect(html).not.toContain("coordination");
  });

  it("intention future : libellé générique, jamais le type brut", () => {
    const future = timelineHtml({
      timeline: timeline({
        date: "2026-09-12",
        events: [event({ event_type: "coordination.future_intent" })],
      }),
      limit: TIMELINE_LIMIT_DEFAULT,
    });
    expect(future).toContain("Événement");
    expect(future).not.toContain("future_intent");
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
  it("nomme l'acteur et la machine sans identifiant", () => {
    expect(timelineEventActor(event({}))).toContain("utilisateur Un membre de l'équipe");
    expect(
      timelineEventActor(
        event({ actor_type: "agent", machine_id: "99999999-0000-1111-2222-333333333333" } as Record<string, unknown>),
      ),
    ).toBe("agent Agent sans nom · machine Poste sans nom");
    expect(timelineEventActor(event({ actor_type: "system" } as Record<string, unknown>))).toContain("système");
  });

  it("n'affiche jamais d'UUID complet", () => {
    expect(timelineEventActor(event({}))).not.toContain("11111111-2222-4333-8444-555555555555");
  });
});

describe("timelineHtml nominal", () => {
  const olderTimeline = timeline(
    { date: "2026-09-12", events: [event({ event_type: "task.created" })] },
    { date: "2026-09-11", events: [event({ event_type: "build.failed" })] },
  );
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

  it("calendrier : focus sur le jour le plus récent, les autres jours restent à un clic", () => {
    expect(html).toContain("2 événement(s)");
    expect(html).toContain('data-cal-day="2026-09-12"');
    expect(html).toContain('data-cal-day="2026-09-11"');
    expect(html).toContain("Tâche créée");
    expect(html).toContain("Chevauchement de réservation");
    expect(html).not.toContain("Build échoué");
    const older = timelineHtml({ timeline: olderTimeline, limit: TIMELINE_LIMIT_DEFAULT, view: { month: "2026-09", selected: "2026-09-11" } });
    expect(older).toContain("Build échoué");
  });

  it("montre acteur, moment, contexte utile et lien tâche", () => {
    expect(html).toContain("utilisateur");
    expect(html).toContain("Optimiser les éclairages");
    expect(html).toContain("scenes/niveau.tscn");
    expect(html).toContain('href="#/tasks/t1"');
    expect(html).toContain("<time");
  });

  it("aucune fuite JSON technique : ni payload, ni event_id, UUID complet seulement en infobulle", () => {
    const visible = html.replace(/\stitle="[^"]*"/g, "");
    expect(html).not.toContain("payload");
    expect(html).not.toContain("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
    expect(visible).not.toContain("11111111-2222-4333-8444-555555555555");
    expect(html).toContain('title="11111111-2222-4333-8444-555555555555"');
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
    expect(html).toContain("suite de cette journée");
  });

  it("une page pleine continue au-delà de 500 événements", () => {
    const events = Array.from({ length: TIMELINE_LIMIT_MAX }, () => event({ event_type: "task.updated" }));
    const html = timelineHtml({ timeline: timeline({ date: "2026-09-12", events }), limit: TIMELINE_LIMIT_MAX });
    expect(html).toContain("data-timeline-more");
    expect(html).not.toContain("limite serveur");
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

describe("historique exhaustif et pagination par journée UTC", () => {
  it("trie les jours et événements du plus récent au plus ancien sans muter la source", () => {
    const source = timeline(
      { date: "2026-09-11", events: [event({ event_id: "old", server_timestamp: "2026-09-11T23:59:00Z" })] },
      { date: "2026-09-12", events: [
        event({ event_id: "a", server_timestamp: "2026-09-12T12:00:00+02:00" }),
        event({ event_id: "b", server_timestamp: "2026-09-12T11:00:00Z" }),
      ] },
    );
    const sorted = newestTimelineFirst(source);
    expect(sorted.days.map((day) => day.date)).toEqual(["2026-09-12", "2026-09-11"]);
    expect(sorted.days[0]?.events.map((item) => item.event_id)).toEqual(["b", "a"]);
    expect((source as { days: { date: string }[] }).days[0]?.date).toBe("2026-09-11");
    expect(utcDayWindow("2026-10-25")).toEqual({ since: "2026-10-25T00:00:00.000Z", until: "2026-10-26T00:00:00.000Z" });
  });

  it("charge 501 événements à la demande puis un ancien mois indépendant du lot récent", async () => {
    const root = document.createElement("div");
    const GET = vi.fn(async (path: string, options: { params: { query: Record<string, unknown> } }) => {
      const query = options.params.query;
      expect(query["project_id"]).toBe("p1");
      if (path.endsWith("/dates")) return { response: new Response(), data: ["2026-10-20", "2026-07-09"] };
      if (path.endsWith("/sessions")) return { response: new Response(), data: [] };
      const selected = String(query["since"]).slice(0, 10);
      const offset = Number(query["offset"]);
      const total = selected === "2026-10-20" ? 501 : 1;
      const events = Array.from({ length: Math.min(200, total - offset) }, (_, index) => event({
        event_id: `${selected}-${offset + index}`,
        event_type: "task.updated",
        payload: { title: `${selected}-événement-${offset + index}` },
        server_timestamp: `${selected}T12:00:00Z`,
      }));
      return { response: new Response(), data: timeline({ date: selected, events }) };
    });
    await renderActivityInto(root, { client: { GET } as unknown as StudioClient, projectId: "p1", authed: true });
    expect(root.querySelectorAll(".tl-item")).toHaveLength(200);
    root.querySelector<HTMLButtonElement>("[data-timeline-more]")!.click();
    await vi.waitFor(() => expect(root.querySelectorAll(".tl-item")).toHaveLength(400));
    root.querySelector<HTMLButtonElement>("[data-timeline-more]")!.click();
    await vi.waitFor(() => expect(root.querySelectorAll(".tl-item")).toHaveLength(501));
    expect(root.querySelector("[data-timeline-more]")).toBeNull();
    for (let i = 0; i < 3; i++) root.querySelector<HTMLButtonElement>('[data-cal-month="-1"]')!.click();
    root.querySelector<HTMLButtonElement>('[data-cal-day="2026-07-09"]')!.click();
    await vi.waitFor(() => expect(root.textContent).toContain("2026-07-09-événement-0"));
    expect(root.querySelectorAll(".tl-item")).toHaveLength(1);
    expect(GET.mock.calls.some(([path, options]) => path.endsWith("/timeline") && options.params.query["offset"] === 400)).toBe(true);
    expect(GET.mock.calls.find(([path, options]) => path.endsWith("/timeline") && String(options.params.query["since"]).startsWith("2026-07"))?.[1].params.query["until"]).toBe("2026-07-10T00:00:00.000Z");
    expect(root.textContent).toContain("Dates et heures en UTC");
  });

  it("une session sans événements reste consultable au calendrier, et une panne ne devient pas un jour vide", async () => {
    const root = document.createElement("div");
    const GET = vi.fn(async (path: string) => ({
      response: new Response(),
      data: path.endsWith("/dates") ? ["2026-01-02"] : path.endsWith("/sessions") ? [{
        id: "s1", task_id: "t1", machine_id: "m1", agent_id: null,
        started_at: "2026-01-01T23:59:00Z", ended_at: "2026-01-02T00:01:00Z", status: "ended",
      }] : timeline(),
    }));
    await renderActivityInto(root, { client: { GET } as unknown as StudioClient, projectId: "p1", authed: true });
    expect(root.textContent).toContain("Session de travail terminée");
    expect(root.textContent).not.toContain("Aucune activité");
    expect(root.querySelector('a[href="#/tasks/t1"]')).not.toBeNull();
    GET.mockRejectedValueOnce(new Error("réseau indisponible"));
    root.querySelector<HTMLButtonElement>("[data-cal-latest]")!.click();
    await vi.waitFor(() => expect(root.querySelector('[role="alert"]')?.textContent).toContain("réseau indisponible"));
    expect(root.textContent).not.toContain("Aucune activité");
    expect(root.querySelector("[data-timeline-retry]")).not.toBeNull();
  });
});

describe("collapseAiWork", () => {
  const WORK = "50000000-0000-4111-8111-000000000004";
  const workEvent = (type: string, at: string, aiWorkId: unknown = WORK) =>
    event({ event_id: `${at}-${type}`, event_type: type, server_timestamp: at, payload: { ai_work_id: aiWorkId } });

  it("started + completed : une seule entrée, la plus récente conservée", () => {
    const collapsed = collapseAiWork(
      timeline({
        date: "2026-09-12",
        events: [
          workEvent("ai_work.started", "2026-09-12T09:00:00Z"),
          workEvent("ai_work.completed", "2026-09-12T10:30:00Z"),
        ],
      }),
    );
    expect(collapsed.days).toHaveLength(1);
    expect(collapsed.days[0]?.events).toHaveLength(1);
    expect(collapsed.days[0]?.events[0]?.event_type).toBe("ai_work.completed");
    expect(countTimelineEvents(collapsed)).toBe(1);
  });

  it("affiche le libellé du plus récent, jamais « démarré »", () => {
    const html = timelineHtml({
      timeline: timeline({
        date: "2026-09-12",
        events: [
          workEvent("ai_work.started", "2026-09-12T09:00:00Z"),
          workEvent("ai_work.completed", "2026-09-12T10:30:00Z"),
        ],
      }),
      limit: TIMELINE_LIMIT_DEFAULT,
    });
    expect(html).toContain("Travail IA terminé");
    expect(html).not.toContain("Travail IA démarré");
    expect(html).toContain("1 événement(s)");
    expect(html.match(/class="tl-item"/g)).toHaveLength(1);
  });

  it("paire répartie sur deux jours : l'entrée reste dans le jour du plus récent", () => {
    const collapsed = collapseAiWork(
      timeline(
        { date: "2026-09-12", events: [workEvent("ai_work.started", "2026-09-11T23:50:00Z")] },
        { date: "2026-09-11", events: [workEvent("ai_work.completed", "2026-09-12T00:10:00Z")] },
      ),
    );
    expect(collapsed.days.map((d) => d.date)).toEqual(["2026-09-11"]);
    expect(collapsed.days[0]?.events.map((e) => e.event_type)).toEqual(["ai_work.completed"]);
  });

  it("un jour vidé par la déduplication disparaît, le reste garde son ordre", () => {
    const collapsed = collapseAiWork(
      timeline(
        {
          date: "2026-09-12",
          events: [
            event({ event_type: "task.created" }),
            workEvent("ai_work.completed", "2026-09-12T10:00:00Z"),
            event({ event_type: "task.completed" }),
          ],
        },
        { date: "2026-09-11", events: [workEvent("ai_work.started", "2026-09-11T23:50:00Z")] },
      ),
    );
    expect(collapsed.days.map((d) => d.date)).toEqual(["2026-09-12"]);
    expect(collapsed.days[0]?.events.map((e) => e.event_type)).toEqual([
      "task.created",
      "ai_work.completed",
      "task.completed",
    ]);
  });

  it("travaux IA distincts, horodatages égaux et identifiants absents : rien n'est écrasé", () => {
    const collapsed = collapseAiWork(
      timeline({
        date: "2026-09-12",
        events: [
          workEvent("ai_work.started", "2026-09-12T09:00:00Z", "work-a"),
          workEvent("ai_work.completed", "2026-09-12T09:00:00Z", "work-a"),
          workEvent("ai_work.started", "2026-09-12T09:00:00Z", "work-b"),
          workEvent("ai_work.started", "2026-09-12T11:00:00Z", undefined),
          workEvent("ai_work.started", "2026-09-12T12:00:00Z", "  "),
        ],
      }),
    );
    // Égalité d'horodatage : la première occurrence l'emporte (stabilité).
    expect(collapsed.days[0]?.events.map((e) => e.event_type)).toEqual([
      "ai_work.started",
      "ai_work.started",
      "ai_work.started",
      "ai_work.started",
    ]);
  });

  it("événements non ai_work intacts : ni regroupés ni déplacés, même identifiant dans le payload", () => {
    const source = timeline({
      date: "2026-09-12",
      events: [
        event({ event_id: "e1", event_type: "task.created", server_timestamp: "2026-09-12T09:00:00Z" }),
        event({
          event_id: "e2",
          event_type: "session.started",
          server_timestamp: "2026-09-12T09:00:00Z",
          payload: { ai_work_id: WORK },
        }),
        event({ event_id: "e3", event_type: "task.completed", server_timestamp: "2026-09-12T09:00:00Z" }),
      ],
    });
    expect(collapseAiWork(source).days[0]?.events.map((e) => e.event_id)).toEqual(["e1", "e2", "e3"]);
  });

  it("n'est pas mutante et reste idempotente", () => {
    const source = timeline(
      {
        date: "2026-09-12",
        events: [
          workEvent("ai_work.started", "2026-09-12T09:00:00Z"),
          workEvent("ai_work.completed", "2026-09-12T10:00:00Z"),
        ],
      },
      { date: "2026-09-11", events: [event({ event_type: "task.created" })] },
    );
    const before = JSON.parse(JSON.stringify(source));
    const once = collapseAiWork(source);
    expect(JSON.parse(JSON.stringify(source))).toEqual(before);
    expect(once).not.toBe(source);
    expect(collapseAiWork(once)).toEqual(once);
  });

  it("reste neutre sur une timeline sans ai_work", () => {
    const source = timeline({ date: "2026-09-12", events: [event({ event_type: "task.created" })] });
    expect(collapseAiWork(source)).toEqual(source);
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
