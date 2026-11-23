/**
 * Contexte studio actif (vitest, node) : la sélection de la fiche N1 fait
 * foi quand le contexte de session ne désigne aucun studio.
 */
import { describe, expect, it } from "vitest";
import {
  ACTIVE_STUDIO_STORAGE_KEY,
  getActiveStudioId,
  resolveActiveStudioId,
  setActiveStudioId,
} from "./studioContext";

function memoryStore(): Pick<Storage, "getItem" | "setItem" | "removeItem"> {
  const map = new Map<string, string>();
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, value),
    removeItem: (key: string) => void map.delete(key),
  };
}

describe("contexte studio actif", () => {
  it("mémorise et relit le studio sélectionné", () => {
    const store = memoryStore();
    setActiveStudioId("s1", store);
    expect(getActiveStudioId(store)).toBe("s1");
    expect(store.getItem(ACTIVE_STUDIO_STORAGE_KEY)).toBe("s1");
  });

  it("oublie le studio quand la sélection est levée", () => {
    const store = memoryStore();
    setActiveStudioId("s1", store);
    setActiveStudioId(null, store);
    expect(getActiveStudioId(store)).toBeNull();
  });

  it("lit une valeur illisible comme « aucun studio sélectionné »", () => {
    const store = memoryStore();
    store.setItem(ACTIVE_STUDIO_STORAGE_KEY, "");
    expect(getActiveStudioId(store)).toBeNull();
  });

  it("ne lève jamais sur un stockage refusant l'écriture", () => {
    const hostile = {
      getItem: () => {
        throw new Error("refusé");
      },
      setItem: () => {
        throw new Error("refusé");
      },
      removeItem: () => {
        throw new Error("refusé");
      },
    };
    expect(getActiveStudioId(hostile)).toBeNull();
    expect(() => setActiveStudioId("s1", hostile)).not.toThrow();
  });
});

describe("résolution du studio actif", () => {
  it("retient le studio du contexte de session quand il existe", () => {
    const store = memoryStore();
    setActiveStudioId("s2", store);
    expect(resolveActiveStudioId([{ id: "s1" }, { id: "s2" }], store)).toBe("s2");
  });

  it("retombe sur la sélection N1 quand le studio mémorisé a disparu", () => {
    const store = memoryStore();
    setActiveStudioId("disparu", store);
    expect(resolveActiveStudioId([{ id: "s1" }, { id: "s2" }], store)).toBe("s1");
  });

  it("renvoie null quand il n'y a aucun studio", () => {
    expect(resolveActiveStudioId([], memoryStore())).toBeNull();
  });
});
