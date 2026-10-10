// @vitest-environment happy-dom
/**
 * Mission Control : verdicts connus/inconnus, données manquantes, résultat,
 * compteurs de fenêtre, page suivante, 403, perte du direct bornée,
 * résumé de la vue d'ensemble limité à 3 runs d'attention.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import type { MissionRun, ProjectMission } from "../missionApi";
import {
  missionRunHtml,
  protocolLabel,
  reasonLabel,
  renderMissionInto,
  renderMissionSummaryInto,
  verdictLabel,
  verdictTone,
  type LiveState,
} from "./mission";

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

let seq = 0;
function run(overrides: Partial<MissionRun> = {}): MissionRun {
  seq += 1;
  const n = String(seq).padStart(12, "0");
  return {
    run_id: `aaaaaaaa-0000-4000-8000-${n}`,
    source: "launch",
    task_id: `bbbbbbbb-0000-4000-8000-${n}`,
    task_title: `Tâche ${seq}`,
    machine_id: `cccccccc-0000-4000-8000-${n}`,
    machine_status: "online",
    launch: {
      id: `dddddddd-0000-4000-8000-${n}`,
      status: "running",
      reason_code: "accepted",
      harness_id: "claude-code",
      created_at: "2026-10-10T10:00:00Z",
    },
    session: null,
    handoff: null,
    protocol_state: "open",
    verdict: "running",
    reasons: ["process_running"],
    active_claims: 0,
    data_gaps: [],
    updated_at: "2026-10-10T10:05:00Z",
    ...overrides,
  } as MissionRun;
}

function mission(runs: MissionRun[], overrides: Partial<ProjectMission> = {}): ProjectMission {
  return {
    project_id: "eeeeeeee-0000-4000-8000-000000000001",
    generated_at: "2026-10-10T10:10:00Z",
    window_hours: 168,
    runs,
    counts: { by_verdict: { running: runs.length }, total: runs.length },
    next_cursor: null,
    truncated: false,
    ...overrides,
  };
}

type Reply = { data?: unknown; error?: unknown; status: number };

function fakeClient(replies: Reply[] | (() => Reply)): { client: StudioClient; get: ReturnType<typeof vi.fn> } {
  const get = vi.fn(async () => {
    const reply = typeof replies === "function" ? replies() : (replies.shift() ?? { status: 500 });
    return { data: reply.data, error: reply.error, response: new Response(null, { status: reply.status }) };
  });
  return { client: { GET: get } as unknown as StudioClient, get };
}

function mount(): HTMLElement {
  const root = document.createElement("div");
  document.body.appendChild(root);
  return root;
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("libellés tolérants", () => {
  it("verdict, raison et protocole connus", () => {
    expect(verdictLabel("waiting_human")).toBe("Attend une personne");
    expect(verdictTone("failed")).toBe("danger");
    expect(reasonLabel("handed_off")).toBe("Résultat transmis");
    expect(protocolLabel("missing")).toBe("Aucune session");
  });

  it("valeurs inconnues : « inconnu » + code brut, ton neutre", () => {
    expect(verdictLabel("exploded")).toBe("inconnu (exploded)");
    expect(verdictTone("exploded")).toBe("neutral");
    expect(reasonLabel("cosmic_ray")).toBe("inconnu (cosmic_ray)");
    expect(protocolLabel("toString")).toBe("inconnu (toString)");
  });

  it("un run au verdict inconnu reste rendu avec le code brut", () => {
    const html = missionRunHtml(run({ verdict: "exploded" as MissionRun["verdict"], reasons: ["cosmic_ray" as MissionRun["reasons"][number]] }));
    expect(html).toContain('data-verdict="exploded"');
    expect(html).toContain("inconnu (exploded)");
    expect(html).toContain("inconnu (cosmic_ray)");
  });
});

describe("missionRunHtml", () => {
  it("données manquantes : mention explicite, rien de fabriqué", () => {
    const root = mount();
    root.innerHTML = missionRunHtml(
      run({ task_title: null, data_gaps: ["task_not_found", "machine_unknown", "session_not_found"], session: null }),
    );
    const gaps = [...root.querySelectorAll("[data-mission-gap]")].map((n) => n.getAttribute("data-mission-gap"));
    expect(gaps).toEqual(expect.arrayContaining(["task_not_found", "machine_unknown", "session_not_found"]));
    expect(root.textContent).toContain("Donnée manquante");
    expect(root.textContent).not.toContain("Tâche sans titre");
  });

  it("résultat présent : résumé du handoff ; absent : « Aucun résultat transmis »", () => {
    const root = mount();
    root.innerHTML = missionRunHtml(
      run({
        verdict: "done",
        protocol_state: "handed_off",
        reasons: ["handed_off"],
        handoff: { ai_work_id: "ffffffff-0000-4000-8000-000000000001", status: "completed", summary: "Vue livrée", completed_at: null },
      }),
    );
    expect(root.querySelector("[data-mission-result]")?.textContent).toContain("Vue livrée");
    root.innerHTML = missionRunHtml(run());
    expect(root.querySelector("[data-mission-result]")?.textContent).toContain("Aucun résultat transmis");
  });

  it("aucun UUID visible hors des détails techniques repliés", () => {
    const root = mount();
    root.innerHTML = missionRunHtml(run({ session: { id: "99999999-0000-4000-8000-000000000001", status: "active", started_at: "2026-10-10T10:00:00Z" } }));
    root.querySelectorAll(".ds-tech").forEach((n) => n.remove());
    expect(root.textContent ?? "").not.toMatch(UUID);
    expect(root.querySelector("a")?.getAttribute("href")).toMatch(/^#\/tasks\//);
  });
});

describe("renderMissionInto", () => {
  it("compteurs issus de `counts` (toute la fenêtre), pas de la page", async () => {
    const root = mount();
    const { client } = fakeClient([
      { status: 200, data: mission([run()], { counts: { by_verdict: { running: 1, failed: 41 }, total: 42 } }) },
    ]);
    await renderMissionInto(root, { client, projectId: "p1", authed: true });
    const counts = root.querySelector("[data-mission-counts]");
    expect(counts?.textContent).toContain("42");
    expect(counts?.querySelector('[data-count-verdict="failed"]')?.textContent).toContain("41");
    expect(root.querySelector("[data-mission]")).not.toBeNull();
    expect(root.querySelectorAll("[data-mission-run]")).toHaveLength(1);
  });

  it("« Charger plus » ajoute la page suivante via next_cursor", async () => {
    const root = mount();
    const first = run();
    const second = run();
    const { client, get } = fakeClient([
      { status: 200, data: mission([first], { next_cursor: "c2" }) },
      { status: 200, data: mission([second]) },
    ]);
    await renderMissionInto(root, { client, projectId: "p1", authed: true });
    root.querySelector<HTMLButtonElement>("[data-mission-more]")?.click();
    await vi.waitFor(() => expect(root.querySelectorAll("[data-mission-run]")).toHaveLength(2));
    expect(get.mock.calls[1]?.[1]).toMatchObject({ params: { query: { cursor: "c2" } } });
    expect(root.querySelector("[data-mission-more]")).toBeNull();
  });

  it("403 → état accès refusé, sans nouvel essai", async () => {
    const root = mount();
    const { client, get } = fakeClient([{ status: 403, error: { detail: { error_code: "forbidden", resource: "project" } } }]);
    await renderMissionInto(root, { client, projectId: "p1", authed: true, live: () => "lost", pollMs: 10, maxPolls: 3 });
    expect(root.querySelector("[data-mission-denied]")).not.toBeNull();
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("direct perdu : bandeau, rafraîchissement borné puis arrêt annoncé", async () => {
    vi.useFakeTimers();
    const root = mount();
    const { client, get } = fakeClient(() => ({ status: 200, data: mission([run()]) }));
    const live = (): LiveState => "lost";
    await renderMissionInto(root, { client, projectId: "p1", authed: true, live, pollMs: 1000, maxPolls: 3 });
    expect(root.querySelector('[data-mission-live="lost"]')).not.toBeNull();
    expect(root.querySelector("[data-mission-refresh]")).not.toBeNull();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(get).toHaveBeenCalledTimes(4);
    expect(root.querySelector("[data-mission-poll-stopped]")).not.toBeNull();
  });

  it("le rafraîchissement s'arrête dès que le direct revient ou que la vue est détachée", async () => {
    vi.useFakeTimers();
    let state: LiveState = "lost";
    const root = mount();
    const { client, get } = fakeClient(() => ({ status: 200, data: mission([]) }));
    await renderMissionInto(root, { client, projectId: "p1", authed: true, live: () => state, pollMs: 1000, maxPolls: 10 });
    await vi.advanceTimersByTimeAsync(1000);
    expect(get).toHaveBeenCalledTimes(2);
    state = "live";
    await vi.advanceTimersByTimeAsync(5000);
    expect(get).toHaveBeenCalledTimes(2);

    state = "lost";
    const other = mount();
    await renderMissionInto(other, { client, projectId: "p1", authed: true, live: () => state, pollMs: 1000, maxPolls: 10 });
    other.remove();
    await vi.advanceTimersByTimeAsync(5000);
    expect(get).toHaveBeenCalledTimes(3);
  });
});

describe("renderMissionSummaryInto", () => {
  it("au plus 3 runs d'attention, lien vers l'onglet", async () => {
    const root = mount();
    const runs = [
      run({ verdict: "running" }),
      run({ verdict: "failed", reasons: ["launch_failed"] }),
      run({ verdict: "stale", reasons: ["machine_offline"] }),
      run({ verdict: "done", reasons: ["handed_off"] }),
      run({ verdict: "needs_attention", reasons: ["session_ended_without_handoff"] }),
      run({ verdict: "waiting_human", reasons: ["review_requested"] }),
    ];
    const { client } = fakeClient([{ status: 200, data: mission(runs) }]);
    await renderMissionSummaryInto(root, { client, projectId: "p1", authed: true });
    const shown = [...root.querySelectorAll("[data-mission-run]")].map((n) => n.getAttribute("data-verdict"));
    expect(shown).toEqual(["waiting_human", "needs_attention", "stale"]);
    expect(root.querySelector("[data-mission-summary] a[href='#/projects/p1/mission']")).not.toBeNull();
    expect(root.querySelector("[data-mission-counts]")).not.toBeNull();
  });
});
