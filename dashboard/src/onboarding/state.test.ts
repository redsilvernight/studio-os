// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from "vitest";
import {
  clearOnboardingState,
  INITIAL_ONBOARDING_STATE,
  loadOnboardingState,
  ONBOARDING_STORAGE_KEY,
  saveOnboardingState,
  type OnboardingState,
} from "./state";

function memStore(): Storage {
  const bag = new Map<string, string>();
  return {
    getItem: (key: string) => bag.get(key) ?? null,
    setItem: (key: string, value: string) => {
      bag.set(key, value);
    },
    removeItem: (key: string) => {
      bag.delete(key);
    },
  } as Storage;
}

describe("onboarding state", () => {
  it("starts as not_started on first run", () => {
    expect(loadOnboardingState(memStore())).toEqual(INITIAL_ONBOARDING_STATE);
  });

  it("round-trips the chosen identifiers, never a full path", () => {
    const store = memStore();
    const state: OnboardingState = {
      schema: 1,
      status: "in_progress",
      current: "memoire",
      projectId: "22222222-2222-4222-8222-222222222222",
      workspaceId: "11111111-1111-4111-8111-111111111111",
      folderName: "Mon jeu",
    };
    saveOnboardingState(state, store);
    const loaded = loadOnboardingState(store);
    expect(loaded.workspaceId).toBe("11111111-1111-4111-8111-111111111111");
    expect(JSON.stringify(loaded)).not.toContain("C:");
    expect(JSON.stringify(loaded)).not.toContain("token");
  });

  it("falls back to not_started on corrupt or foreign data", () => {
    const store = memStore();
    store.setItem(ONBOARDING_STORAGE_KEY, "not-json{{{");
    expect(loadOnboardingState(store).status).toBe("not_started");
    store.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({ schema: 99, status: "completed" }));
    expect(loadOnboardingState(store).status).toBe("not_started");
    store.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({ schema: 1, status: "mystery", current: "nope" }));
    const loaded = loadOnboardingState(store);
    expect(loaded.status).toBe("not_started");
    expect(loaded.current).toBe("bienvenue");
  });

  it("a failing storage never breaks the flow", () => {
    const broken = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
      removeItem: () => {
        throw new Error("denied");
      },
    } as unknown as Storage;
    expect(loadOnboardingState(broken).status).toBe("not_started");
    expect(() =>
      saveOnboardingState({ schema: 1, status: "completed", current: "termine" }, broken),
    ).not.toThrow();
    expect(() => clearOnboardingState(broken)).not.toThrow();
  });

  it("clear removes the key", () => {
    const store = memStore();
    saveOnboardingState({ schema: 1, status: "completed", current: "termine" }, store);
    clearOnboardingState(store);
    expect(store.getItem(ONBOARDING_STORAGE_KEY)).toBeNull();
  });
});

describe("onboarding state (real localStorage)", () => {
  beforeEach(() => {
    globalThis.localStorage.removeItem(ONBOARDING_STORAGE_KEY);
  });

  it("persists across loads in this browser profile", () => {
    saveOnboardingState({ schema: 1, status: "completed", current: "termine" });
    expect(loadOnboardingState().status).toBe("completed");
    clearOnboardingState();
    expect(loadOnboardingState().status).toBe("not_started");
  });
});
