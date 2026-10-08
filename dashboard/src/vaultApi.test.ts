/**
 * P14 — client Vault : les routes canoniques, les alias snake_case et
 * `expected_version` obligatoire. Un 409 remonte en `ApiError` (le serveur
 * garde la version vraie), jamais en écrasement silencieux.
 */
import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import { ApiError } from "./api";
import {
  getVaultNote,
  getVaultVersion,
  listVaultTree,
  listVaultVersions,
  searchVault,
  updateVaultNote,
} from "./vaultApi";

type Fake = Record<"GET" | "PATCH", ReturnType<typeof vi.fn>>;
const fakeClient = (impl: Fake): StudioClient => impl as unknown as StudioClient;
const emptyFake = (): Fake => ({ GET: vi.fn(), PATCH: vi.fn() });

const ok = <T>(data: T): { data: T; error?: undefined; response: Response } => ({
  data,
  response: { ok: true, status: 200 } as Response,
});

const fail = (status: number, error: unknown): { data?: undefined; error: unknown; response: Response } => ({
  error,
  response: { ok: false, status } as Response,
});

describe("listVaultTree", () => {
  it("maps camelCase to the snake_case query of the API", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ items: [] }));
    await listVaultTree(fakeClient({ ...emptyFake(), GET }), {
      scope: "project",
      projectId: "p1",
      status: "proposed",
      limit: 25,
      cursor: "c0",
    });
    expect(GET).toHaveBeenCalledWith("/api/v1/vault/tree", {
      params: {
        query: { scope: "project", project_id: "p1", status: "proposed", limit: 25, cursor: "c0" },
      },
    });
  });

  it("omits unset filters rather than sending null", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ items: [] }));
    await listVaultTree(fakeClient({ ...emptyFake(), GET }));
    expect(GET).toHaveBeenCalledWith("/api/v1/vault/tree", { params: { query: {} } });
  });

  it("raises the server error on a rejected read", async () => {
    const GET = vi.fn().mockResolvedValue(fail(403, { detail: { code: "forbidden" } }));
    await expect(listVaultTree(fakeClient({ ...emptyFake(), GET }))).rejects.toBeInstanceOf(ApiError);
  });
});

describe("searchVault", () => {
  it("sends q, scope and the repeatable note_type/status filters", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ items: [], total: 0, truncated: false }));
    await searchVault(fakeClient({ ...emptyFake(), GET }), {
      q: "cache",
      scope: "project",
      projectId: "p1",
      noteTypes: ["rule", "convention"],
      statuses: ["proposed"],
      limit: 10,
    });
    expect(GET).toHaveBeenCalledWith("/api/v1/vault/search", {
      params: {
        query: {
          q: "cache",
          scope: "project",
          project_id: "p1",
          note_type: ["rule", "convention"],
          status: ["proposed"],
          limit: 10,
        },
      },
    });
  });

  it("drops empty filter arrays instead of sending an empty list", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ items: [], total: 0, truncated: false }));
    await searchVault(fakeClient({ ...emptyFake(), GET }), { q: "x", noteTypes: [], statuses: [] });
    const query = (GET.mock.calls[0]?.[1] as { params: { query: Record<string, unknown> } }).params.query;
    expect(query).not.toHaveProperty("note_type");
    expect(query).not.toHaveProperty("status");
  });
});

describe("getVaultNote / getVaultVersion", () => {
  it("reads the note and one of its versions by their canonical paths", async () => {
    const GET = vi.fn().mockResolvedValue(ok({}));
    await getVaultNote(fakeClient({ ...emptyFake(), GET }), "n1");
    expect(GET).toHaveBeenCalledWith("/api/v1/vault/notes/{note_id}", { params: { path: { note_id: "n1" } } });
    await getVaultVersion(fakeClient({ ...emptyFake(), GET }), "n1", 3);
    expect(GET).toHaveBeenCalledWith("/api/v1/vault/notes/{note_id}/versions/{version}", {
      params: { path: { note_id: "n1", version: 3 } },
    });
  });

  it("paginates the history", async () => {
    const GET = vi.fn().mockResolvedValue(ok({ items: [] }));
    await listVaultVersions(fakeClient({ ...emptyFake(), GET }), "n1", { limit: 10, cursor: "c1" });
    expect(GET).toHaveBeenCalledWith("/api/v1/vault/notes/{note_id}/versions", {
      params: { path: { note_id: "n1" }, query: { limit: 10, cursor: "c1" } },
    });
  });
});

describe("updateVaultNote", () => {
  it("always carries expected_version", async () => {
    const PATCH = vi.fn().mockResolvedValue(ok({ version: 4 }));
    await updateVaultNote(fakeClient({ ...emptyFake(), PATCH }), "n1", {
      expected_version: 3,
      status: "validated",
    });
    expect(PATCH).toHaveBeenCalledWith("/api/v1/vault/notes/{note_id}", {
      params: { path: { note_id: "n1" } },
      body: { expected_version: 3, status: "validated" },
    });
  });

  it("surfaces the 409 version conflict (with the server version) instead of writing over", async () => {
    const PATCH = vi
      .fn()
      .mockResolvedValue(fail(409, { detail: { error_code: "version_conflict", server_version: 7 } }));
    const client = fakeClient({ ...emptyFake(), PATCH });
    await expect(updateVaultNote(client, "n1", { expected_version: 3, status: "validated" })).rejects.toMatchObject({
      status: 409,
      errorCode: "version_conflict",
      serverVersion: 7,
    });
  });
});