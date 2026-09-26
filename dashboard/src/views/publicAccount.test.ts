// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "../api";
import type { AccountErrorKind } from "../publicAccountApi";
import { ACCOUNT_MESSAGES, renderPublicAccount, type PublicScreen, type TerminalKind } from "./publicAccount";

const SECRET = "s3cr3t-verification-token-0123456789";

interface Harness {
  root: HTMLElement;
  POST: ReturnType<typeof vi.fn>;
  screens: PublicScreen[];
  toLogin: ReturnType<typeof vi.fn>;
}

function reply(status: number, error?: unknown) {
  return async () => ({ response: new Response(null, { status }), error });
}

function mount(screen: PublicScreen, post: (...args: unknown[]) => Promise<unknown> = reply(202)): Harness {
  const root = document.createElement("div");
  document.body.replaceChildren(root);
  const POST = vi.fn(post);
  const screens: PublicScreen[] = [];
  const toLogin = vi.fn();
  const deps = {
    client: { POST } as unknown as StudioClient,
    go: (next: PublicScreen) => {
      screens.push(next);
      renderPublicAccount(root, next, deps);
    },
    toLogin,
  };
  renderPublicAccount(root, screen, deps);
  return { root, POST, screens, toLogin };
}

function fill(root: HTMLElement, values: Record<string, string>): void {
  for (const [name, value] of Object.entries(values)) {
    const input = root.querySelector<HTMLInputElement>(`input[name="${name}"]`);
    if (input === null) throw new Error(`missing input ${name}`);
    input.value = value;
  }
}

