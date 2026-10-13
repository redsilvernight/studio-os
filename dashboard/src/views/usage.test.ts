// @vitest-environment happy-dom
/**
 * Consommation (P03-usage-ui) : les valeurs affichées sont exactement celles
 * du serveur, un coût partiel, inconnu ou en devises mélangées n'est jamais
 * présenté comme un total exact, et aucun UUID n'est visible hors détails
 * techniques repliés.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import type { UsageAggregate, UsageSummary } from "../usageApi";
import {
  costValueHtml,
  formatSeconds,
  renderProjectUsageInto,
  taskUsageSectionHtml,
  usageSince,
  usageSummaryHtml,
} from "./usage";

const PROJECT = "aaaaaaaa-1111-4222-8333-444444444444";
const TASK = "bbbbbbbb-1111-4222-8333-444444444444";
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

function coverage(measured: number, estimated = 0, unknown = 0) {
  return { measured_entries: measured, estimated_entries: estimated, unknown_entries: unknown };
}

function aggregate(overrides: Partial<UsageAggregate> = {}): UsageAggregate {
  const none = { status: "unknown" as const, known_sum: null, ...coverage(0, 0, 2) };
  return {
    key: {},
    entries: 2,
    first_period_start: "2026-10-11T10:00:00Z",
    last_period_end: "2026-10-11T10:00:05Z",
    tokens_in: { status: "partial", known_sum: 25, ...coverage(1, 0, 1) },
    tokens_out: none,
    tokens_cached: none,
    total_tokens: { status: "partial", known_sum: 330, ...coverage(1, 0, 1) },
    cost: {
      status: "partial",
      known_sum: "0.125",
      currency: "USD",
      by_currency: [{ currency: "USD", known_sum: "0.125", entries: 1 }],
      ...coverage(1, 0, 1),
    },
    duration: { status: "exact", known_sum: "17", ...coverage(2) },
    sources: [
      { collector: "studio-claude-code", entries: 1 },
      { collector: "studio-runner", entries: 1 },
    ],
    ...overrides,
  };
}

function summary(overrides: Partial<UsageSummary> = {}): UsageSummary {
  const total = aggregate();
  return {
    project_id: PROJECT,
    task_id: null,
    group_by: "task",
    since: null,
    until: null,
    generated_at: "2026-10-13T12:00:00Z",
    total,
    groups: [{ ...total, key: { task_id: TASK, task_title: "Afficher le coût" } }],
    truncated: false,
    ...overrides,
  };
}

function visibleText(html: string): string {
  const root = document.createElement("div");
  root.innerHTML = html;
  root.querySelectorAll("details").forEach((node) => node.remove());
  return root.textContent ?? "";
}

function metric(html: string, kind: string): HTMLElement[] {
  const root = document.createElement("div");
  root.innerHTML = html;
  return [...root.querySelectorAll<HTMLElement>(`[data-usage-metric="${kind}"]`)];
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("usageSummaryHtml", () => {
  it("affiche exactement les valeurs du serveur, sans recalcul", () => {
    const html = usageSummaryHtml(summary());
    const [totalCost] = metric(html, "cost");
    const [totalDuration] = metric(html, "duration");
    const [totalTokens] = metric(html, "tokens");
    expect(totalCost?.dataset.usageValue).toBe("0.125");
    expect(totalDuration?.dataset.usageValue).toBe("17");
    expect(totalDuration?.textContent).toBe("17 s");
    expect(totalTokens?.dataset.usageValue).toBe("330");
    expect(visibleText(html)).toContain("studio-claude-code (1) · studio-runner (1)");
  });

  it("coût partiel : « au moins » + entrées inconnues, jamais un total exact", () => {
    const html = usageSummaryHtml(summary());
    const [cost] = metric(html, "cost");
    expect(cost?.dataset.usageStatus).toBe("partial");
    expect(cost?.textContent).toBe("au moins 0,125 USD · inconnu pour 1 entrée");
    expect(visibleText(html)).toContain("partiel");
  });

  it("coût inconnu : « inconnu », aucune valeur ni zéro", () => {
    const html = costValueHtml({ status: "unknown", known_sum: null, currency: null, by_currency: [], ...coverage(0, 0, 3) });
    expect(html).toContain(">inconnu<");
    expect(html).not.toContain("data-usage-value");
    expect(html).not.toMatch(/\b0\b/);
  });

  it("devises mélangées : pas de total, détail par devise tel quel", () => {
    const html = costValueHtml({
      status: "mixed_currency",
      known_sum: null,
      currency: null,
      by_currency: [
        { currency: "EUR", known_sum: "3", entries: 1 },
        { currency: "USD", known_sum: "2.00", entries: 2 },
      ],
      ...coverage(2, 1),
    });
    const text = visibleText(html);
    expect(text).toContain("Devises mélangées : pas de total");
    expect(text).toContain("3 EUR (1 entrée)");
    expect(text).toContain("2,00 USD (2 entrées)");
    expect(text).not.toMatch(/5(,00)? /);
  });

  it("estimé : préfixe ≈ et mention « estimé »", () => {
    const html = costValueHtml({ status: "estimated", known_sum: "2.00", currency: "USD", by_currency: [], ...coverage(1, 1) });
    expect(visibleText(html)).toBe("≈ 2,00 USD (estimé)");
  });

  it("statut inconnu du client : jamais présenté comme exact", () => {
    const html = costValueHtml({
      status: "future_status" as never,
      known_sum: "1",
      currency: "USD",
      by_currency: [],
      ...coverage(1),
    });
    expect(visibleText(html)).toBe("au moins 1 USD · statut inconnu (future_status)");
  });

  it("aucun UUID ni prompt visible hors détails techniques repliés", () => {
    const html = usageSummaryHtml(summary({ task_id: TASK }));
    expect(visibleText(html)).not.toMatch(UUID);
    expect(html).toContain('<details class="ds-tech"');
    expect(html).toContain(`href="#/tasks/${TASK}"`);
    expect(visibleText(html)).toContain("Afficher le coût");
    expect(html.toLowerCase()).not.toContain("prompt");
  });

  it("regroupement par configuration et par jour : libellés lisibles", () => {
    const byConfig = usageSummaryHtml(
      summary({ group_by: "configuration", groups: [aggregate({ key: { harness: "codex", provider: null, model: null } })] }),
    );
    expect(visibleText(byConfig)).toContain("codex · inconnu · inconnu");
    const byDay = usageSummaryHtml(summary({ group_by: "day", groups: [aggregate({ key: { day: "2026-10-11" } })] }));
    expect(visibleText(byDay)).toContain("11/10/2026");
  });

  it("période vide : état explicite, aucun total", () => {
    const empty = aggregate({ entries: 0 });
    const html = usageSummaryHtml(summary({ total: empty, groups: [] }));
    expect(html).toContain("data-usage-empty");
    expect(metric(html, "cost")).toHaveLength(0);
  });

  it("groupes tronqués : annoncé, le total couvre toute la période", () => {
    expect(usageSummaryHtml(summary({ truncated: true }))).toContain("data-usage-truncated");
  });
});

describe("formatSeconds", () => {
  it("convertit l'unité sans arrondir les petites durées", () => {
    expect(formatSeconds("12.25")).toBe("12,25 s");
    expect(formatSeconds("125")).toBe("2 min 05 s");
    expect(formatSeconds("3725")).toBe("1 h 02 min 05 s");
  });
});

describe("taskUsageSectionHtml", () => {
  it("absent : rien ; indisponible : mention discrète ; sinon total de la tâche", () => {
    expect(taskUsageSectionHtml(undefined)).toBe("");
    expect(taskUsageSectionHtml(null)).toContain("Consommation indisponible");
    const html = taskUsageSectionHtml(summary({ task_id: TASK, group_by: "none", groups: [] }));
    expect(html).toContain("Consommation");
    expect(metric(html, "duration")[0]?.dataset.usageValue).toBe("17");
    expect(visibleText(html)).not.toMatch(UUID);
  });
});

describe("renderProjectUsageInto", () => {
  function fakeClient(reply: { data?: unknown; status: number }): StudioClient {
    const get = vi.fn(async () => ({
      data: reply.data,
      error: undefined,
      response: new Response(null, { status: reply.status }),
    }));
    return { GET: get } as unknown as StudioClient;
  }

  it("charge 30 jours par tâche puis recharge au changement de période", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const client = fakeClient({ status: 200, data: summary() });
    const now = Date.parse("2026-10-13T12:00:00Z");
    await renderProjectUsageInto(root, { client, projectId: PROJECT, authed: true, now: () => now });
    const get = client.GET as unknown as ReturnType<typeof vi.fn>;
    expect(get.mock.calls[0]?.[0]).toBe("/api/v1/usage/summary");
    expect(get.mock.calls[0]?.[1]).toMatchObject({
      params: { query: { project_id: PROJECT, group_by: "task", since: usageSince("30d", now) } },
    });
    expect(root.querySelector('[data-usage-metric="cost"]')?.getAttribute("data-usage-value")).toBe("0.125");

    const period = root.querySelector<HTMLSelectElement>("[data-usage-period]");
    if (period === null) throw new Error("period select missing");
    period.value = "all";
    period.dispatchEvent(new Event("change"));
    await vi.waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    const query = (get.mock.calls[1]?.[1] as { params: { query: Record<string, string> } }).params.query;
    expect(query.since).toBeUndefined();
  });

  it("403 : refus nommé, jamais bloquant ; réponse inattendue : indisponible", async () => {
    const denied = document.createElement("div");
    await renderProjectUsageInto(denied, { client: fakeClient({ status: 403 }), projectId: PROJECT, authed: true });
    expect(denied.textContent).toContain("n'a pas accès");
    const odd = document.createElement("div");
    await renderProjectUsageInto(odd, { client: fakeClient({ status: 200, data: [] }), projectId: PROJECT, authed: true });
    expect(odd.querySelector("[data-usage-unavailable]")).not.toBeNull();
  });

  it("non connecté : rien n'est rendu et aucun appel n'est fait", async () => {
    const root = document.createElement("div");
    const client = fakeClient({ status: 200, data: summary() });
    await renderProjectUsageInto(root, { client, projectId: PROJECT, authed: false });
    expect(root.innerHTML).toBe("");
    expect(client.GET).not.toHaveBeenCalled();
  });
});
