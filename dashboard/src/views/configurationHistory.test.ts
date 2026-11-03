// @vitest-environment happy-dom
/**
 * Historique des configurations (P06-history-option, DEC-0221) : les groupes
 * restent dans l'ordre reçu, un taux nul n'est jamais présenté comme 0 %, les
 * clés absentes ou mixtes sont nommées, et aucun UUID n'est visible hors
 * détails techniques repliés.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import type { ConfigurationHistory, ConfigurationHistoryGroup, ConfigurationRate } from "../usageApi";
import {
  configurationHistoryHtml,
  historyCaveatBannerHtml,
  historyWindow,
  keyValue,
  rateValueText,
  renderConfigurationHistoryInto,
} from "./configurationHistory";

const PROJECT = "aaaaaaaa-1111-4222-8333-444444444444";
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

function rate(overrides: Partial<ConfigurationRate> = {}): ConfigurationRate {
  return {
    key: "succeeded",
    definition: "lancements réussis sur lancements terminaux",
    numerator: 3,
    denominator: 4,
    covered: 4,
    launches: 4,
    value: 0.75,
    ...overrides,
  };
}

function group(overrides: Partial<ConfigurationHistoryGroup> = {}): ConfigurationHistoryGroup {
  return {
    key: {
      harness: "claude-code",
      profile_key: "default",
      profile_contract_version: 2,
      profile_digest: null,
      harness_version: "1.2.3",
      provider: "anthropic",
      model: "claude-sonnet",
    },
    launches: 4,
    first_requested_at: "2026-10-01T09:00:00Z",
    last_requested_at: "2026-10-10T18:00:00Z",
    status_counts: { succeeded: 3, failed: 1 },
    rates: [rate()],
    ledger_entries: 4,
    ai_work_entries: 2,
    total_tokens: { status: "exact", known_sum: 1200, measured_entries: 4, estimated_entries: 0, unknown_entries: 0 },
    cost: {
      status: "exact",
      known_sum: "0.50",
      currency: "USD",
      by_currency: [],
      measured_entries: 4,
      estimated_entries: 0,
      unknown_entries: 0,
    },
    comparable: false,
    ...overrides,
  };
}

function history(overrides: Partial<ConfigurationHistory> = {}): ConfigurationHistory {
  return {
    project_id: PROJECT,
    since: "2026-10-01T00:00:00Z",
    until: "2026-10-13T00:00:00Z",
    generated_at: "2026-10-13T12:00:00Z",
    population: "task_launch",
    ranking: "none",
    launches: 4,
    groups: [group()],
    unattributed: { ledger_entries: 0, ai_work_entries: 0 },
    caveats: ["tests_not_quality", "not_ranked", "no_minimum_sample"],
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

function fakeClient(reply: { data?: unknown; status: number }): StudioClient {
  const get = vi.fn(async () => ({
    data: reply.data,
    error: undefined,
    response: new Response(null, { status: reply.status }),
  }));
  return { GET: get } as unknown as StudioClient;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("keyValue", () => {
  it("nomme l'absence et le désaccord, sans inventer de valeur", () => {
    expect(keyValue(null)).toBe("inconnu");
    expect(keyValue(undefined)).toBe("inconnu");
    expect(keyValue("")).toBe("inconnu");
    expect(keyValue("mixed")).toBe("mixte");
    expect(keyValue("claude-code")).toBe("claude-code");
  });
});

describe("rateValueText", () => {
  it("affiche x/n et le pourcentage, jamais sans dénominateur", () => {
    expect(rateValueText(rate())).toBe("3/4 (75 %)");
    expect(rateValueText(rate({ numerator: 1, denominator: 3, value: 1 / 3 }))).toBe("1/3 (33,3 %)");
  });

  it("n = 0 : « non calculable (n = 0) », jamais 0 %", () => {
    const text = rateValueText(rate({ numerator: 0, denominator: 0, covered: 0, launches: 0, value: null }));
    expect(text).toBe("non calculable (n = 0)");
    expect(text).not.toContain("%");
  });
});

describe("configurationHistoryHtml", () => {
  it("clés null → inconnu et mixed → mixte", () => {
    const html = configurationHistoryHtml(
      history({
        groups: [
          group({
            key: {
              harness: "codex",
              profile_key: null,
              profile_contract_version: null,
              profile_digest: null,
              harness_version: "mixed",
              provider: null,
              model: "mixed",
            },
          }),
        ],
      }),
    );
    const text = visibleText(html);
    expect(text).toContain("codex");
    expect(text).toContain("inconnu");
    expect(text).toContain("mixte");
    expect(text).not.toContain("mixed");
  });

  it("taux n = 0 : non calculable, la définition et la couverture restent visibles", () => {
    const html = configurationHistoryHtml(
      history({
        groups: [
          group({
            rates: [
              rate({ key: "succeeded", numerator: 0, denominator: 0, covered: 0, launches: 0, value: null }),
              rate({ key: "session_linked", numerator: 2, denominator: 4, covered: 4, launches: 4, value: 0.5 }),
            ],
          }),
        ],
      }),
    );
    const text = visibleText(html);
    expect(text).toContain("non calculable (n = 0)");
    expect(text).toContain("2/4 (50 %)");
    expect(text).toContain("lancements réussis sur lancements terminaux");
    expect(text).toContain("couverture 4/4");
    expect(text).toContain("Période");
    expect(html).toContain('data-history-rate="succeeded"');
  });

  it("ordre des groupes conservé, aucun tri ni classement", () => {
    const first = group({
      key: { ...group().key, harness: "z-harness", model: "z-model" },
      rates: [rate({ numerator: 0, denominator: 4, value: 0 })],
    });
    const second = group({
      key: { ...group().key, harness: "a-harness", model: "a-model" },
      rates: [rate({ numerator: 4, denominator: 4, value: 1 })],
    });
    const html = configurationHistoryHtml(history({ groups: [first, second] }));
    const root = document.createElement("div");
    root.innerHTML = html;
    const headings = [...root.querySelectorAll("[data-history-group] h3")].map((node) => node.textContent ?? "");
    expect(headings[0]).toContain("z-harness");
    expect(headings[1]).toContain("a-harness");
  });

  it("bandeau permanent : non comparables, non classés, tests ≠ qualité, aucun minimum", () => {
    const html = historyCaveatBannerHtml();
    const text = visibleText(html);
    expect(html).toContain("data-history-banner");
    expect(text).toContain("Groupes non comparables, non classés");
    expect(text).toContain("Tests réussis ≠ garantie de qualité");
    expect(text).toContain("Aucun effectif minimum");
  });

  it("aucun UUID visible hors détails techniques repliés", () => {
    const html = configurationHistoryHtml(history());
    expect(visibleText(html)).not.toMatch(UUID);
    expect(html).toContain('<details class="ds-tech"');
  });

  it("section « Non attribué » : ledger et travail IA séparés des groupes", () => {
    const html = configurationHistoryHtml(history({ unattributed: { ledger_entries: 3, ai_work_entries: 2 } }));
    const root = document.createElement("div");
    root.innerHTML = html;
    const section = root.querySelector("[data-history-unattributed]");
    expect(section).not.toBeNull();
    const text = section?.textContent ?? "";
    expect(text).toContain("Non attribué");
    expect(text).toContain("3");
    expect(text).toContain("2");
    expect(text).toContain("jamais répartis dans un groupe");
  });

  it("période vide : état explicite, section non attribuée toujours présente", () => {
    const html = configurationHistoryHtml(history({ groups: [], launches: 0 }));
    expect(html).toContain("data-history-empty");
    expect(html).toContain("data-history-unattributed");
  });

  it("groupes tronqués : annoncé", () => {
    expect(configurationHistoryHtml(history({ truncated: true }))).toContain("data-history-truncated");
  });
});

describe("historyWindow", () => {
  it("calcule la fenêtre [since, until) demandée par la route", () => {
    const now = Date.parse("2026-10-13T12:00:00Z");
    expect(historyWindow("30d", now)).toEqual({
      since: "2026-09-13T12:00:00.000Z",
      until: "2026-10-13T12:00:00.000Z",
    });
    expect(historyWindow("all", now).since).toBe("1970-01-01T00:00:00.000Z");
  });
});

describe("renderConfigurationHistoryInto", () => {
  it("appelle la route avec la période choisie et affiche le bandeau", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const client = fakeClient({ status: 200, data: history() });
    const now = Date.parse("2026-10-13T12:00:00Z");
    await renderConfigurationHistoryInto(root, { client, projectId: PROJECT, authed: true, now: () => now });
    const get = client.GET as unknown as ReturnType<typeof vi.fn>;
    expect(get.mock.calls[0]?.[0]).toBe("/api/v1/usage/configuration-history");
    expect(get.mock.calls[0]?.[1]).toMatchObject({
      params: { query: { project_id: PROJECT, since: historyWindow("30d", now).since, until: historyWindow("30d", now).until } },
    });
    expect(root.querySelector("[data-history-banner]")).not.toBeNull();
    expect(root.querySelector('[data-history-rate="succeeded"]')?.textContent).toContain("3/4 (75 %)");

    const period = root.querySelector<HTMLSelectElement>("[data-history-period]");
    if (period === null) throw new Error("period select missing");
    period.value = "all";
    period.dispatchEvent(new Event("change"));
    await vi.waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    const query = (get.mock.calls[1]?.[1] as { params: { query: Record<string, string> } }).params.query;
    expect(query.since).toBe("1970-01-01T00:00:00.000Z");
  });

  it("403 : refus nommé ; réponse inattendue : indisponible", async () => {
    const denied = document.createElement("div");
    await renderConfigurationHistoryInto(denied, { client: fakeClient({ status: 403 }), projectId: PROJECT, authed: true });
    expect(denied.textContent).toContain("n'a pas accès");
    const odd = document.createElement("div");
    await renderConfigurationHistoryInto(odd, { client: fakeClient({ status: 200, data: [] }), projectId: PROJECT, authed: true });
    expect(odd.querySelector("[data-history-unavailable]")).not.toBeNull();
  });

  it("non connecté : rien n'est rendu et aucun appel n'est fait", async () => {
    const root = document.createElement("div");
    const client = fakeClient({ status: 200, data: history() });
    await renderConfigurationHistoryInto(root, { client, projectId: PROJECT, authed: false });
    expect(root.innerHTML).toBe("");
    expect(client.GET).not.toHaveBeenCalled();
  });
});
