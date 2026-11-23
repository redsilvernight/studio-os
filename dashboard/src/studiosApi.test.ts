// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import {
  listStudios,
  normalizeStudioRole,
  probeServer,
  studioRoleLabel,
  SINGLE_STUDIO_FALLBACK,
  type StudiosClient,
} from "./studiosApi";

function clientWith(response: { ok: boolean; status: number }, data?: unknown, error?: unknown): StudiosClient {
  return {
    GET: async () => ({ response, data, error }),
  };
}

describe("normalizeStudioRole", () => {
  it("maps known roles and aliases to the safest value", () => {
    expect(normalizeStudioRole("owner")).toBe("owner");
    expect(normalizeStudioRole("admin")).toBe("admin");
    expect(normalizeStudioRole("member")).toBe("member");
    expect(normalizeStudioRole("viewer")).toBe("viewer");
    expect(normalizeStudioRole("readonly")).toBe("viewer");
    expect(normalizeStudioRole("unknown-role")).toBe("viewer");
    expect(normalizeStudioRole(undefined)).toBe("viewer");
  });

  it("labels roles in French, never by color alone", () => {
    expect(studioRoleLabel("owner")).toBe("Propriétaire");
    expect(studioRoleLabel("admin")).toBe("Administrateur");
    expect(studioRoleLabel("member")).toBe("Membre");
    expect(studioRoleLabel("viewer")).toBe("Lecture seule");
  });
});

describe("listStudios", () => {
  it("returns typed studios on 200 and drops invalid entries", async () => {
    const client = clientWith({ ok: true, status: 200 }, [
      { id: "a", name: "Atelier Phare", slug: "phare", plan: "Gratuit", status: "active", role: "owner" },
      { id: "b", name: "Binaweb", slug: "bina", plan: "Pro", status: "suspended", role: "member" },
      { id: "", name: "", role: "owner" },
      { id: "c", name: "Sans formule", role: "readonly" },
    ]);
    const result = await listStudios(client);
    expect(result.fallback).toBe(false);
    expect(result.studios).toHaveLength(3);
    expect(result.studios[1]).toMatchObject({ status: "suspended", role: "member" });
    expect(result.studios[2]).toMatchObject({ plan: "Gratuit", role: "viewer", status: "active" });
  });

  it("falls back to a single studio on 404 (endpoint not yet deployed)", async () => {
    const result = await listStudios(clientWith({ ok: false, status: 404 }, null, "not found"));
    expect(result.fallback).toBe(true);
    expect(result.studios).toHaveLength(1);
    expect(result.studios[0]).toEqual({ ...SINGLE_STUDIO_FALLBACK });
  });

  it("throws a typed error on other failures", async () => {
    await expect(listStudios(clientWith({ ok: false, status: 500 }, null, "boom"))).rejects.toMatchObject({ status: 500 });
  });

  it("falls back to a single studio when the list is empty", async () => {
    const result = await listStudios(clientWith({ ok: true, status: 200 }, []));
    expect(result.fallback).toBe(true);
    expect(result.studios).toHaveLength(1);
  });
});

describe("probeServer", () => {
  it("returns true on 2xx and false on network failure", async () => {
    const ok = vi.fn(async () => new Response(null, { status: 200 }));
    expect(await probeServer("https://studio.example.com/", ok, 1000)).toBe(true);
    const failing = vi.fn(async () => {
      throw new Error("down");
    });
    expect(await probeServer("https://studio.example.com", failing, 1000)).toBe(false);
  });

  it("returns false on non-2xx answers", async () => {
    const down = vi.fn(async () => new Response(null, { status: 503 }));
    expect(await probeServer("https://studio.example.com", down, 1000)).toBe(false);
  });
});
