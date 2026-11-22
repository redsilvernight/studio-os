/**
 * Cycle de vie des studios — client typé local (vitest, node).
 *
 * On vérifie les verbes, les chemins et les corps envoyés : le contrat
 * serveur étant écrit ailleurs, c'est la seule garde-fou côté dashboard.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  acceptInvitation,
  cancelStudioDeletion,
  createStudio,
  createStudioExport,
  createStudioInvitation,
  getStudio,
  getStudioExport,
  listStudioInvitations,
  listStudioMembers,
  listStudios,
  previewInvitation,
  removeStudioMember,
  revokeStudioInvitation,
  scheduleStudioDeletion,
  transferStudioOwnership,
  updateStudioMemberRole,
} from "./studioLifecycleApi";

const BASE = "https://api.example.test";
const realFetch = globalThis.fetch;

interface Call {
  url: string;
  method: string;
  body: unknown;
}

function mockFetch(status: number, payload: unknown): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
    });
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => payload,
    } as Response;
  }) as unknown as typeof fetch;
  return calls;
}

beforeEach(() => {
  globalThis.fetch = realFetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

describe("lecture des studios", () => {
  it("liste les studios du compte", async () => {
    const calls = mockFetch(200, [{ id: "s1", slug: "atelier-phare", name: "Atelier Phare", plan: "free", status: "active", role: "owner" }]);
    const studios = await listStudios(BASE);
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios`);
    expect(calls[0]?.method).toBe("GET");
    expect(studios[0]?.name).toBe("Atelier Phare");
  });

  it("lit le détail d'un studio", async () => {
    const calls = mockFetch(200, { id: "s1", slug: "atelier-phare", name: "Atelier Phare", plan: "free", status: "suspended", role: "owner", deletion_scheduled_at: null });
    const studio = await getStudio(BASE, "s1");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios/s1`);
    expect(studio.status).toBe("suspended");
    expect(studio.deletion_scheduled_at).toBeNull();
  });

  it("crée un studio avec son seul nom", async () => {
    const calls = mockFetch(200, { id: "s2", slug: "binaweb", name: "Binaweb", plan: "free", status: "active", role: "owner" });
    const studio = await createStudio(BASE, "Binaweb");
    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.body).toEqual({ name: "Binaweb" });
    expect(studio.role).toBe("owner");
  });
});

describe("invitations", () => {
  it("envoie une invitation avec l'adresse et le rôle", async () => {
    const calls = mockFetch(200, { id: "inv_1", studio_id: "s1", email: "lucie@exemple.fr", role: "member", expires_at: "2026-12-01T00:00:00Z", consumed_at: null, invited_by_user_id: "u1", created_at: "2026-11-21T00:00:00Z" });
    await createStudioInvitation(BASE, "s1", "lucie@exemple.fr", "member");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios/s1/invitations`);
    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.body).toEqual({ email: "lucie@exemple.fr", role: "member" });
  });

  it("liste les invitations en attente", async () => {
    const calls = mockFetch(200, []);
    await listStudioInvitations(BASE, "s1");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios/s1/invitations`);
    expect(calls[0]?.method).toBe("GET");
  });

  it("annule une invitation", async () => {
    const calls = mockFetch(204, null);
    await revokeStudioInvitation(BASE, "s1", "inv_1");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios/s1/invitations/inv_1`);
    expect(calls[0]?.method).toBe("DELETE");
  });

  it("lit l'état d'un lien sans l'accepter", async () => {
    const calls = mockFetch(200, { state: "valid", studio_name: "Atelier Phare", role: "member", inviter_display_name: "Marie" });
    const preview = await previewInvitation(BASE, "tok");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/invitations/preview`);
    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.body).toEqual({ token: "tok" });
    expect(preview.state).toBe("valid");
    expect(preview.studio_name).toBe("Atelier Phare");
    expect(preview.inviter_display_name).toBe("Marie");
  });

  it("accepte une invitation", async () => {
    const calls = mockFetch(200, { status: "accepted", studio_id: "s1", role: "member" });
    const result = await acceptInvitation(BASE, "tok");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/invitations/accept`);
    expect(calls[0]?.body).toEqual({ token: "tok" });
    expect(result.studio_id).toBe("s1");
  });

  it("remonte le 410 d'une invitation expirée avec son error_code", async () => {
    mockFetch(410, { detail: { error_code: "invitation_expired" } });
    await expect(acceptInvitation(BASE, "tok")).rejects.toBeInstanceOf(ApiError);
    const error = await acceptInvitation(BASE, "tok").catch((e: unknown) => e as ApiError);
    expect((error as ApiError).status).toBe(410);
    expect((error as ApiError).errorCode).toBe("invitation_expired");
  });

  it("remonte le 410 d'une invitation déjà utilisée avec son error_code", async () => {
    mockFetch(410, { detail: { error_code: "invitation_used" } });
    const error = await acceptInvitation(BASE, "tok").catch((e: unknown) => e as ApiError);
    expect((error as ApiError).status).toBe(410);
    expect((error as ApiError).errorCode).toBe("invitation_used");
  });
});

describe("membres", () => {
  it("liste les membres avec leur rôle", async () => {
    const calls = mockFetch(200, []);
    await listStudioMembers(BASE, "s1");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios/s1/members`);
  });

  it("change le rôle d'un membre", async () => {
    const calls = mockFetch(204, null);
    await updateStudioMemberRole(BASE, "s1", "u2", "admin");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios/s1/members/u2`);
    expect(calls[0]?.method).toBe("PATCH");
    expect(calls[0]?.body).toEqual({ role: "admin" });
  });

  it("retire un membre", async () => {
    const calls = mockFetch(204, null);
    await removeStudioMember(BASE, "s1", "u2");
    expect(calls[0]?.method).toBe("DELETE");
  });

  it("transfère la propriété", async () => {
    const calls = mockFetch(204, null);
    await transferStudioOwnership(BASE, "s1", "u2");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios/s1/transfer-ownership`);
    expect(calls[0]?.body).toEqual({ user_id: "u2" });
  });
});

describe("export et suppression", () => {
  it("prépare un export", async () => {
    const calls = mockFetch(200, { id: "exp_1" });
    const created = await createStudioExport(BASE, "s1");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios/s1/exports`);
    expect(calls[0]?.method).toBe("POST");
    expect(created.id).toBe("exp_1");
  });

  it("lit le lien de téléchargement de l'export", async () => {
    const calls = mockFetch(200, { download_url: "https://storage.example/x.zip", expires_at: "2026-11-21T10:15:00Z" });
    const link = await getStudioExport(BASE, "s1", "exp_1");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios/s1/exports/exp_1`);
    expect(link.download_url).toBe("https://storage.example/x.zip");
  });

  it("programme la suppression avec le slug de confirmation", async () => {
    const calls = mockFetch(200, { deletion_scheduled_at: "2026-12-05T10:00:00Z" });
    await scheduleStudioDeletion(BASE, "s1", "atelier-phare");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios/s1/deletion`);
    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.body).toEqual({ confirm_slug: "atelier-phare" });
  });

  it("annule la suppression pendant le délai de grâce", async () => {
    const calls = mockFetch(204, null);
    await cancelStudioDeletion(BASE, "s1");
    expect(calls[0]?.url).toBe(`${BASE}/api/v1/studios/s1/deletion`);
    expect(calls[0]?.method).toBe("DELETE");
  });
});
