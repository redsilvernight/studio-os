import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import {
  classifyAccountError,
  createIdempotencyKeyer,
  passwordProblem,
  requestEmailFlow,
  resetPassword,
  verifyEmail,
} from "./publicAccountApi";

const coded = (code: string) => ({ detail: { error_code: code } });

describe("classifyAccountError", () => {
  it("keeps the documented A4 codes", () => {
    expect(classifyAccountError(404, coded("registration_unavailable"))).toBe("registration_unavailable");
    expect(classifyAccountError(404, coded("password_recovery_unavailable"))).toBe("password_recovery_unavailable");
    expect(classifyAccountError(400, coded("invalid_or_expired_token"))).toBe("invalid_or_expired_token");
  });

  it("maps statuses without a known code", () => {
    expect(classifyAccountError(429, { detail: "rate limit exceeded" })).toBe("rate_limited");
    expect(classifyAccountError(409, coded("idempotency_key_in_progress"))).toBe("conflict");
    expect(classifyAccountError(422, { detail: [] })).toBe("invalid_input");
    expect(classifyAccountError(400, coded("idempotency_key_required"))).toBe("server");
    expect(classifyAccountError(500, "boom")).toBe("server");
  });
});

describe("createIdempotencyKeyer", () => {
  it("replays the key for the same payload and renews it otherwise", () => {
    let n = 0;
    const keyer = createIdempotencyKeyer(() => `k${++n}`);
    expect(keyer.keyFor("a@x.io")).toBe("k1");
    expect(keyer.keyFor("a@x.io")).toBe("k1");
    expect(keyer.keyFor("b@x.io")).toBe("k2");
    keyer.reset();
    expect(keyer.keyFor("b@x.io")).toBe("k3");
  });
});

describe("passwordProblem", () => {
  it("enforces 12 characters, 72 UTF-8 bytes and confirmation", () => {
    expect(passwordProblem("court", "court")).toMatch(/12 caractères/);
    const long = "é".repeat(37); // 37 characters, 74 bytes
    expect(passwordProblem(long, long)).toMatch(/72 octets/);
    expect(passwordProblem("correct-horse-1", "correct-horse-2")).toMatch(/correspondent pas/);
    expect(passwordProblem("correct-horse-1", "correct-horse-1")).toBeNull();
  });
});

function fakeClient(status: number, error?: unknown) {
  const POST = vi.fn(async () => ({ response: new Response(null, { status }), error }));
  return { client: { POST } as unknown as StudioClient, POST };
}

describe("account calls", () => {
  it("sends the Idempotency-Key and the email only", async () => {
    const { client, POST } = fakeClient(202);
    await expect(requestEmailFlow(client, "register", "a@x.io", "key-1")).resolves.toEqual({ ok: true });
    expect(POST).toHaveBeenCalledWith("/api/v1/auth/register", {
      params: { header: { "Idempotency-Key": "key-1" } },
      body: { email: "a@x.io" },
    });
  });

  it("routes resend and forgot to their endpoints", async () => {
    const { client, POST } = fakeClient(202);
    await requestEmailFlow(client, "resend", "a@x.io", "k");
    await requestEmailFlow(client, "forgot", "a@x.io", "k");
    expect(POST.mock.calls.map((call) => (call as unknown[])[0])).toEqual([
      "/api/v1/auth/resend-verification",
      "/api/v1/auth/forgot-password",
    ]);
  });

  it("reports a network failure", async () => {
    const client = { POST: vi.fn(async () => Promise.reject(new TypeError("offline"))) } as unknown as StudioClient;
    await expect(verifyEmail(client, { token: "t", password: "p", display_name: "n" })).resolves.toEqual({
      ok: false,
      kind: "network",
    });
  });

  it("classifies a refused reset", async () => {
    const { client } = fakeClient(400, coded("invalid_or_expired_token"));
    await expect(resetPassword(client, { token: "t", new_password: "p" })).resolves.toEqual({
      ok: false,
      kind: "invalid_or_expired_token",
    });
  });
});
