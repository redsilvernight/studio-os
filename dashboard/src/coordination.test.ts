import { describe, expect, it } from "vitest";
import { buildThreads, latestHandoff, openItems, parseCoordinationEvents } from "./coordination";

function ev(id: string, intent: string, at: string, extra: Record<string, unknown> = {}) {
  return {
    event_id: id,
    event_type: `coordination.${intent}`,
    task_id: "t1",
    actor_type: "agent",
    actor_id: "a1",
    server_timestamp: at,
    payload: { intent, text: `texte ${id}`, from_session_id: "s1", ...extra },
  };
}

describe("parseCoordinationEvents", () => {
  it("garde seulement les coordination.* valides, triés par date", () => {
    const items = parseCoordinationEvents([
      ev("b", "question", "2026-10-11T10:02:00Z"),
      { event_id: "x", event_type: "task.updated", server_timestamp: "2026-10-11T10:00:00Z", payload: {} },
      ev("a", "heads_up", "2026-10-11T10:01:00Z"),
      { ...ev("bad", "chat", "2026-10-11T10:03:00Z") },
      { ...ev("notext", "question", "2026-10-11T10:04:00Z"), payload: {} },
    ]);
    expect(items.map((i) => i.eventId)).toEqual(["a", "b"]);
    expect(items[1]).toMatchObject({ intent: "question", text: "texte b", taskId: "t1", fromSessionId: "s1" });
  });

  it("tolère une entrée qui n'est pas un tableau", () => {
    expect(parseCoordinationEvents(null)).toEqual([]);
  });
});

describe("fils, éléments ouverts et passage de relais", () => {
  const items = parseCoordinationEvents([
    ev("q1", "question", "2026-10-11T10:00:00Z"),
    ev("r1", "heads_up", "2026-10-11T10:05:00Z", { in_reply_to: "q1" }),
    ev("r2", "heads_up", "2026-10-11T10:06:00Z", { in_reply_to: "r1" }),
    ev("q2", "blocked_by", "2026-10-11T10:07:00Z"),
    ev("h1", "handoff", "2026-10-11T10:08:00Z"),
    ev("h2", "handoff", "2026-10-11T10:09:00Z"),
  ]);

  it("rattache les réponses en chaîne au signal racine", () => {
    const threads = buildThreads(items);
    expect(threads.map((t) => t.root.eventId)).toEqual(["q1", "q2", "h1", "h2"]);
    expect(threads[0]?.replies.map((r) => r.eventId)).toEqual(["r1", "r2"]);
  });

  it("une question répondue n'est plus à traiter ; un blocage sans réponse l'est", () => {
    expect(openItems(items).map((i) => i.eventId)).toEqual(["q2"]);
  });

  it("retient le passage de relais le plus récent", () => {
    expect(latestHandoff(items)?.eventId).toBe("h2");
    expect(latestHandoff([])).toBeNull();
  });
});
