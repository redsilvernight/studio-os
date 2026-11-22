// @vitest-environment happy-dom
/**
 * Abonnements (DEC-0361) : liste, ajout validé côté client, modification avec
 * la version lue, suppression confirmée ; la consommation est relue après
 * chaque écriture.
 */
import { answerConfirm } from "../ds/confirmTest";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import type { UsageSubscription } from "../usageApi";
import { readSubscriptionTerms, renderUsageSubscriptionsInto, subscriptionFormHtml, subscriptionsTableHtml } from "./usageSubscriptions";

const PROJECT = "aaaaaaaa-1111-4222-8333-444444444444";
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
const NOW = Date.UTC(2026, 10, 15);

const MAX: UsageSubscription = {
  id: "cccccccc-1111-4222-8333-444444444444",
  project_id: PROJECT,
  label: "Claude Max",
  monthly_price: "100.00",
  currency: "EUR",
  harnesses: ["claude-code"],
  providers: [],
  starts_on: "2026-10-01",
  ends_on: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  version: 3,
};

function ok<T>(data: T, status = 200) {
  return Promise.resolve({ data, error: undefined, response: new Response(null, { status }) });
}

function formWith(values: Record<string, string>): HTMLFormElement {
  const root = document.createElement("div");
  root.innerHTML = subscriptionFormHtml(null, NOW);
  const form = root.querySelector<HTMLFormElement>("form") as HTMLFormElement;
  for (const [name, value] of Object.entries(values)) {
    const field = form.querySelector<HTMLInputElement | HTMLSelectElement>(`[name=${name}]`);
    if (field !== null) field.value = value;
  }
  return form;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("subscriptionsTableHtml", () => {
  it("affiche prix, couverture et période sans UUID", () => {
    const html = subscriptionsTableHtml([MAX]);
    expect(html).toContain("100,00 EUR");
    expect(html).toContain("claude-code");
    expect(html).toContain("(en cours)");
    expect(html).not.toMatch(UUID);
  });

  it("explique l'absence d'abonnement", () => {
    expect(subscriptionsTableHtml([])).toContain("Aucun abonnement déclaré");
  });
});

describe("readSubscriptionTerms", () => {
  it("lit les listes séparées par des virgules et le début par défaut", () => {
    const terms = readSubscriptionTerms(formWith({ label: "Codex Pro", monthly_price: "200", harnesses: "codex, opencode" }));
    expect(terms).toEqual({
      label: "Codex Pro",
      monthly_price: "200",
      currency: "EUR",
      harnesses: ["codex", "opencode"],
      providers: [],
      starts_on: "2026-11-01",
      ends_on: null,
    });
  });

  it("refuse une saisie sans couverture, un prix invalide ou une fin avant le début", () => {
    expect(readSubscriptionTerms(formWith({ label: "X", monthly_price: "10" }))).toMatch(/outil ou un fournisseur/);
    expect(readSubscriptionTerms(formWith({ label: "X", monthly_price: "-1", providers: "openai" }))).toMatch(/prix/);
    expect(
      readSubscriptionTerms(formWith({ label: "X", monthly_price: "1", providers: "openai", ends_on: "2026-10-01" })),
    ).toMatch(/fin précède/);
  });
});

describe("renderUsageSubscriptionsInto", () => {
  it("modifie avec la version lue puis relit la consommation", async () => {
    const put = vi.fn(() => ok({ ...MAX, monthly_price: "150.00", version: 4 }));
    const client = {
      GET: vi.fn(() => ok([MAX])),
      PUT: put,
      POST: vi.fn(),
      DELETE: vi.fn(),
    } as unknown as StudioClient;
    const onChange = vi.fn();
    const root = document.createElement("div");
    await renderUsageSubscriptionsInto(root, { client, projectId: PROJECT, onChange, now: () => NOW });
    root.querySelector<HTMLButtonElement>("[data-subscription-edit]")?.click();
    const price = root.querySelector<HTMLInputElement>("[name=monthly_price]") as HTMLInputElement;
    expect(price.value).toBe("100.00");
    price.value = "150";
    root.querySelector<HTMLFormElement>("[data-subscription-form]")?.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledOnce());
    expect(put).toHaveBeenCalledWith("/api/v1/usage/subscriptions/{subscription_id}", {
      params: { path: { subscription_id: MAX.id } },
      body: expect.objectContaining({ monthly_price: "150", expected_version: 3 }),
    });
  });

  it("ne supprime qu'après confirmation", async () => {
    const del = vi.fn(() => Promise.resolve({ data: undefined, error: undefined, response: new Response(null, { status: 204 }) }));
    const client = { GET: vi.fn(() => ok([MAX])), DELETE: del } as unknown as StudioClient;
    const root = document.createElement("div");
    await renderUsageSubscriptionsInto(root, { client, projectId: PROJECT, now: () => NOW });
    root.querySelector<HTMLButtonElement>("[data-subscription-delete]")?.click();
    await answerConfirm(false);
    expect(del).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>("[data-subscription-delete]")?.click();
    await answerConfirm(true);
    await vi.waitFor(() => expect(del).toHaveBeenCalledOnce());
    expect(del).toHaveBeenCalledWith("/api/v1/usage/subscriptions/{subscription_id}", {
      params: { path: { subscription_id: MAX.id }, query: { expected_version: 3 } },
    });
  });
});
