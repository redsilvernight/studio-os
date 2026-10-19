import { describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import type { LibraryResource, LibraryVersion } from "./libraryApi";
import { hookVersionSummary, loadHookListContent, loadIncomingHookDependencies } from "./libraryHooks";

const resource = (id: string, overrides: Partial<LibraryResource> = {}): LibraryResource => ({
  id, kind: "hook", stable_key: "before-tool", scope: "studio", status: "active", active_version: 1, version: 3,
  created_at: "2026-10-11T10:00:00Z", updated_at: "2026-10-11T10:00:00Z", ...overrides,
});
const version = (number: number, overrides: Partial<LibraryVersion> = {}): LibraryVersion => ({
  id: `v${number}`, resource_id: "h1", version: number, title: "Hook",
  content: { content_schema: "studio.library.hook/v1", event: "pre_tool", mode: number === 1 ? "advisory" : "blocking" },
  dependencies: [], created_at: "2026-10-11T10:00:00Z", ...overrides,
});
const ok = (data: unknown) => ({ data, response: { ok: true, status: 200 } });
const fake = (GET: ReturnType<typeof vi.fn>) => ({ GET }) as unknown as StudioClient;

describe("contenu des listes Hooks", () => {
  it("sélectionne la version active et la dernière version d'un brouillon", async () => {
    const GET = vi.fn().mockResolvedValue(ok([version(2), version(1)]));
    const contents = await loadHookListContent(fake(GET), [resource("active"), resource("draft", { active_version: 0, status: "draft" })]);
    expect(contents.get("active")?.summary).toMatchObject({ version: 1, mode: "advisory", matcher: null });
    expect(contents.get("draft")?.summary).toMatchObject({ version: 2, mode: "blocking" });
  });

  it("ne présente pas une autre version si le pointeur actif est absent", async () => {
    const GET = vi.fn().mockResolvedValue(ok([version(2)]));
    expect((await loadHookListContent(fake(GET), [resource("h1")])).get("h1")).toEqual({ summary: null });
    expect(hookVersionSummary(version(1, { content: { content_schema: "studio.library.workflow/v1" } }))).toBeNull();
  });

  it("conserve les succès et les erreurs de lecture par ressource", async () => {
    const GET = vi.fn().mockImplementation((_path, options) => options.params.path.resource_id === "broken"
      ? Promise.reject(new Error("lecture impossible")) : Promise.resolve(ok([version(1)])));
    const contents = await loadHookListContent(fake(GET), [resource("ok"), resource("broken")]);
    expect(contents.get("ok")?.summary?.event).toBe("pre_tool");
    expect(contents.get("broken")).toEqual({ summary: null, error: "lecture impossible" });
  });

  it("borne à quatre le nombre de lectures simultanées", async () => {
    let pending = 0;
    let maximum = 0;
    const GET = vi.fn().mockImplementation(async () => {
      maximum = Math.max(maximum, ++pending);
      await new Promise((resolve) => setTimeout(resolve, 1));
      pending--;
      return ok([version(1)]);
    });
    await loadHookListContent(fake(GET), Array.from({ length: 12 }, (_, i) => resource(`h${i}`)));
    expect(maximum).toBe(4);
    expect(GET).toHaveBeenCalledTimes(12);
  });
});

describe("dépendances entrantes uses_hook", () => {
  it("lit les deux types sources et filtre clé, kind et relation", async () => {
    const GET = vi.fn().mockImplementation((path, options) => {
      if (path === "/api/v1/library") return Promise.resolve(ok([resource(options.params.query.kind, { kind: options.params.query.kind })]));
      return Promise.resolve(ok([version(2, { dependencies: [
        { kind: "hook", stable_key: "before-tool", version: 1, relation: "uses_hook" },
        { kind: "hook", stable_key: "before-tool", version: 2 },
        { kind: "hook", stable_key: "elsewhere", version: 1, relation: "uses_hook" },
        { kind: "rule", stable_key: "before-tool", version: 1, relation: "applies_rule" },
      ] })]));
    });
    const loaded = await loadIncomingHookDependencies(fake(GET), resource("h1"));
    expect(loaded.dependencies.map((pin) => [pin.resource.kind, pin.sourceVersion, pin.hookVersion])).toEqual([
      ["agent_definition", 2, 1], ["agent_definition", 2, 2], ["workflow", 2, 1], ["workflow", 2, 2],
    ]);
    expect(loaded.errors).toEqual([]);
  });

  it("pagine les sources et signale les versions illisibles", async () => {
    const GET = vi.fn().mockImplementation((path, options) => {
      if (path === "/api/v1/library") {
        const { kind, offset } = options.params.query;
        return Promise.resolve(ok(kind === "workflow" ? [] : offset === 0
          ? Array.from({ length: 100 }, (_, i) => resource(`a${i}`, { kind: "agent_definition" }))
          : [resource("last", { kind: "agent_definition" })]));
      }
      return options.params.path.resource_id === "last" ? Promise.reject(new Error("indisponible")) : Promise.resolve(ok([]));
    });
    const loaded = await loadIncomingHookDependencies(fake(GET), resource("h1"));
    expect(loaded.errors).toEqual(["indisponible"]);
    expect(GET).toHaveBeenCalledWith("/api/v1/library", { params: { query: { kind: "agent_definition", limit: 100, offset: 100 } } });
  });
});