async function submit(root: HTMLElement): Promise<void> {
  root.querySelector<HTMLFormElement>("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

const screenOf = (root: HTMLElement) => root.querySelector<HTMLElement>("[data-testid=account-screen]")?.dataset["screen"];
const alertText = (root: HTMLElement) => root.querySelector<HTMLElement>("[data-testid=account-error]")?.textContent;
const STRONG = "correct-horse-battery";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("inscription", () => {
  it("sends the email and shows a non-discriminating confirmation", async () => {
    const h = mount({ name: "register" });
    fill(h.root, { email: "ada@example.com" });
    await submit(h.root);
    expect(h.POST).toHaveBeenCalledTimes(1);
    const [path, init] = h.POST.mock.calls[0] as [string, { params: { header: Record<string, string> }; body: unknown }];
    expect(path).toBe("/api/v1/auth/register");
    expect(init.body).toEqual({ email: "ada@example.com" });
    expect(init.params.header["Idempotency-Key"]).toMatch(/.+/);
    expect(screenOf(h.root)).toBe("sent");
    expect(h.root.textContent).toContain("Si une inscription est possible pour « ada@example.com »");
  });

  it("refuses an invalid email before calling the server", async () => {
    const h = mount({ name: "register" });
    fill(h.root, { email: "pas-une-adresse" });
    await submit(h.root);
    expect(h.POST).not.toHaveBeenCalled();
    expect(alertText(h.root)).toBe("Saisissez une adresse email valide.");
  });

  it("replays the same key on retry after a network error", async () => {
    let calls = 0;
    const h = mount({ name: "register" }, async () => {
      calls += 1;
      if (calls === 1) throw new TypeError("offline");
      return { response: new Response(null, { status: 202 }) };
    });
    fill(h.root, { email: "ada@example.com" });
    await submit(h.root);
    expect(alertText(h.root)).toBe(ACCOUNT_MESSAGES.network.message);
    await submit(h.root);
    const keys = h.POST.mock.calls.map((call) => (call[1] as { params: { header: Record<string, string> } }).params.header["Idempotency-Key"]);
    expect(keys[0]).toBe(keys[1]);
    expect(screenOf(h.root)).toBe("sent");
  });

  it("asks for a new link with a fresh key each time", async () => {
    const h = mount({ name: "sent", flow: "register", email: "ada@example.com" });
    await submit(h.root);
    await submit(h.root);
    expect(h.POST.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/auth/resend-verification",
      "/api/v1/auth/resend-verification",
    ]);
    const keys = h.POST.mock.calls.map((call) => (call[1] as { params: { header: Record<string, string> } }).params.header["Idempotency-Key"]);
    expect(keys[0]).not.toBe(keys[1]);
    expect(h.root.querySelector("[data-testid=account-notice]")?.textContent).toContain("Seul le plus récent fonctionne");
  });
});

describe("vérification", () => {
  it("activates the account with name and password", async () => {
    const h = mount({ name: "verify", token: SECRET }, reply(200));
    fill(h.root, { display_name: "  Ada  ", password: STRONG, confirmation: STRONG });
    await submit(h.root);
    expect(h.POST).toHaveBeenCalledWith("/api/v1/auth/verify-email", {
      body: { token: SECRET, password: STRONG, display_name: "Ada" },
    });
    expect(screenOf(h.root)).toBe("verified");
  });

  it("validates the password locally", async () => {
    const h = mount({ name: "verify", token: SECRET });
    fill(h.root, { display_name: "Ada", password: "court", confirmation: "court" });
    await submit(h.root);
    expect(h.POST).not.toHaveBeenCalled();
    expect(alertText(h.root)).toContain("12 caractères");
  });

  it("never exposes the secret in the page, storage or console", async () => {
    const logs = vi.spyOn(console, "log");
    const errors = vi.spyOn(console, "error");
    const h = mount({ name: "verify", token: SECRET }, reply(400, { detail: { error_code: "invalid_or_expired_token" } }));
    expect(h.root.innerHTML).not.toContain(SECRET);
    fill(h.root, { display_name: "Ada", password: STRONG, confirmation: STRONG });
    await submit(h.root);
    expect(document.documentElement.outerHTML).not.toContain(SECRET);
    expect(JSON.stringify({ ...localStorage })).not.toContain(SECRET);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(SECRET);
    expect(JSON.stringify([...logs.mock.calls, ...errors.mock.calls])).not.toContain(SECRET);
  });
});

describe("réinitialisation", () => {
  it("resets the password then points to the login", async () => {
    const h = mount({ name: "reset", token: SECRET }, reply(200));
    fill(h.root, { password: STRONG, confirmation: STRONG });
    await submit(h.root);
    expect(h.POST).toHaveBeenCalledWith("/api/v1/auth/reset-password", { body: { token: SECRET, new_password: STRONG } });
    expect(screenOf(h.root)).toBe("resetDone");
    await submit(h.root);
    expect(h.toLogin).toHaveBeenCalledTimes(1);
  });
});

describe("chaque état d'erreur a un écran explicite", () => {
  const terminal: Array<{ start: PublicScreen; values: Record<string, string>; status: number; kind: TerminalKind }> = [
    { start: { name: "register" }, values: { email: "a@x.io" }, status: 404, kind: "registration_unavailable" },
    { start: { name: "forgot" }, values: { email: "a@x.io" }, status: 404, kind: "password_recovery_unavailable" },
    {
      start: { name: "verify", token: SECRET },
      values: { display_name: "Ada", password: STRONG, confirmation: STRONG },
      status: 400,
      kind: "invalid_or_expired_token",
    },
    {
      start: { name: "reset", token: SECRET },
      values: { password: STRONG, confirmation: STRONG },
      status: 400,
      kind: "invalid_or_expired_token",
    },
  ];

  it.each(terminal)("$start.name → $kind : écran dédié", async ({ start, values, status, kind }) => {
    const h = mount(start, reply(status, { detail: { error_code: kind } }));
    fill(h.root, values);
    await submit(h.root);
    expect(screenOf(h.root)).toBe(`failure-${kind}`);
    expect(h.root.querySelector("h2")?.textContent).toBe(ACCOUNT_MESSAGES[kind].title);
    expect(h.root.querySelector("[data-testid=account-failure]")?.textContent).toBe(ACCOUNT_MESSAGES[kind].message);
  });

  it("an expired verification link leads to a new link request", async () => {
    const h = mount({ name: "failure", kind: "invalid_or_expired_token", flow: "verify" });
    await submit(h.root);
    expect(screenOf(h.root)).toBe("resend");
  });

  it("an expired reset link leads to the forgotten password form", async () => {
    const h = mount({ name: "failure", kind: "invalid_or_expired_token", flow: "reset" });
    await submit(h.root);
    expect(screenOf(h.root)).toBe("forgot");
  });

  const inline: Array<{ kind: AccountErrorKind; post: () => Promise<unknown> }> = [
    { kind: "rate_limited", post: reply(429, { detail: "rate limit exceeded" }) },
    { kind: "conflict", post: reply(409, { detail: { error_code: "idempotency_key_in_progress" } }) },
    { kind: "invalid_input", post: reply(422, { detail: [] }) },
    { kind: "server", post: reply(500) },
    { kind: "network", post: async () => Promise.reject(new TypeError("offline")) },
  ];

  it.each(inline)("$kind : alerte fixe, saisie conservée", async ({ kind, post }) => {
    const h = mount({ name: "register" }, post);
    fill(h.root, { email: "ada@example.com" });
    await submit(h.root);
    expect(screenOf(h.root)).toBe("register");
    expect(alertText(h.root)).toBe(ACCOUNT_MESSAGES[kind].message);
    expect(h.root.querySelector<HTMLInputElement>("input[name=email]")?.value).toBe("ada@example.com");
    expect(h.root.querySelector<HTMLButtonElement>("button[type=submit]")?.disabled).toBe(false);
  });

  it("never shows the server's own text", async () => {
    const h = mount({ name: "register" }, reply(500, { detail: "Traceback: internal" }));
    fill(h.root, { email: "ada@example.com" });
    await submit(h.root);
    expect(h.root.textContent).not.toContain("Traceback");
  });
});

it("« Retour à la connexion » returns to the login screen", () => {
  const h = mount({ name: "forgot" });
  h.root.querySelector<HTMLAnchorElement>("a[data-action=login]")!.click();
  expect(h.toLogin).toHaveBeenCalledTimes(1);
});
