/**
 * UI-6 — dérivation honnête de l'activité agent (DERIVED, jamais canonique).
 *
 * Pur (vitest, node) : seuils, priorité session ouverte, attribution
 * directe uniquement, vocabulaire sans « En ligne ».
 */
import { describe, expect, it } from "vitest";
import {
  AGENT_RECENT_MS,
  aiWorkStatusLabel,
  aiWorkStatusTone,
  deriveAgentActivity,
  filterAgents,
  type Agent,
  type AgentEvidence,
  type AgentTask,
  type AIWorkLog,
  type WorkSession,
} from "./agentsApi";

const A1 = "aaaaaaaa-0000-4111-8111-000000000001";
const A2 = "aaaaaaaa-0000-4111-8111-000000000002";
const M1 = "bbbbbbbb-0000-4111-8111-000000000001";
const T1 = "cccccccc-0000-4111-8111-000000000001";
const P1 = "11111111-2222-4333-8444-555555555555";

const NOW = new Date("2026-09-18T12:00:00Z").getTime();
const iso = (ms: number): string => new Date(ms).toISOString();

const agent = (id: string, extra: Record<string, unknown> = {}): Agent =>
  ({
    id,
    machine_id: M1,
    display_name: id === A1 ? "Claude Atlas" : "Qwen Relais",
    agent_kind: "code",
    agent_profile: null,
    harness: null,
    provider: "anthropic",
    model: "claude-test",
    created_at: iso(NOW - 10 * 86_400_000),
    updated_at: iso(NOW - 86_400_000),
    version: 1,
    ...extra,
  }) as Agent;

const session = (id: string, agentId: string | null, startedAgoMs: number, open: boolean): WorkSession =>
  ({
    id,
    task_id: T1,
    machine_id: M1,
    agent_id: agentId,
    started_at: iso(NOW - startedAgoMs),
    ended_at: open ? null : iso(NOW - startedAgoMs + 60_000),
  }) as WorkSession;

const work = (id: string, agentId: string, startedAgoMs: number, status = "completed"): AIWorkLog =>
  ({
    id,
    task_id: T1,
    project_id: P1,
    agent_id: agentId,
    machine_id: M1,
    summary: "Corriger l'authentification",
    status,
    changed_files: [],
    tests_run: [],
    started_at: iso(NOW - startedAgoMs),
    ended_at: iso(NOW - startedAgoMs + 120_000),
    agent_profile: null,
    harness: null,
    provider: null,
    model: null,
  }) as AIWorkLog;

const claimedTask = (agentId: string | null): AgentTask =>
  ({
    id: T1,
    project_id: P1,
    readable_id: "T-9",
    title: "Corriger l'authentification",
    description: null,
    status: "in_progress",
    claimed_by_machine_id: M1,
    claimed_by_agent_id: agentId,
    created_at: iso(NOW - 86_400_000),
    updated_at: iso(NOW - 5 * 60_000),
    version: 3,
  }) as AgentTask;

const blank: AgentEvidence = { sessions: [], aiWork: [], tasks: [], events: [], secondaryOk: true, now: NOW };

