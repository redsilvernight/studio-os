// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderSubscription, subscriptionHtml } from "./subscription";
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
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ url: "https://checkout.stripe.com/x" }), { status: 200 }));
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
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
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
