import { afterEach, describe, expect, it, vi } from "vitest";
import type { StudioClient } from "./api";
import {
  agentLabel,
  agentRef,
  loadActorNames,
  machineLabel,
  machineRef,
  resetActorNames,
  setActorNames,
} from "./actorNames";

const M = "269dc2bf-3d53-4679-807a-ba1b18f773ce";
const A = "c99dba71-c260-456f-8a0d-03a8e0b85420";

function fakeClient(machines: unknown, agents: unknown, ok = true): { client: StudioClient; get: ReturnType<typeof vi.fn> } {
  const get = vi.fn((path: string) =>
    Promise.resolve({ response: { ok }, data: path === "/api/v1/machines" ? machines : agents }),
  );
  return { client: { GET: get } as unknown as StudioClient, get };
}

afterEach(() => resetActorNames());

describe("actorNames", () => {
  it("nom connu : texte = nom, HTML = nom avec identifiant complet en infobulle", () => {
    setActorNames([{ id: M, display_name: "flo-laptop" }], [{ id: A, display_name: "Claude Code" }]);
    expect(machineLabel(M)).toBe("flo-laptop");
    expect(agentLabel(A)).toBe("Claude Code");
    expect(machineRef(M)).toBe(`<span class="actor-name" title="${M}">flo-laptop</span>`);
    expect(agentRef(A)).toContain(`title="${A}"`);
  });

  it("nom inconnu ou vide : repli sur l'identifiant court, toujours en infobulle", () => {
    setActorNames([{ id: M, display_name: "  " }], []);
    expect(machineLabel(M)).toBe("269dc2bf…");
    expect(agentRef(A)).toBe(`<code class="mono" title="${A}">c99dba71…</code>`);
    expect(machineRef(null)).toBe("—");
  });

  it("échappe le nom", () => {
    setActorNames([{ id: M, display_name: "<b>x</b>" }], []);
    expect(machineRef(M)).toContain("&lt;b&gt;x&lt;/b&gt;");
  });

  it("charge machines et agents, puis sert le cache sans relire", async () => {
    const { client, get } = fakeClient([{ id: M, display_name: "flo-laptop" }], [{ id: A, display_name: "Claude Code" }]);
    await loadActorNames(client);
    await loadActorNames(client);
    expect(get).toHaveBeenCalledTimes(2);
    expect(machineLabel(M)).toBe("flo-laptop");
    expect(agentLabel(A)).toBe("Claude Code");
  });

  it("échec de lecture : ne rejette pas et garde le cache précédent", async () => {
    setActorNames([{ id: M, display_name: "flo-laptop" }], []);
    const { client } = fakeClient(null, null, false);
    await expect(loadActorNames(client, true)).resolves.toBeUndefined();
    expect(machineLabel(M)).toBe("flo-laptop");
  });
});
