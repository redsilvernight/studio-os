// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { billingNoticeHtml, renderSubscription, subscriptionHtml, usageHtml } from "./subscription";
import { parseCheckoutReturn } from "../billingApi";
import { parseRoute } from "../router";
import { resetStudioStoreForTests, setStudios } from "../studioStore";
import type { Studio } from "../studiosApi";

const studio = (plan: string): Studio => ({ id: "s1", name: "Atelier Phare", slug: "phare", plan, status: "active", role: "owner" });
const flush = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
};

beforeEach(() => resetStudioStoreForTests());
afterEach(() => vi.unstubAllGlobals());

describe("subscription billing (N3)", () => {
  it("offers Pro with both prices on the free plan, no change on return", () => {
    setStudios([studio("Gratuit")]);
    const html = subscriptionHtml("owner", "success");
    expect(html).toContain("9 € / mois");
    expect(html).toContain("90 € / an");
    expect(html).toContain("En attente de confirmation");
    expect(html).toContain("Gratuit");
    expect(html).toContain('role="dialog"');
  });

  it("shows the portal on Pro without pending notice", () => {
    setStudios([studio("Pro")]);
    const html = subscriptionHtml("owner", "success");
    expect(html).toContain("Gérer l'abonnement");
    expect(html).not.toContain("En attente");
    expect(html).not.toContain("sub-upgrade");
  });

  it("explains a cancelled checkout", () => {
    setStudios([studio("Gratuit")]);
    expect(subscriptionHtml("owner", "cancel")).toContain("Paiement annulé");
  });

  it("never shows billing controls to non-owners", () => {
    setStudios([studio("Gratuit")]);
    expect(subscriptionHtml("member", null)).not.toContain("sub-upgrade");
  });

  it("posts the chosen interval after confirmation and redirects to Stripe", async () => {
    setStudios([studio("Gratuit")]);
    const fetchMock = vi.fn(async (..._args: unknown[]) => new Response(JSON.stringify({ url: "https://checkout.stripe.com/x", counters: [], limits: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const redirect = vi.fn();
    const view = document.createElement("div");
    document.body.append(view);
    renderSubscription(view, "owner", { baseUrl: "http://api", redirect, checkoutReturn: null });
    (view.querySelector('input[value="year"]') as HTMLInputElement).checked = true;
    (view.querySelector("#sub-upgrade") as HTMLElement).click();
    expect((view.querySelector("#sub-confirm") as HTMLElement).hidden).toBe(false);
    (view.querySelector("#sub-confirm-ok") as HTMLElement).click();
    await flush();
    const [url, init] = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/checkout")) as unknown as [string, RequestInit];
    expect(url).toBe("http://api/api/v1/studios/s1/billing/checkout");
    expect(init.body).toBe('{"interval":"year"}');
    expect(redirect).toHaveBeenCalledWith("https://checkout.stripe.com/x");
    view.remove();
  });

  it("maps 409 already_subscribed to a readable alert", async () => {
    setStudios([studio("Gratuit")]);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { error_code: "already_subscribed" } }), { status: 409 })));
    const redirect = vi.fn();
    const view = document.createElement("div");
    document.body.append(view);
    renderSubscription(view, "owner", { baseUrl: "", redirect, checkoutReturn: null });
    (view.querySelector("#sub-upgrade") as HTMLElement).click();
    (view.querySelector("#sub-confirm-ok") as HTMLElement).click();
    await flush();
    await flush();
    expect(redirect).not.toHaveBeenCalled();
    expect(view.querySelector('[role="alert"]')?.textContent).toContain("déjà abonné");
    view.remove();
  });
});

const status = (over: Partial<Parameters<typeof billingNoticeHtml>[0]>): Parameters<typeof billingNoticeHtml>[0] => ({
  plan: "pro",
  status: "active",
  past_due_since: null,
  grace_ends_at: null,
  grace_days: 7,
  trial_ends_at: null,
  ...over,
});

describe("billing status and usage (S4b)", () => {
  it("announces the trial end and the unpaid grace end, nothing otherwise", () => {
    expect(billingNoticeHtml(status({ status: "trialing", trial_ends_at: "2026-12-07T10:00:00Z" }))).toContain("Essai gratuit en cours");
    const unpaid = billingNoticeHtml(status({ status: "past_due", past_due_since: "2026-11-20T10:00:00Z", grace_ends_at: "2026-11-27T10:00:00Z" }));
    expect(unpaid).toContain("Paiement en échec");
    expect(unpaid).toContain("7 jours de grâce");
    expect(billingNoticeHtml(status({}))).toBe("");
  });

  it("lists counters against limits, unlimited without a ceiling", () => {
    const html = usageHtml({
      studio_id: "s1",
      plan: { code: "free", name: "Gratuit", rank: 0 } as never,
      limits: [{ key: "projects", max_value: 3, unit: "" }],
      counters: [
        { key: "projects", value: 2, source: "live" },
        { key: "members", value: 4, source: "live" },
      ],
      upgrade_url: "/settings/subscription",
      generated_at: "2026-11-23T10:00:00Z",
    });
    expect(html).toContain("2 sur 3");
    expect(html).toContain("4 · illimité");
  });

  it("renders the tabs, the notice and the usage from the API", async () => {
    setStudios([studio("Pro")]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        new Response(
          JSON.stringify(
            String(url).endsWith("/billing")
              ? status({ status: "trialing", trial_ends_at: "2026-12-07T10:00:00Z" })
              : { studio_id: "s1", plan: {}, limits: [], counters: [{ key: "machines", value: 2, source: "live" }], upgrade_url: "", generated_at: "" },
          ),
          { status: 200 },
        ),
      ),
    );
    const view = document.createElement("div");
    document.body.append(view);
    renderSubscription(view, "owner", { baseUrl: "", checkoutReturn: null });
    await flush();
    await flush();
    expect(view.querySelectorAll('[role="tab"]').length).toBe(2);
    expect(view.querySelector("#sub-billing")?.textContent).toContain("Essai gratuit en cours");
    expect(view.querySelector("#sub-usage")?.textContent).toContain("Appareils");
    view.remove();
  });
});

describe("checkout return parsing", () => {
  it("reads the query from search or hash only for known values", () => {
    expect(parseCheckoutReturn("?checkout=cancel", "#/abonnement")).toBe("cancel");
    expect(parseCheckoutReturn("", "#/abonnement?checkout=portal")).toBe("portal");
    expect(parseCheckoutReturn("?checkout=evil", "")).toBeNull();
  });
  it("routes #/abonnement?checkout=success to the subscription view", () => {
    expect(parseRoute("#/abonnement?checkout=success")).toEqual({ name: "subscription" });
  });
});