describe("deriveAgentActivity (DERIVED, jamais canonique)", () => {
  it("priorise la session ouverte portée par l'agent", () => {
    const activity = deriveAgentActivity(A1, {
      ...blank,
      sessions: [session("s1", A1, 10 * 60_000, true)],
      aiWork: [work("w1", A1, 5 * 60_000)],
    });
    expect(activity.signal).toBe("open-session");
    expect(activity.openSession?.id).toBe("s1");
    expect(activity.sessionCount).toBe(1);
    expect(activity.workCount).toBe(1);
  });

  it("signale récent sous le seuil, passé au-delà", () => {
    const recent = deriveAgentActivity(A1, { ...blank, aiWork: [work("w1", A1, AGENT_RECENT_MS - 60_000)] });
    expect(recent.signal).toBe("recent");
    expect(recent.lastActivitySource).toBe("ai-work");
    const past = deriveAgentActivity(A1, { ...blank, aiWork: [work("w1", A1, AGENT_RECENT_MS + 300_000)] });
    expect(past.signal).toBe("past");
  });

  it("retient la plus récente de toutes les sources directes", () => {
    const activity = deriveAgentActivity(A1, {
      ...blank,
      sessions: [session("s1", A1, 90 * 60_000, false)],
      aiWork: [work("w1", A1, 60 * 60_000)],
      tasks: [claimedTask(A1)],
      events: [
        {
          event_id: "e1",
          event_type: "task.updated",
          project_id: P1,
          task_id: T1,
          machine_id: M1,
          actor_type: "agent",
          actor_id: A1,
          client_timestamp: iso(NOW - 80 * 60_000),
          server_timestamp: iso(NOW - 2 * 60_000),
          payload: {},
          schema_version: 1,
        } as never,
      ],
    });
    expect(activity.signal).toBe("recent");
    expect(activity.lastActivitySource).toBe("event");
  });

  it("n'attribue jamais l'activité machine ou d'un autre agent", () => {
    const activity = deriveAgentActivity(A1, {
      ...blank,
      sessions: [session("s1", null, 60_000, true), session("s2", A2, 60_000, true)],
      aiWork: [work("w1", A2, 60_000)],
      tasks: [claimedTask(A2)],
      events: [
        {
          event_id: "e1",
          event_type: "task.updated",
          project_id: P1,
          task_id: T1,
          machine_id: M1,
          actor_type: "user",
          actor_id: "u1",
          client_timestamp: iso(NOW - 60_000),
          server_timestamp: iso(NOW - 60_000),
          payload: {},
          schema_version: 1,
        } as never,
      ],
    });
    expect(activity.signal).toBe("none");
    expect(activity.openSession).toBeNull();
    expect(activity.lastActivityAt).toBeNull();
  });

  it("dégrade en inconnu quand une source secondaire a échoué", () => {
    const activity = deriveAgentActivity(A1, { ...blank, secondaryOk: false });
    expect(activity.signal).toBe("unknown");
    expect(activity.lastActivityAt).toBeNull();
  });

  it("garde le signal fort même si une source secondaire a échoué", () => {
    const activity = deriveAgentActivity(A1, {
      ...blank,
      secondaryOk: false,
      sessions: [session("s1", A1, 10 * 60_000, true)],
    });
    expect(activity.signal).toBe("open-session");
  });
});

describe("filterAgents (recherche locale, champs humains chargés)", () => {
  const agents = [agent(A1), agent(A2, { display_name: "Kimi Scribe", agent_kind: "docs", provider: null, model: null })];

  it("sans requête retourne tout, dans l'ordre du serveur", () => {
    expect(filterAgents(agents, "")).toEqual(agents);
    expect(filterAgents(agents, "   ")).toEqual(agents);
  });

  it("cherche nom, nature et technique déclarée, insensible à la casse", () => {
    expect(filterAgents(agents, "atlas").map((a) => a.id)).toEqual([A1]);
    expect(filterAgents(agents, "DOCS").map((a) => a.id)).toEqual([A2]);
    expect(filterAgents(agents, "anthropic").map((a) => a.id)).toEqual([A1]);
    expect(filterAgents(agents, "claude-test").map((a) => a.id)).toEqual([A1]);
  });

  it("ne fabrique rien : sans correspondance, vide", () => {
    expect(filterAgents(agents, "zzz")).toEqual([]);
  });
});

describe("aiWorkStatusLabel (clés backend inchangées)", () => {
  it("traduit les six statuts connus, repli brut sinon", () => {
    expect(aiWorkStatusLabel("started")).toBe("Commencé");
    expect(aiWorkStatusLabel("review_requested")).toBe("En relecture");
    expect(aiWorkStatusLabel("approved")).toBe("Approuvé");
    expect(aiWorkStatusLabel("nope")).toBe("nope");
  });

  it("associe un ton non ambigu (couleur jamais seul signal, libellé joint)", () => {
    expect(aiWorkStatusTone("completed")).toBe("success");
    expect(aiWorkStatusTone("started")).toBe("info");
    expect(aiWorkStatusTone("failed")).toBe("warning");
    expect(aiWorkStatusTone("nope")).toBe("neutral");
  });
});
